"""Diff-based docs-to-eLabFTW sync with image upload and attachment support.

CLI tool — not intended for use as a library.
"""

import hashlib
import json
import os as _os
import re
import shutil
import tempfile
import markdown
import html as _html
from pathlib import Path

from .safety import atomic_write, write_json, safe_path, snapshot, local_transaction
from .client import ELabFTWClient
from .config import TargetConfig
from . import sync_log

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# eLabFTW の画像 URL から upload_id を抽出する正規表現。
# /uploads/{数字} の後に区切り文字（? # / 行末）が続くパターンにマッチ。
# ホスト名やパス前半は検証しない（外部 URL がマッチしても、id_map に
# 存在しない upload_id は無視されるため安全）。
# id が一致した場合は自サーバーの API 経由でダウンロードされる。
# eLabFTW の body HTML 内の画像 URL は相対パスか自サーバー URL のみのため、
# 外部 URL が /uploads/ を含むことは実運用上ありえない。
# 許容例: /uploads/100  /uploads/100/  /uploads/100?x=1  /uploads/100#frag
# 拒否例: /uploads/100/extra（サブパス付き）
UPLOAD_ID_RE = re.compile(r"/uploads/(\d+)(?:[?#]|/?$)")
UPLOAD_LONGNAME_RE = re.compile(r"[?&]f=([^&\s)]+)")
MD_EXTENSIONS = ["tables", "fenced_code", "codehilite", "toc", "nl2br"]

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm"})

# umask をモジュールロード時に1回だけ取得してキャッシュする。
# Python 標準ライブラリには umask を副作用なしに読む API がないため、
# os.umask(0) → os.umask(元値) で取得する。
# 本ツールは CLI 専用（単一プロセス・単一スレッド）であり、
# import 時の一瞬の umask 変更は実運用上問題にならない。
_UMASK = _os.umask(0)
_os.umask(_UMASK)

# 数式保護用: $$...$$ (ブロック) と $...$ (インライン) を退避・復元する。
# 仕様: $ の直前が \ (バックスラッシュ) の場合、数式の開始/終了とみなさない。
# これにより \$ はリテラルドル記号として扱われる。
# 制限: \\$ (バックスラッシュ2つ+ドル) も数式開始とみなさない（奇偶判定は非対応）。
_MATH_BLOCK_RE = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL)
_MATH_INLINE_RE = re.compile(r"(?<![\$\\])\$(?!\$)(.+?)(?<![\$\\])\$(?!\$)")


class ConflictError(Exception):
    """リモートが前回同期以降に変更されている。"""
    pass


def _compute_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _compute_meta_hash(title: str, category, tags: list[str]) -> str:
    """タイトル・カテゴリ・タグからメタデータハッシュを計算する。"""
    data = json.dumps({"title": title, "category": category, "tags": sorted(tags or [])},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _count_local_images(body: str) -> int:
    return sum(1 for m in IMAGE_RE.finditer(body) if not m.group(2).startswith(("http://", "https://")))


def _md_to_html(text: str) -> str:
    """Markdown → HTML 変換。LaTeX 数式（$$...$$ / $...$）を保護する。

    数式内の <, >, & は HTML エンティティに変換して復元する。
    \\$ はリテラルドル記号として扱い、数式開始とみなさない。
    """
    placeholders: list[str] = []

    def _save(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00MATH{len(placeholders) - 1}\x00"

    text = _MATH_BLOCK_RE.sub(_save, text)
    text = _MATH_INLINE_RE.sub(_save, text)
    result = markdown.markdown(text, extensions=MD_EXTENSIONS)
    for i, original in enumerate(placeholders):
        result = result.replace(f"\x00MATH{i}\x00", _html.escape(original, quote=False))
    return result


def _image_local_name(entity: str, entity_id: int, real_name: str) -> str:
    """画像のローカルファイル名を生成する（命名規則の一元管理）。

    形式: {entity}_{entity_id}_{real_name}
    逆変換は _parse_image_local_name で行う。
    """
    return f"{entity}_{entity_id}_{real_name}"


# eLabFTW API の entity 種別プレフィックス（items / experiments のみ）
_ENTITY_PREFIXES = ("items_", "experiments_")


def _parse_image_local_name(filename: str) -> str | None:
    """_image_local_name で生成されたファイル名から real_name を復元する。

    形式に合致しない場合は None を返す。
    eLabFTW の entity 種別は items / experiments の 2 種のみ。
    新しい entity 種別が追加された場合は _ENTITY_PREFIXES も更新すること。
    """
    for prefix in _ENTITY_PREFIXES:
        if filename.startswith(prefix):
            rest = filename[len(prefix):]
            idx = rest.find("_")
            if idx != -1 and rest[:idx].isdigit():
                return rest[idx + 1:]
    return None


def _download_images(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, strict: bool = False) -> str:
    """Markdown 内の eLabFTW 画像 URL をローカルにダウンロードし相対パスに書き換える。"""
    try:
        uploads = client.list_uploads(entity, entity_id)
    except Exception as e:
        if strict:
            raise
        print(f"    ⚠ 添付ファイル一覧の取得に失敗（{entity} #{entity_id}、画像のローカル化をスキップ）: {e}")
        return body
    upload_map = {}
    id_map = {}
    for u in uploads:
        ln = u.get("long_name")
        if ln:
            upload_map[ln] = u
        uid = u.get("id")
        if uid is not None:
            id_map[str(uid)] = u

    def replace_match(m):
        alt, src = m.group(1), m.group(2)
        if "app/download.php" not in src and "/uploads/" not in src:
            return m.group(0)
        # long_name でマッチ（download.php 形式）
        matched_upload = None
        for ln, u in upload_map.items():
            if ln in src:
                matched_upload = u
                break
        # upload_id でマッチ（/api/v2/.../uploads/{id} 形式）
        if not matched_upload:
            uid_match = UPLOAD_ID_RE.search(src)
            if uid_match:
                matched_upload = id_map.get(uid_match.group(1))
        if not matched_upload:
            # list_uploads にない画像: 絶対 URL に変換して保持
            if "app/download.php" in src and not src.startswith(("http://", "https://")):
                abs_url = f"{client.base_url}/{src.lstrip('/')}"
                print(f"    画像を絶対 URL に変換: {Path(src).name[:40]}")
                return f"![{alt}]({abs_url})"
            return m.group(0)
        real_name = matched_upload.get("real_name", f"upload_{matched_upload['id']}")
        local_name = _image_local_name(entity, entity_id, real_name)
        img_dir = docs_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        dest = safe_path(img_dir, local_name)
        if strict or not dest.exists():
            data = client.download_upload(
                entity_type=entity,
                entity_id=entity_id,
                upload_id=matched_upload["id"],
            )
            atomic_write(dest, data)
            print(f"    画像をダウンロード: {real_name}")
        return f"![{alt}](images/{local_name})"

    return IMAGE_RE.sub(replace_match, body)


def _normalize_remote_image_urls(body: str, entity: str, entity_id: int, client: ELabFTWClient, uploads=None) -> str:
    """diff 比較用: リモート MD 内の eLabFTW 画像 URL をローカル相対パスに書き換える（DL なし）。"""
    try:
        if uploads is None:
            uploads = client.list_uploads(entity, entity_id)
    except Exception as e:
        print(f"    ⚠ 添付ファイル一覧の取得に失敗（{entity} #{entity_id}、画像 URL の正規化をスキップ）: {e}")
        return body
    upload_map = {}
    id_map = {}
    for u in uploads:
        ln = u.get("long_name")
        if ln:
            upload_map[ln] = u
        uid = u.get("id")
        if uid is not None:
            id_map[str(uid)] = u

    def replace_match(m):
        alt, src = m.group(1), m.group(2)
        if "app/download.php" not in src and "/uploads/" not in src:
            return m.group(0)
        matched = None
        for ln, u in upload_map.items():
            if ln in src:
                matched = u
                break
        if not matched:
            uid_match = UPLOAD_ID_RE.search(src)
            if uid_match:
                matched = id_map.get(uid_match.group(1))
        if matched:
            real_name = matched.get("real_name", f"upload_{matched['id']}")
            return f"![{alt}](images/{_image_local_name(entity, entity_id, real_name)})"
        return m.group(0)

    return IMAGE_RE.sub(replace_match, body)


def _compute_file_hash(filepath: Path) -> str:
    """ファイルの SHA-256 ハッシュを計算する。"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_asset_path(docs_dir: Path, project_root: Path, source: str, strict=False) -> Path:
    root = project_root.resolve()
    candidates = [(docs_dir / source).absolute(), (project_root / source).absolute()]
    for index, candidate in enumerate(candidates):
        if strict:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"プロジェクト外のファイルは送信できません: {source}")
            if any(part.startswith(".") and part not in (".", "..") for part in resolved.relative_to(root).parts):
                raise ValueError(f"隠しファイル・設定領域は送信できません: {source}")
            for part in (candidate, *candidate.parents):
                if part == root:
                    break
                if part.is_symlink():
                    raise ValueError(f"シンボリックリンクは送信できません: {source}")
        if candidate.exists() or index == len(candidates) - 1:
            return candidate.resolve()
    raise FileNotFoundError(source)


def _rewrite_images(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path, strict: bool = False) -> str:
    """Markdown 内のローカル画像を eLabFTW にアップロードし URL に書き換える。

    upload_file はファイルパスの basename を real_name としてリモートに保存する。
    プレフィックス付きローカル名（例: items_1_photo.png）は real_name（photo.png）に
    戻してからアップロードし、次回 pull 時の命名安定性を保つ。
    """
    existing: dict[str, list[dict]] = {}
    try:
        for u in client.list_uploads(entity, entity_id):
            rn = u.get("real_name")
            ln = u.get("long_name")
            st = u.get("storage")
            if rn and ln and st:
                existing.setdefault(rn, []).append({
                    "url": f"{client.base_url}/app/download.php?f={ln}&name={rn}&storage={st}",
                    "size": int(u.get("filesize", 0) or 0),
                    "id": u.get("id"),
                    "hash": u.get("hash") or u.get("sha256") or None,
                })
        # id 昇順でソートし、最小 id の添付を正本として安定させる
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        if strict:
            raise

    tmp_dirs: list[str] = []
    stale_ids: list[int] = []

    def replace_match(m):
        alt, src = m.group(1), m.group(2)
        if src.startswith(("http://", "https://")):
            return m.group(0)
        # 動画ファイルは _rewrite_videos で処理するためスキップ
        if _is_video(src):
            return m.group(0)
        img_path = _resolve_asset_path(docs_dir, project_root, src, strict)
        if not img_path.exists():
            if strict:
                raise FileNotFoundError(f"画像が見つかりません: {src}")
            print(f"    ⚠ 画像が見つかりません: {src}")
            return m.group(0)
        real_name = _parse_image_local_name(img_path.name) or img_path.name
        entries = existing.get(real_name, [])
        local_size = img_path.stat().st_size
        local_hash = _compute_file_hash(img_path)
        # サイズ一致 → ハッシュでも確認（同名・同サイズ・別内容を検出）
        reuse = None
        for e in entries:
            if e["size"] and e["size"] == local_size:
                # リモートのハッシュフィールドがあれば使う、なければサイズ一致で再利用
                remote_hash = e.get("hash")
                if strict and not remote_hash and e.get("id") is not None:
                    remote_hash = hashlib.sha256(client.download_upload(entity_type=entity, entity_id=entity_id, upload_id=e["id"])).hexdigest()
                if remote_hash and remote_hash != local_hash:
                    continue
                reuse = e
                break
        if reuse:
            # サイズ（+ハッシュ）一致の1件を再利用し、残りの重複は削除予約
            for e in entries:
                if e is not reuse and e.get("id") is not None:
                    stale_ids.append(e["id"])
            print(f"    ✓ {real_name}（既存アップロードを再利用）")
            return f"![{alt}]({reuse['url']})"
        # サイズ不一致 → 新規アップロードを試み、成功時のみ旧添付を削除予約
        if real_name != img_path.name:
            td = tempfile.mkdtemp()
            tmp_dirs.append(td)
            tmp_file = Path(td) / real_name
            shutil.copy2(img_path, tmp_file)
            upload_path = str(tmp_file)
        else:
            upload_path = str(img_path)
        print(f"    画像をアップロード中: {real_name}")
        result = client.upload_file(entity, entity_id, upload_path)
        if result.get("url"):
            for e in entries:
                if e.get("id") is not None:
                    stale_ids.append(e["id"])
            print(f"    ✓ {real_name}")
            return f"![{alt}]({result['url']})"
        if strict:
            raise RuntimeError(f"アップロード失敗: {real_name}")
        print(f"    ✗ アップロード失敗: {real_name}")
        return m.group(0)

    try:
        result = IMAGE_RE.sub(replace_match, body)
        # アップロード成功後に古い添付を削除（失敗しても本文は壊さない）
        for uid in ([] if strict else stale_ids):
            try:
                client.delete_upload(entity, entity_id, uid)
            except Exception:
                pass
        return result
    finally:
        for td in tmp_dirs:
            shutil.rmtree(td, ignore_errors=True)


# ── ローカルファイルリンク ↔ eLabFTW URL 変換 ───────────────

# Markdown リンク（画像以外）: [text](path)
_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")

# eLabFTW の記事 URL パターン:
#   items → {base_url}/database.php?mode=view&id={id}
#   experiments → {base_url}/experiments.php?mode=view&id={id}
# フラグメント部分もキャプチャして逆変換時に保持する
_ELAB_URL_RE = re.compile(
    r"(?P<base>https?://[^/]+)/(?P<page>database|experiments)\.php\?mode=view&id=(?P<id>\d+)(?P<fragment>#[^\s)]*)?")

# eLabFTW の entity タイプと URL ページ名の対応
_ENTITY_TO_PAGE = {"items": "database", "experiments": "experiments"}
_PAGE_TO_ENTITY = {"database": "items", "experiments": "experiments"}

def _hosts_match(base_url: str, link_base: str) -> bool:
    """base_url と link_base のホスト部分が完全一致するか判定する。

    前方一致ではなくホスト完全一致を使い、
    elab.example.com と elab.example.co の誤マッチを防ぐ。
    """
    from urllib.parse import urlparse
    return urlparse(base_url).netloc == urlparse(link_base).netloc


def _rewrite_local_links(body: str, entity: str, base_url: str,
                         mapping: dict, all_mappings: list[tuple[str, str, dict]] | None = None) -> str:
    """Markdown 本文中のローカルファイルリンクを eLabFTW の記事 URL に変換する。

    each モード専用。merge モードでは 1 ファイル = 1 エンティティの対応関係がないため非対応。

    対象: [text](./file.md), [text](file.md), [text](../other_dir/file.md)
    非対象: 画像リンク (![...]()), 外部URL (http://...), アンカーリンク (#...), 非.mdファイル

    Args:
        body: Markdown 本文
        entity: このファイルが属する entity タイプ ("items" / "experiments")
        base_url: eLabFTW のベース URL
        mapping: 現在のターゲットの {filename: entity_id} マッピング
        all_mappings: 全ターゲットの [(docs_dir, entity_type, {filename: eid}), ...] リスト
                      他ターゲットのファイルへのリンクも解決するために使用
    """
    def replace_link(m):
        text, href = m.group(1), m.group(2)

        # 外部 URL、アンカーリンク、非 .md ファイルはスキップ
        if href.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        link_path, sep, fragment = href.partition("#")
        if not link_path.endswith(".md"):
            return m.group(0)
        fragment_suffix = sep + fragment

        # パスからファイル名を抽出
        target_filename = Path(link_path).name

        # 1. 同じターゲット内の mapping を検索
        eid = mapping.get(target_filename)
        target_entity = entity
        if eid is not None:
            page = _ENTITY_TO_PAGE[target_entity]
            url = f"{base_url}/{page}.php?mode=view&id={eid}{fragment_suffix}"
            return f"[{text}]({url})"

        # 2. 他のターゲットの mapping を検索
        if all_mappings:
            for _docs_dir, other_entity, other_mapping in all_mappings:
                eid = other_mapping.get(target_filename)
                if eid is not None:
                    page = _ENTITY_TO_PAGE[other_entity]
                    url = f"{base_url}/{page}.php?mode=view&id={eid}{fragment_suffix}"
                    return f"[{text}]({url})"

        # 解決できないリンクはそのまま残す
        return m.group(0)

    return _LINK_RE.sub(replace_link, body)


def _rewrite_elab_links_to_local(body: str, base_url: str,
                                 mapping: dict, entity: str,
                                 all_mappings: list[tuple[str, str, dict]] | None = None,
                                 target_docs_dir: str = "") -> str:
    """eLabFTW の記事 URL をローカルファイルリンクに逆変換する。

    each モード専用。merge モードでは mapping が空のため変換は行われない。

    対象: [text](https://elab.example.com/items.php?mode=view&id=42)
    → [text](./file.md)  (同一ターゲット内)
    → [text](../other_dir/file.md)  (他ターゲット)

    Args:
        body: Markdown/HTML 本文
        base_url: eLabFTW のベース URL
        mapping: 現在のターゲットの {filename: entity_id}
        entity: 現在のターゲットの entity タイプ
        all_mappings: 全ターゲットの [(docs_dir, entity_type, {filename: eid}), ...]
        target_docs_dir: 現在のターゲットの docs_dir（相対パス計算用）
    """
    # reverse mapping: entity_id → filename
    reverse = {v: k for k, v in mapping.items()}

    # 全ターゲットの reverse mapping
    all_reverse: list[tuple[str, str, dict[int, str]]] = []
    if all_mappings:
        for docs_dir, other_entity, other_mapping in all_mappings:
            all_reverse.append((docs_dir, other_entity, {v: k for k, v in other_mapping.items()}))

    def replace_link(m):
        text, href = m.group(1), m.group(2)

        match = _ELAB_URL_RE.match(href)
        if not match:
            return m.group(0)

        link_base = match.group("base")
        link_page = match.group("page")  # "database" or "experiments"
        link_entity = _PAGE_TO_ENTITY.get(link_page, link_page)  # → "items" or "experiments"
        link_id = int(match.group("id"))
        fragment = match.group("fragment") or ""  # #section など

        # ホスト完全一致でなければスキップ（外部 eLabFTW リンク）
        if not _hosts_match(base_url, link_base):
            return m.group(0)

        # 1. 同じターゲット内で解決
        if link_entity == entity and link_id in reverse:
            filename = reverse[link_id]
            return f"[{text}](./{filename}{fragment})"

        # 2. 他ターゲットで解決
        for docs_dir, other_entity, other_reverse in all_reverse:
            if link_entity == other_entity and link_id in other_reverse:
                filename = other_reverse[link_id]
                # 相対パスを計算
                if target_docs_dir and docs_dir != target_docs_dir:
                    rel_path = _os.path.relpath(
                        str(Path(docs_dir) / filename),
                        str(Path(target_docs_dir))
                    )
                    return f"[{text}]({rel_path}{fragment})"
                else:
                    return f"[{text}](./{filename}{fragment})"

        # 解決できない eLabFTW リンクはそのまま残す
        return m.group(0)

    return _LINK_RE.sub(replace_link, body)


def _is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def _rewrite_videos(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path, strict: bool = False) -> str:
    """Markdown 内の動画リンクを eLabFTW にアップロードし <video> タグに書き換える。

    対象:
      - 通常リンク [text](video.mp4)
      - 画像記法 ![alt](video.mp4)

    変換結果: <video src="upload_url" controls>text</video>
    """
    existing: dict[str, list[dict]] = {}
    try:
        for u in client.list_uploads(entity, entity_id):
            rn = u.get("real_name")
            ln = u.get("long_name")
            st = u.get("storage")
            if rn and ln and st:
                existing.setdefault(rn, []).append({
                    "url": f"{client.base_url}/app/download.php?f={ln}&name={rn}&storage={st}",
                    "size": int(u.get("filesize", 0) or 0),
                    "id": u.get("id"),
                })
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        if strict:
            raise

    stale_ids: list[int] = []

    def _process_video_match(alt: str, src: str, full_match: str) -> str:
        if src.startswith(("http://", "https://")):
            return full_match
        if not _is_video(src):
            return full_match

        video_path = _resolve_asset_path(docs_dir, project_root, src, strict)
        if not video_path.exists():
            if strict:
                raise FileNotFoundError(f"動画が見つかりません: {src}")
            print(f"    ⚠ 動画が見つかりません: {src}")
            return full_match

        real_name = video_path.name
        entries = existing.get(real_name, [])
        local_size = video_path.stat().st_size

        reuse = next((e for e in entries if e["size"] and e["size"] == local_size), None)
        if reuse and strict:
            actual = client.download_upload(entity_type=entity, entity_id=entity_id, upload_id=reuse["id"])
            if hashlib.sha256(actual).hexdigest() != _compute_file_hash(video_path):
                reuse = None
        if reuse:
            for e in entries:
                if e is not reuse and e.get("id") is not None:
                    stale_ids.append(e["id"])
            print(f"    ✓ {real_name}（既存アップロードを再利用）")
            return f'<video src="{reuse["url"]}" controls>{alt}</video>'

        print(f"    動画をアップロード中: {real_name}")
        result = client.upload_file(entity, entity_id, str(video_path))
        if result.get("url"):
            for e in entries:
                if e.get("id") is not None:
                    stale_ids.append(e["id"])
            print(f"    ✓ {real_name}")
            return f'<video src="{result["url"]}" controls>{alt}</video>'
        if strict:
            raise RuntimeError(f"アップロード失敗: {real_name}")
        print(f"    ✗ アップロード失敗: {real_name}")
        return full_match

    # IMAGE_RE と _LINK_RE の両方から動画を検出。重複排除して後ろから置換。
    matches: list[tuple[int, int, str, str, str]] = []
    for m in IMAGE_RE.finditer(body):
        if _is_video(m.group(2)):
            matches.append((m.start(), m.end(), m.group(1), m.group(2), m.group(0)))
    for m in _LINK_RE.finditer(body):
        if _is_video(m.group(2)):
            matches.append((m.start(), m.end(), m.group(1), m.group(2), m.group(0)))

    matches.sort(key=lambda x: x[0])
    unique_matches: list[tuple[int, int, str, str, str]] = []
    last_end = -1
    for match in matches:
        if match[0] >= last_end:
            unique_matches.append(match)
            last_end = match[1]

    result = body
    for start, end, alt, src, full in reversed(unique_matches):
        replacement = _process_video_match(alt, src, full)
        result = result[:start] + replacement + result[end:]

    for uid in ([] if strict else stale_ids):
        try:
            client.delete_upload(entity, entity_id, uid)
        except Exception:
            pass
    return result


def _count_local_videos(body: str) -> int:
    """本文中のローカル動画リンク数をカウントする。"""
    count = 0
    for m in IMAGE_RE.finditer(body):
        src = m.group(2)
        if not src.startswith(("http://", "https://")) and _is_video(src):
            count += 1
    for m in _LINK_RE.finditer(body):
        src = m.group(2)
        if not src.startswith(("http://", "https://")) and _is_video(src):
            count += 1
    return count


def _rewrite_file_links(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path, strict: bool = False) -> str:
    """Markdown 内の非画像・非動画ファイルリンクを eLabFTW にアップロードし URL に書き換える。

    対象:
      - 通常リンク [text](file.pdf)
      - 画像記法 ![alt](file.pdf) （画像でも動画でもない → [alt](url) に正規化）

    変換結果: [text](upload_url)

    注: .md ファイルへのリンクはファイル間リンク変換 (_rewrite_local_links) で処理するため除外。
    """
    existing: dict[str, list[dict]] = {}
    try:
        for u in client.list_uploads(entity, entity_id):
            rn = u.get("real_name")
            ln = u.get("long_name")
            st = u.get("storage")
            if rn and ln and st:
                existing.setdefault(rn, []).append({
                    "url": f"{client.base_url}/app/download.php?f={ln}&name={rn}&storage={st}",
                    "size": int(u.get("filesize", 0) or 0),
                    "id": u.get("id"),
                })
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        if strict:
            raise

    stale_ids: list[int] = []

    def _process_file_match(alt: str, src: str, full_match: str) -> str:
        if src.startswith(("http://", "https://", "#", "mailto:", "data:")):
            return full_match
        if _is_image(src) or _is_video(src):
            return full_match
        # .md ファイルはファイル間リンク変換で処理するためスキップ
        if src.split("#", 1)[0].endswith(".md"):
            return full_match

        file_path = _resolve_asset_path(docs_dir, project_root, src, strict)
        if not file_path.exists():
            if strict:
                raise FileNotFoundError(f"ファイルが見つかりません: {src}")
            print(f"    ⚠ ファイルが見つかりません: {src}")
            return full_match

        real_name = file_path.name
        entries = existing.get(real_name, [])
        local_size = file_path.stat().st_size

        reuse = next((e for e in entries if e["size"] and e["size"] == local_size), None)
        if reuse and strict:
            actual = client.download_upload(entity_type=entity, entity_id=entity_id, upload_id=reuse["id"])
            if hashlib.sha256(actual).hexdigest() != _compute_file_hash(file_path):
                reuse = None
        if reuse:
            for e in entries:
                if e is not reuse and e.get("id") is not None:
                    stale_ids.append(e["id"])
            print(f"    ✓ {real_name}（既存アップロードを再利用）")
            return f'[{alt}]({reuse["url"]})'

        print(f"    ファイルをアップロード中: {real_name}")
        result = client.upload_file(entity, entity_id, str(file_path))
        if result.get("url"):
            for e in entries:
                if e.get("id") is not None:
                    stale_ids.append(e["id"])
            print(f"    ✓ {real_name}")
            return f'[{alt}]({result["url"]})'
        if strict:
            raise RuntimeError(f"アップロード失敗: {real_name}")
        print(f"    ✗ アップロード失敗: {real_name}")
        return full_match

    # IMAGE_RE と _LINK_RE の両方から非画像・非動画ファイルを検出
    matches: list[tuple[int, int, str, str, str]] = []
    for m in IMAGE_RE.finditer(body):
        src = m.group(2)
        if not src.startswith(("http://", "https://", "#", "mailto:", "data:")) and not _is_image(src) and not _is_video(src) and not src.split("#", 1)[0].endswith(".md"):
            matches.append((m.start(), m.end(), m.group(1), src, m.group(0)))
    for m in _LINK_RE.finditer(body):
        src = m.group(2)
        if not src.startswith(("http://", "https://", "#", "mailto:", "data:")) and not _is_image(src) and not _is_video(src) and not src.split("#", 1)[0].endswith(".md"):
            matches.append((m.start(), m.end(), m.group(1), src, m.group(0)))

    matches.sort(key=lambda x: x[0])
    unique_matches: list[tuple[int, int, str, str, str]] = []
    last_end = -1
    for match in matches:
        if match[0] >= last_end:
            unique_matches.append(match)
            last_end = match[1]

    result = body
    for start, end, alt, src, full in reversed(unique_matches):
        replacement = _process_file_match(alt, src, full)
        result = result[:start] + replacement + result[end:]

    for uid in ([] if strict else stale_ids):
        try:
            client.delete_upload(entity, entity_id, uid)
        except Exception:
            pass
    return result


def _count_local_file_links(body: str) -> int:
    """本文中の非画像・非動画ローカルファイルリンク数をカウントする。"""
    count = 0
    for m in IMAGE_RE.finditer(body):
        src = m.group(2)
        if not src.startswith(("http://", "https://", "#", "mailto:", "data:")) and not _is_image(src) and not _is_video(src) and not src.split("#", 1)[0].endswith(".md"):
            count += 1
    for m in _LINK_RE.finditer(body):
        src = m.group(2)
        if not src.startswith(("http://", "https://", "#", "mailto:", "data:")) and not _is_image(src) and not _is_video(src) and not src.split("#", 1)[0].endswith(".md"):
            count += 1
    return count


def _count_local_attachments(attachments_dir: Path | None) -> int:
    if not attachments_dir or not attachments_dir.is_dir():
        return 0
    return sum(1 for f in attachments_dir.iterdir() if f.is_file() and not _is_image(f.name))


def _sync_attachments(attachments_dir: Path | None, entity: str, entity_id: int, client: ELabFTWClient, *, force: bool = False, pattern: str = "*", prune: bool = False, strict: bool = False) -> bool:
    """attachments_dir 内の非画像ファイルをリモートにアップロードする。

    差分検知: サイズ一致 → リモートに hash/sha256 フィールドがあれば
    ローカル SHA-256 と比較。strict=Trueではhash不在時に実体を取得して比較する。
    strict=Falseは旧呼び出し用で、hash不在時はサイズ一致だけで再利用する。
    strict=Trueは一覧取得エラーを伝播し、旧添付を保持する（明示pruneは別）。
    force=True の場合は一致でも再アップロードする。
    pattern: glob パターンでアップロード対象をフィルタ。
    prune: True の場合、ローカルに存在しないリモート添付を削除する。

    Returns:
        True: 全ファイル同期成功（またはスキップ）
        False: 1件以上のアップロードに失敗
    """
    if not attachments_dir or not attachments_dir.is_dir():
        return True
    from fnmatch import fnmatch
    local_files = [f for f in sorted(attachments_dir.iterdir())
                   if f.is_file() and not _is_image(f.name) and fnmatch(f.name, pattern)]
    if not local_files and not prune:
        return True

    existing: dict[str, list[dict]] = {}
    try:
        for u in client.list_uploads(entity, entity_id):
            rn = u.get("real_name")
            if rn and not _is_image(rn):
                existing.setdefault(rn, []).append(u)
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        if strict:
            raise

    all_success = True
    for f in local_files:
        entries = existing.get(f.name, [])
        local_size = f.stat().st_size
        local_hash = _compute_file_hash(f) if not force else None
        reuse = None
        if not force:
            for e in entries:
                if int(e.get("filesize", 0) or 0) == local_size:
                    remote_hash = e.get("hash") or e.get("sha256")
                    if strict and not remote_hash and e.get("id") is not None:
                        remote_hash = hashlib.sha256(client.download_upload(entity_type=entity, entity_id=entity_id, upload_id=e["id"])).hexdigest()
                    if remote_hash and remote_hash != local_hash:
                        continue
                    reuse = e
                    break
        if reuse:
            print(f"    ✓ {f.name}（既存添付を再利用）")
            stale = [e for e in entries if e is not reuse and e.get("id") is not None]
        else:
            print(f"    添付ファイルをアップロード中: {f.name}")
            result = client.upload_file(entity, entity_id, str(f))
            if result.get("url"):
                print(f"    ✓ {f.name}")
                stale = [e for e in entries if e.get("id") is not None]
            else:
                print(f"    ✗ アップロード失敗: {f.name}")
                stale = []
                all_success = False
        for e in ([] if strict else stale):
            try:
                client.delete_upload(entity, entity_id, e["id"])
            except Exception:
                pass

    # prune: ローカルに存在しないリモート添付を削除（pattern に一致するもののみ）
    if prune:
        local_names = {f.name for f in local_files}
        for rn, entries in existing.items():
            if rn not in local_names and fnmatch(rn, pattern):
                for e in entries:
                    if e.get("id") is not None:
                        try:
                            client.delete_upload(entity, entity_id, e["id"])
                            print(f"    🗑 {rn}（リモートから削除）")
                        except Exception as exc:
                            print(f"    ⚠ {rn} の削除に失敗: {exc}")
                            all_success = False

    return all_success


def _download_attachments(entity: str, entity_id: int, client: ELabFTWClient, attachments_dir: Path, strict: bool = False) -> None:
    """リモートの非画像添付ファイルをローカルにダウンロードする。

    書き込みはテンポラリファイル経由で行い、既存ファイルの部分破損を防ぐ。
    fsync は行わないため、電源断やカーネルクラッシュ時のデータ保全は保証しない。
    本ツールは単一プロセスでの実行を前提としている。
    """
    try:
        uploads = client.list_uploads(entity, entity_id)
    except Exception as e:
        if strict:
            raise
        print(f"    ⚠ 添付ファイル一覧の取得に失敗: {e}")
        return
    attachments_dir.mkdir(parents=True, exist_ok=True)
    for u in uploads:
        rn = u.get("real_name")
        if not rn or _is_image(rn):
            continue
        # パストラバーサル防止: basename のみ使用
        safe_name = Path(rn).name
        if not safe_name or safe_name in (".", ".."):
            print(f"    ⚠ 不正なファイル名をスキップ: {rn!r}")
            continue
        dest = safe_path(attachments_dir, safe_name)
        remote_size = int(u.get("filesize", 0) or 0)
        if dest.exists() and remote_size:
            local_size = dest.stat().st_size
            if local_size == remote_size:
                # サイズ一致 → ハッシュも確認（リモートにハッシュがある場合）
                remote_hash = u.get("hash") or u.get("sha256")
                if remote_hash:
                    local_hash = _compute_file_hash(dest)
                    if local_hash == remote_hash:
                        continue
                elif not strict:
                    continue
        try:
            overwriting = dest.exists()
            orig_mode = dest.stat().st_mode & 0o777 if overwriting else None
            data = client.download_upload(entity_type=entity, entity_id=entity_id, upload_id=u["id"])
            # テンポラリファイルに書いてからリネーム（既存ファイル保護）
            tmp_file = None
            try:
                tmp_file = tempfile.NamedTemporaryFile(
                    dir=attachments_dir, prefix=f".{safe_name}.", delete=False)
                tmp_file.write(data)
                tmp_file.close()
                tp = Path(tmp_file.name)
                if orig_mode is not None:
                    tp.chmod(orig_mode)
                else:
                    tp.chmod(0o666 & ~_UMASK)
                tp.replace(dest)
            except Exception:
                if tmp_file is not None:
                    try:
                        tmp_file.close()
                    except Exception:
                        pass
                    Path(tmp_file.name).unlink(missing_ok=True)
                raise
            if overwriting:
                print(f"    ⚠ 上書き: {safe_name}（{entity} #{entity_id} の添付で既存ファイルを置換）")
            print(f"    添付ファイルをダウンロード: {safe_name}")
        except Exception as e:
            if strict:
                raise
            print(f"    ⚠ 添付ファイルのダウンロードに失敗: {safe_name}: {e}")



def _sync_tags(client: ELabFTWClient, entity_type: str, entity_id: int, desired_tags: list[str]) -> None:
    """設定のタグをリモートに追記する（既存タグは外さない）。best-effort。"""
    if not desired_tags:
        return True
    try:
        remote = client.get_tags(entity_type, entity_id)
        remote_names = {(t.get("tag") if isinstance(t, dict) else str(t)) for t in remote}
        for tag in desired_tags:
            if tag not in remote_names:
                client.add_tag(entity_type, entity_id, tag)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("タグ同期失敗", exc_info=True)
        print(f"    ⚠ タグ同期に失敗しました（本文の同期は成功しています）")
        return False
    return True


def _sync_category(client: ELabFTWClient, entity_type: str, entity_id: int, category) -> None:
    """設定のカテゴリをリモートに設定する。best-effort。"""
    if category is None:
        return True
    try:
        cat_id = client.resolve_category_id(entity_type, category)
        client.patch_entity(entity_type, entity_id, category=cat_id)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("カテゴリ同期失敗", exc_info=True)
        print(f"    ⚠ カテゴリ同期に失敗しました（本文の同期は成功しています）")
        return False
    return True


class EachDocsSyncer:
    """One file per entity, with shared three-way state inspection."""

    SUFFIXES = (".hash", ".remote_hash", ".meta_hash", ".assets_hash", ".state.json")

    def __init__(self, client, target, project_root):
        self.client = client
        self.target = target
        self.entity = target.entity
        self.project_root = Path(project_root).resolve()
        self.docs_dir = self.project_root / target.docs_dir
        self.mapping_file = (self.project_root / target.id_file).parent / "mapping.json"
        self.hash_dir = self.mapping_file.parent
        self.failures = 0
        self.skipped = 0

    def backup_paths(self):
        paths = [self.docs_dir, self.hash_dir]
        if self.target.attachments_dir:
            paths.append(self.project_root / self.target.attachments_dir)
        return paths

    def _load_mapping(self, *, migrate=True):
        if self.mapping_file.exists():
            mapping = json.loads(self.mapping_file.read_text(encoding="utf-8"))
        else:
            legacy = self.project_root / ".elab-sync-ids/mapping.json"
            mapping = {}
            if legacy.exists() and legacy != self.mapping_file:
                mapping = {name: eid for name, eid in json.loads(legacy.read_text(encoding="utf-8")).items()
                           if (self.docs_dir / name).is_file()}
                if mapping and migrate:
                    snapshot(self.project_root, [self.hash_dir], "旧紐付けの移行")
                    self._save_mapping(mapping)
        if not isinstance(mapping, dict) or not all(isinstance(n, str) and Path(n).name == n and n not in ("", ".", "..")
                                                    and isinstance(e, int) and e > 0 for n, e in mapping.items()):
            raise ValueError(f"紐付け情報の形式が不正です: {self.mapping_file}")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("同じリモートIDに複数文書が紐付いています。紐付けを修正してください")
        return mapping

    def _save_mapping(self, mapping):
        write_json(self.mapping_file, mapping)

    def _hash_path(self, filename):
        return self.hash_dir / f"{filename}.hash"

    def _remote_hash_path(self, filename):
        return self.hash_dir / f"{filename}.remote_hash"

    def _meta_hash_path(self, filename):
        return self.hash_dir / f"{filename}.meta_hash"

    def _state(self, filename):
        path = self.hash_dir / f"{filename}.state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _has_changed(self, filename, body):
        state = self._state(filename)
        hp = self._hash_path(filename)
        saved = state["local_hash"] if state else hp.read_text().strip() if hp.exists() else None
        return saved != _compute_hash(body)

    def _save_hash(self, filename, body):
        atomic_write(self._hash_path(filename), _compute_hash(body) + "\n")

    def _save_remote_hash(self, filename, body):
        atomic_write(self._remote_hash_path(filename), _compute_hash(body) + "\n")

    def _has_meta_changed(self, filename, title, category, tags):
        state = self._state(filename)
        if state and state.get("body_format", self.target.body_format) != self.target.body_format:
            return True
        hp = self._meta_hash_path(filename)
        saved = state["meta_hash"] if state else hp.read_text().strip() if hp.exists() else None
        return saved is not None and saved != _compute_meta_hash(title, category, tags)

    def _save_meta_hash(self, filename, title, category, tags):
        atomic_write(self._meta_hash_path(filename), _compute_meta_hash(title, category, tags) + "\n")

    def _get_entity(self, eid):
        return self.client.get_experiment(eid) if self.entity == "experiments" else self.client.get_item(eid)

    def _create_entity(self, title):
        # Deliberately no PATCH here: persist the POST's ID before updating fields.
        return self.client.create_experiment() if self.entity == "experiments" else self.client.create_item()

    def _update_entity(self, eid, **fields):
        if self.entity == "experiments":
            self.client.update_experiment(eid, **fields)
        else:
            self.client.update_item(eid, **fields)

    def _compute_assets_hash(self, raw_body, filename=None):
        parts = []
        document_dir = self.file_path(filename).parent if filename else self.docs_dir
        for m in [*IMAGE_RE.finditer(raw_body), *_LINK_RE.finditer(raw_body)]:
            src = m.group(2)
            if src.startswith(("http://", "https://", "#")) or src.split("#")[0].endswith(".md"):
                continue
            path = _resolve_asset_path(document_dir, self.project_root, src, strict=True)
            parts.append(f"{src}:{_compute_file_hash(path) if path.is_file() else 'missing'}")
        if self.target.attachments_dir:
            att_dir = self.project_root / self.target.attachments_dir
            if att_dir.is_dir():
                for f in sorted(att_dir.glob(self.target.attachments_pattern)):
                    if f.is_file() and not _is_image(f.name):
                        checked = _resolve_asset_path(self.project_root, self.project_root, str(f), strict=True)
                        parts.append(f"{f.name}:{_compute_file_hash(checked)}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def _assets_changed(self, filename, raw_body):
        state = self._state(filename)
        hp = self.hash_dir / f"{filename}.assets_hash"
        saved = state["assets_hash"] if state else hp.read_text().strip() if hp.exists() else None
        return saved is not None and saved != self._compute_assets_hash(raw_body, filename)

    def _save_assets_hash(self, filename, raw_body):
        atomic_write(self.hash_dir / f"{filename}.assets_hash", self._compute_assets_hash(raw_body, filename) + "\n")

    def _remote_signature(self, data, uploads):
        return {"body": data.get("body") or "", "title": data.get("title") or "",
                "content_type": data.get("content_type"), "category": data.get("category"), "tags": data.get("tags"),
                "uploads": sorted([{k: u.get(k) for k in ("id", "real_name", "hash", "sha256", "filesize", "long_name")}
                                   for u in uploads], key=lambda u: str(u["id"]))}

    def _save_baseline(self, filename, raw_body, data, uploads):
        self._save_hash(filename, raw_body)
        self._save_remote_hash(filename, data.get("body") or "")
        self._save_meta_hash(filename, Path(filename).stem, self.target.category, self.target.tags)
        self._save_assets_hash(filename, raw_body)
        write_json(self.hash_dir / f"{filename}.state.json", {
            "version": 1, "server": str(self.client.base_url), "entity": self.entity,
            "profile": self.target.profile, "team": self.target.team, "body_format": self.target.body_format,
            "local_hash": _compute_hash(raw_body), "assets_hash": self._compute_assets_hash(raw_body, filename),
            "meta_hash": _compute_meta_hash(Path(filename).stem, self.target.category, self.target.tags),
            "remote": self._remote_signature(data, uploads),
        })

    def inspect(self, filename, eid, data=None, uploads=None):
        """Read-only; legacy body hashes remain usable without inventing a baseline."""
        path = self.file_path(filename)
        local_exists = path.is_file()
        body = path.read_text(encoding="utf-8").strip() if local_exists else ""
        result = {"filename": filename, "entity_id": eid, "body": body, "state": "未追跡"}
        if eid is None:
            return result
        try:
            data = self._get_entity(eid) if data is None else data
            uploads = self.client.list_uploads(self.entity, eid) if uploads is None else uploads
            result.update(data=data, uploads=uploads)
            state = self._state(filename)
            if state and (state["server"] != str(self.client.base_url) or state["entity"] != self.entity
                          or state.get("profile", self.target.profile) != self.target.profile
                          or state.get("team", self.target.team) != self.target.team):
                raise ValueError("接続先が前回同期時と異なります。別の状態ディレクトリを指定してください")
            hp = self._remote_hash_path(filename)
            remote_known = bool(state or hp.exists())
            remote_changed = (state["remote"] != self._remote_signature(data, uploads)) if state else (
                hp.read_text().strip() != _compute_hash(data.get("body") or "") if hp.exists() else False)
            local_known = bool(state or self._hash_path(filename).exists())
            local_changed = (self._has_changed(filename, body) or self._assets_changed(filename, body)
                             or self._has_meta_changed(filename, path.stem, self.target.category, self.target.tags))
            result.update(local_changed=local_changed, remote_changed=remote_changed)
            if not local_exists:
                result["state"] = "ローカル削除"
            elif not local_known or not remote_known:
                result["state"] = "基準情報なし"
            elif local_changed and remote_changed:
                result["state"] = "競合"
            elif local_changed:
                result["state"] = "送信待ち"
            elif remote_changed:
                result["state"] = "取得待ち"
            else:
                result["state"] = "最新"
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            result.update(state="リモート削除" if status == 404 else "確認失敗", error=str(exc))
        return result

    def file_path(self, filename):
        safe_path(self.docs_dir, filename)
        matches = [p for p in self.docs_dir.glob(self.target.pattern) if p.name == filename and p.is_file()]
        if len(matches) > 1:
            raise ValueError(f"同名ファイルが複数あります: {filename}")
        return matches[0] if matches else self.docs_dir / filename

    def collect_files(self):
        excluded = self._load_excluded()
        files = sorted(f for f in self.docs_dir.glob(self.target.pattern) if f.is_file() and f.name not in excluded)
        if len({f.name for f in files}) != len(files):
            raise ValueError("同名ファイルが複数あります。異なるファイル名にしてください")
        for f in files:
            safe_path(self.docs_dir, f.relative_to(self.docs_dir).as_posix())
        return files

    def _load_excluded(self):
        path = self.hash_dir / "excluded.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(data, list) or not all(isinstance(n, str) and Path(n).name == n for n in data):
            raise ValueError(f"除外情報の形式が不正です: {path}")
        return set(data)

    def _receipt_path(self, filename):
        identity = f"{self.client.base_url}|{self.entity}|{self.hash_dir}|{filename}"
        key = hashlib.sha256(identity.encode()).hexdigest()
        return self.project_root / ".elab-sync-operations" / f"{key}.json"

    def _pending(self):
        path = self.hash_dir / "pending.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save_pending(self, data):
        write_json(self.hash_dir / "pending.json", data)

    def untrack(self, filenames, mapping):
        write_json(self.hash_dir / "excluded.json", sorted(self._load_excluded() | filenames))
        self._save_mapping({n: eid for n, eid in mapping.items() if n not in filenames})
        for name in filenames:
            for suffix in self.SUFFIXES:
                (self.hash_dir / f"{name}{suffix}").unlink(missing_ok=True)

    def move_tracking(self, old, new, mapping):
        if not self._meta_hash_path(old).exists() and not self._state(old):
            self._save_meta_hash(old, Path(old).stem, self.target.category, self.target.tags)
        mapping[new] = mapping.pop(old)
        for suffix in self.SUFFIXES:
            src, dest = self.hash_dir / f"{old}{suffix}", self.hash_dir / f"{new}{suffix}"
            if src.exists():
                src.replace(dest)
        self._save_mapping(mapping)

    def _detect_renames(self, mapping, md_files, entity_label):
        files = {f.name: f for f in md_files}
        missing = set(mapping) - set(files) - self._load_excluded()
        new = set(files) - set(mapping)
        if not missing or not new:
            return mapping
        pairs = []
        for old in sorted(missing):
            hp = self._hash_path(old)
            matches = [n for n in new if hp.exists() and hp.read_text().strip() == _compute_hash(files[n].read_text(encoding="utf-8").strip())]
            if len(matches) != 1 or any(n == matches[0] for _, n in pairs):
                raise ConflictError("リネームの対応が不明です。esync mv 旧パス 新パス で指定するか、不要な追跡をrmしてください")
            pairs.append((old, matches[0]))
        # No remote changes here; title updates use the normal conflict checks.
        with local_transaction(self.project_root, [self.hash_dir], "自動リネームの紐付け変更"):
            for old, new_name in pairs:
                self.move_tracking(old, new_name, mapping)
                print(f"  リネーム検出: {old} → {new_name}")
        return mapping

    def _check_remote_conflict(self, filename, eid):
        result = self.inspect(filename, eid)
        if result["state"] in ("競合", "取得待ち", "基準情報なし", "リモート削除", "確認失敗"):
            raise ConflictError(f"{filename}: {result['state']}。esync diff で確認し、pull または --force を選択してください")

    def dry_run(self):
        mapping = self._load_mapping(migrate=False)
        return [{"filename": f.name, "title": f.stem, "images": _count_local_images(body),
                 "videos": _count_local_videos(body), "file_links": _count_local_file_links(body),
                 "changed": self._has_changed(f.name, body), "entity_id": mapping.get(f.name)}
                for f in self.collect_files() for body in [f.read_text(encoding="utf-8").strip()]]

    def sync(self, force=False, prune_attachments=False):
        md_files = self.collect_files()
        self.failures = self.skipped = 0
        if not md_files:
            if self._load_excluded() and self.docs_dir.is_dir():
                return 0
            raise FileNotFoundError(f"{self.docs_dir} に {self.target.pattern} に一致するファイルがありません")
        mapping = self._load_mapping()
        pending = self._pending()
        unknown = [name for name, item in pending.items() if not item.get("eid")]
        if unknown:
            raise ConflictError(f"作成結果が不明です: {', '.join(unknown)}。esync list で確認し、linkでIDを確定してください")
        for name, item in pending.items():
            if item.get("eid") and name not in mapping:
                if item["eid"] in mapping.values():
                    raise ConflictError("未完了の作成IDが別文書に紐付いています")
                mapping[name] = item["eid"]
                self._save_mapping(mapping)
        mapping = self._detect_renames(mapping, md_files, self.entity)
        jobs = []
        # Preflight all known destinations before creating any entities.
        for f in md_files:
            self._compute_assets_hash(f.read_text(encoding="utf-8").strip(), f.name)
            eid = mapping.get(f.name)
            result = self.inspect(f.name, eid)
            state = result["state"]
            if state in ("確認失敗", "リモート削除"):
                self.failures += 1
                print(f"  [{f.stem}] {state}: {result.get('error', '')}")
                continue
            owned = pending.get(f.name, {})
            expected = owned.get("expected")
            before = owned.get("before")
            current_guard = {k: v for k, v in self._remote_signature(result.get("data", {}), result.get("uploads", [])).items() if k not in ("body", "title", "content_type")}
            resuming = bool(owned.get("eid") == eid and owned.get("guard") == current_guard and any(
                version is not None and all(result["data"].get(k) == v for k, v in version.items())
                for version in (expected, before)))
            if not force and owned and not resuming:
                self.failures += 1
                print(f"  [{f.stem}] 未完了の同期後にリモート変更があります。diffで確認してから再開してください")
                continue
            if not force and not resuming and state in ("競合", "取得待ち", "基準情報なし"):
                self.failures += 1
                print(f"  [{f.stem}] {state}。esync diff で確認してください")
                continue
            if not force and not prune_attachments and not resuming and state == "最新":
                self.skipped += 1
                print(f"  [{f.stem}] 変更なし（スキップ）")
                continue
            jobs.append((f, result, resuming))
        for f, result, resuming in jobs:
            if result["entity_id"] is None:
                receipt = self._receipt_path(f.name)
                if receipt.exists():
                    raise ConflictError(f"{f.name}: 過去の作成記録があります。listで確認後、linkまたはlink --newで解決してください")
                write_json(receipt, {"filename": f.name, "eid": None})
                pending[f.name] = {"eid": None}
                self._save_pending(pending)
                eid = self._create_entity(f.stem)
                if not isinstance(eid, int) or eid <= 0 or eid in mapping.values():
                    raise RuntimeError("新規作成IDを取得できませんでした。listとlinkで確認してください")
                write_json(receipt, {"filename": f.name, "eid": eid})
                pending[f.name] = {"eid": eid, "expected": {"body": "", "title": ""}}
                self._save_pending(pending)
                mapping[f.name] = eid
                self._save_mapping(mapping)
                result["entity_id"] = eid
                print(f"  [{f.stem}] #{eid} を新規作成しました")
        updated = 0
        for f, result, resuming in jobs:
            eid = result["entity_id"]
            raw_body = result["body"]
            try:
                if force and result.get("data") is not None:
                    snapshot(self.project_root, [], "強制push前のリモート本文", remote={
                        "server": str(self.client.base_url), "entity": self.entity, "id": eid,
                        "title": result["data"].get("title"), "body": result["data"].get("body"),
                        "content_type": result["data"].get("content_type"),
                    })
                body = _rewrite_images(raw_body, self.entity, eid, self.client, f.parent, self.project_root, strict=True)
                body = _rewrite_videos(body, self.entity, eid, self.client, f.parent, self.project_root, strict=True)
                body = _rewrite_file_links(body, self.entity, eid, self.client, f.parent, self.project_root, strict=True)
                body = _rewrite_local_links(body, self.entity, self.client.base_url, mapping)
                body = body if self.target.body_format == "md" else _md_to_html(body)
                expected = {"body": body, "title": f.stem, "content_type": 2 if self.target.body_format == "md" else 1}
                previous = result.get("data") or self._get_entity(eid)
                before = {key: previous.get(key) for key in expected}
                guard = {k: v for k, v in self._remote_signature(previous, self.client.list_uploads(self.entity, eid)).items() if k not in ("body", "title", "content_type")}
                pending[f.name] = {"eid": eid, "expected": expected, "before": before, "guard": guard}
                self._save_pending(pending)
                self._update_entity(eid, **expected)
                meta_changed = force or result.get("data") is None or resuming or self._has_meta_changed(f.name, f.stem, self.target.category, self.target.tags)
                def checkpoint(allowed_fields=()):
                    observed = self._get_entity(eid)
                    signature = self._remote_signature(observed, self.client.list_uploads(self.entity, eid))
                    observed_guard = {k: v for k, v in signature.items() if k not in ("body", "title", "content_type")}
                    if any(value != pending[f.name]["guard"].get(key) for key, value in observed_guard.items() if key not in allowed_fields):
                        raise ConflictError("同期処理中にリモートのメタデータ・添付が変更されました。diffで確認してください")
                    pending[f.name]["guard"] = observed_guard
                    self._save_pending(pending)

                checkpoint()
                tags_ok = _sync_tags(self.client, self.entity, eid, self.target.tags) if meta_changed else True
                if not tags_ok:
                    raise RuntimeError("本文更新後にタグ同期が失敗しました。リモートを確認して再実行してください")
                if meta_changed:
                    checkpoint(("tags",))
                category_ok = _sync_category(self.client, self.entity, eid, self.target.category) if meta_changed else True
                if not category_ok:
                    raise RuntimeError("本文更新後にカテゴリ同期が失敗しました。リモートを確認して再実行してください")
                if meta_changed:
                    checkpoint(("category",))
                att_ok = True
                if self.target.attachments_dir:
                    att_ok = _sync_attachments(self.project_root / self.target.attachments_dir, self.entity, eid, self.client,
                                               force=force, pattern=self.target.attachments_pattern, prune=prune_attachments, strict=True)
                if tags_ok is False or category_ok is False or not att_ok:
                    raise RuntimeError("本文更新後、メタデータまたは添付の同期が失敗しました。再実行してください")
                data = self._get_entity(eid)
                uploads = self.client.list_uploads(self.entity, eid)
                self._save_baseline(f.name, raw_body, data, uploads)
                pending.pop(f.name, None)
                self._save_pending(pending)
                sync_log.record(self.project_root / sync_log.DEFAULT_LOG_PATH, action="push", target=f.stem,
                                entity=self.entity, entity_id=eid, files=[f.name])
                updated += 1
                print(f"  [{f.stem}] #{eid} を更新しました")
            except Exception as exc:
                self.failures += 1
                print(f"  [{f.stem}] 同期失敗: {exc}")
        return updated
