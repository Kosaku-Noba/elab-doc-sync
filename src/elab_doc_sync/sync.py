"""Diff-based docs sync to eLabFTW items/experiments with image upload."""

import hashlib
import json
import re
import shutil
import tempfile
import markdown
from pathlib import Path

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


class ConflictError(Exception):
    """リモートが前回同期以降に変更されている。"""
    pass


def _compute_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _count_local_images(body: str) -> int:
    return sum(1 for m in IMAGE_RE.finditer(body) if not m.group(2).startswith(("http://", "https://")))


def _md_to_html(text: str) -> str:
    return markdown.markdown(text, extensions=MD_EXTENSIONS)


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


def _download_images(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path) -> str:
    """Markdown 内の eLabFTW 画像 URL をローカルにダウンロードし相対パスに書き換える。"""
    try:
        uploads = client.list_uploads(entity, entity_id)
    except Exception as e:
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
        dest = img_dir / local_name
        if not dest.exists():
            data = client.download_upload(
                entity_type=entity,
                entity_id=entity_id,
                upload_id=matched_upload["id"],
            )
            dest.write_bytes(data)
            print(f"    画像をダウンロード: {real_name}")
        return f"![{alt}](images/{local_name})"

    return IMAGE_RE.sub(replace_match, body)


def _normalize_remote_image_urls(body: str, entity: str, entity_id: int, client: ELabFTWClient) -> str:
    """diff 比較用: リモート MD 内の eLabFTW 画像 URL をローカル相対パスに書き換える（DL なし）。"""
    try:
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


def _rewrite_images(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path) -> str:
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
                })
        # id 昇順でソートし、最古の添付を正本として安定させる
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        pass

    tmp_dirs: list[str] = []
    stale_ids: list[int] = []

    def replace_match(m):
        alt, src = m.group(1), m.group(2)
        if src.startswith(("http://", "https://")):
            return m.group(0)
        img_path = (docs_dir / src).resolve()
        if not img_path.exists():
            img_path = (project_root / src).resolve()
        if not img_path.exists():
            print(f"    ⚠ 画像が見つかりません: {src}")
            return m.group(0)
        real_name = _parse_image_local_name(img_path.name) or img_path.name
        entries = existing.get(real_name, [])
        local_size = img_path.stat().st_size
        # NOTE: 同名・同サイズ・別内容のケースは再利用される（ハッシュ比較はコスト回避のため省略）
        reuse = next((e for e in entries if e["size"] and e["size"] == local_size), None)
        if reuse:
            # サイズ一致の1件を再利用し、残りの重複は削除予約
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
        print(f"    ✗ アップロード失敗: {real_name}")
        return m.group(0)

    try:
        result = IMAGE_RE.sub(replace_match, body)
        # アップロード成功後に古い添付を削除（失敗しても本文は壊さない）
        for uid in stale_ids:
            try:
                client.delete_upload(entity, entity_id, uid)
            except Exception:
                pass
        return result
    finally:
        for td in tmp_dirs:
            shutil.rmtree(td, ignore_errors=True)


class DocsSyncer:
    """mode: merge — 複数 md を結合して 1 エンティティに同期。"""

    def __init__(self, client: ELabFTWClient, target: TargetConfig, project_root: Path):
        self.client = client
        self.target = target
        self.entity = target.entity
        self.project_root = project_root
        self.docs_dir = project_root / target.docs_dir
        self.id_file = project_root / target.id_file
        self.hash_file = self.id_file.with_suffix(".hash")

    def collect_docs(self) -> str:
        md_files = sorted(self.docs_dir.glob(self.target.pattern))
        if not md_files:
            raise FileNotFoundError(
                f"{self.docs_dir} に {self.target.pattern} に一致するファイルがありません\n"
                "→ docs_dir とパターンの設定を確認してください"
            )
        sections = [f.read_text(encoding="utf-8").strip() for f in md_files]
        body = "\n\n---\n\n".join(sections)
        print(f"  [{self.target.title}] {len(md_files)} 件のドキュメントを収集しました（{len(body)} 文字）")
        return body

    def collect_files(self) -> list[Path]:
        return sorted(self.docs_dir.glob(self.target.pattern))

    def has_changed(self, body: str) -> bool:
        new_hash = _compute_hash(body)
        if self.hash_file.exists():
            return self.hash_file.read_text().strip() != new_hash
        return True

    def save_hash(self, body: str) -> None:
        self.hash_file.parent.mkdir(parents=True, exist_ok=True)
        self.hash_file.write_text(_compute_hash(body) + "\n")

    @property
    def remote_hash_file(self) -> Path:
        return self.id_file.with_suffix(".remote_hash")

    def save_remote_hash(self, remote_body: str) -> None:
        self.remote_hash_file.parent.mkdir(parents=True, exist_ok=True)
        self.remote_hash_file.write_text(_compute_hash(remote_body) + "\n")

    def read_item_id(self) -> int | None:
        if self.id_file.exists():
            text = self.id_file.read_text().strip()
            if text.isdigit():
                return int(text)
        return None

    def save_item_id(self, item_id: int) -> None:
        self.id_file.parent.mkdir(parents=True, exist_ok=True)
        self.id_file.write_text(str(item_id) + "\n")

    def _get_entity(self, eid: int) -> dict:
        if self.entity == "experiments":
            return self.client.get_experiment(eid)
        return self.client.get_item(eid)

    def _create_entity(self, title: str) -> int:
        if self.entity == "experiments":
            return self.client.create_experiment(title=title)
        return self.client.create_item(title=title)

    def _update_entity(self, eid: int, **fields) -> None:
        if self.entity == "experiments":
            self.client.update_experiment(eid, **fields)
        else:
            self.client.update_item(eid, **fields)

    def dry_run(self) -> dict:
        md_files = self.collect_files()
        if not md_files:
            return {"files": 0, "images": 0, "changed": False, "item_id": self.read_item_id()}
        sections = [f.read_text(encoding="utf-8").strip() for f in md_files]
        body = "\n\n---\n\n".join(sections)
        return {
            "files": len(md_files),
            "images": _count_local_images(body),
            "changed": self.has_changed(body),
            "item_id": self.read_item_id(),
        }

    def _check_remote_conflict(self, item_id: int) -> None:
        """前回同期時のリモートハッシュと現在のリモート body を比較。"""
        if not self.remote_hash_file.exists():
            return
        saved_hash = self.remote_hash_file.read_text().strip()
        remote_data = self._get_entity(item_id)
        remote_body = remote_data.get("body", "") or ""
        remote_hash = _compute_hash(remote_body)
        if saved_hash != remote_hash:
            raise ConflictError(
                f"リモートが前回同期以降に変更されています（{self.entity} #{item_id}）\n"
                "→ esync pull で先にリモート変更を取り込むか、--force で強制上書きしてください"
            )

    def sync(self, force: bool = False) -> bool:
        raw_body = self.collect_docs()

        if not force and not self.has_changed(raw_body):
            print(f"  [{self.target.title}] 変更なし（スキップ）")
            return False

        item_id = self.read_item_id()
        entity_label = "実験ノート" if self.entity == "experiments" else "リソース"

        if item_id is not None:
            try:
                self._get_entity(item_id)
            except Exception:
                print(f"  [{self.target.title}] {entity_label} #{item_id} が見つかりません。新規作成します")
                item_id = None

        if item_id is not None and not force:
            self._check_remote_conflict(item_id)

        if item_id is None:
            item_id = self._create_entity(title=self.target.title)
            self.save_item_id(item_id)
            print(f"  [{self.target.title}] {entity_label} #{item_id} を新規作成しました")

        body = _rewrite_images(raw_body, self.entity, item_id, self.client, self.docs_dir, self.project_root)
        if self.target.body_format == "md":
            self._update_entity(item_id, body=body, title=self.target.title)
        else:
            html = _md_to_html(body)
            self._update_entity(item_id, body=html, title=self.target.title)
        self.save_hash(raw_body)

        # push 後のリモート body ハッシュを保存（競合検出用）
        try:
            remote_data = self._get_entity(item_id)
            self.save_remote_hash(remote_data.get("body", "") or "")
        except Exception as e:
            print(f"  [{self.target.title}] ⚠ リモートハッシュの保存に失敗（次回の競合検出が不正確になる可能性があります）: {e}")

        print(f"  [{self.target.title}] {entity_label} #{item_id} を更新しました")

        _sync_tags(self.client, self.entity, item_id, self.target.tags)

        log_path = self.project_root / sync_log.DEFAULT_LOG_PATH
        files = [f.name for f in self.collect_files()]
        sync_log.record(log_path, action="push", target=self.target.title,
                        entity=self.entity, entity_id=item_id, files=files)

        return True


def _sync_tags(client: ELabFTWClient, entity_type: str, entity_id: int, desired_tags: list[str]) -> None:
    """設定のタグをリモートに追記する（既存タグは外さない）。best-effort。"""
    if not desired_tags:
        return
    try:
        remote = client.get_tags(entity_type, entity_id)
        remote_names = {t.get("tag") for t in remote}
        for tag in desired_tags:
            if tag not in remote_names:
                client.add_tag(entity_type, entity_id, tag)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("タグ同期失敗", exc_info=True)
        print(f"    ⚠ タグ同期に失敗しました（本文の同期は成功しています）")


class EachDocsSyncer:
    """mode: each — 1 ファイル = 1 エンティティとして個別に同期。"""

    def __init__(self, client: ELabFTWClient, target: TargetConfig, project_root: Path):
        self.client = client
        self.target = target
        self.entity = target.entity
        self.project_root = project_root
        self.docs_dir = project_root / target.docs_dir
        self.mapping_file = (project_root / target.id_file).parent / "mapping.json"
        self.hash_dir = (project_root / target.id_file).parent

    def _load_mapping(self) -> dict:
        if self.mapping_file.exists():
            return json.loads(self.mapping_file.read_text(encoding="utf-8"))
        return {}

    def _save_mapping(self, mapping: dict) -> None:
        self.mapping_file.parent.mkdir(parents=True, exist_ok=True)
        self.mapping_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _hash_path(self, filename: str) -> Path:
        return self.hash_dir / f"{filename}.hash"

    def _has_changed(self, filename: str, body: str) -> bool:
        hp = self._hash_path(filename)
        new_hash = _compute_hash(body)
        if hp.exists():
            return hp.read_text().strip() != new_hash
        return True

    def _save_hash(self, filename: str, body: str) -> None:
        hp = self._hash_path(filename)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(_compute_hash(body) + "\n")

    def _remote_hash_path(self, filename: str) -> Path:
        return self.hash_dir / f"{filename}.remote_hash"

    def _save_remote_hash(self, filename: str, remote_body: str) -> None:
        hp = self._remote_hash_path(filename)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(_compute_hash(remote_body) + "\n")

    def _get_entity(self, eid: int) -> dict:
        if self.entity == "experiments":
            return self.client.get_experiment(eid)
        return self.client.get_item(eid)

    def _create_entity(self, title: str) -> int:
        if self.entity == "experiments":
            return self.client.create_experiment(title=title)
        return self.client.create_item(title=title)

    def _update_entity(self, eid: int, **fields) -> None:
        if self.entity == "experiments":
            self.client.update_experiment(eid, **fields)
        else:
            self.client.update_item(eid, **fields)

    def _check_remote_conflict(self, filename: str, eid: int) -> None:
        """前回同期時のリモートハッシュと現在のリモート body を比較。"""
        hp = self._remote_hash_path(filename)
        if not hp.exists():
            return
        saved_hash = hp.read_text().strip()
        remote_data = self._get_entity(eid)
        remote_body = remote_data.get("body", "") or ""
        remote_hash = _compute_hash(remote_body)
        if saved_hash != remote_hash:
            raise ConflictError(
                f"リモートが前回同期以降に変更されています（{self.entity} #{eid}: {filename}）\n"
                "→ esync pull で先にリモート変更を取り込むか、--force で強制上書きしてください"
            )

    def collect_files(self) -> list[Path]:
        return sorted(self.docs_dir.glob(self.target.pattern))

    def dry_run(self) -> list[dict]:
        md_files = self.collect_files()
        mapping = self._load_mapping()
        results = []
        for f in md_files:
            body = f.read_text(encoding="utf-8").strip()
            title = f.stem
            results.append({
                "filename": f.name,
                "title": title,
                "images": _count_local_images(body),
                "changed": self._has_changed(f.name, body),
                "entity_id": mapping.get(f.name),
            })
        return results

    def sync(self, force: bool = False) -> int:
        """各ファイルを個別に同期。更新した件数を返す。"""
        md_files = self.collect_files()
        if not md_files:
            raise FileNotFoundError(
                f"{self.docs_dir} に {self.target.pattern} に一致するファイルがありません\n"
                "→ docs_dir とパターンの設定を確認してください"
            )

        mapping = self._load_mapping()
        entity_label = "実験ノート" if self.entity == "experiments" else "リソース"
        updated = 0

        for f in md_files:
            title = f.stem
            raw_body = f.read_text(encoding="utf-8").strip()

            if not force and not self._has_changed(f.name, raw_body):
                print(f"  [{title}] 変更なし（スキップ）")
                continue

            eid = mapping.get(f.name)

            if eid is not None:
                try:
                    self._get_entity(eid)
                except Exception:
                    print(f"  [{title}] {entity_label} #{eid} が見つかりません。新規作成します")
                    eid = None

            if eid is not None and not force:
                self._check_remote_conflict(f.name, eid)

            if eid is None:
                eid = self._create_entity(title=title)
                mapping[f.name] = eid
                self._save_mapping(mapping)
                print(f"  [{title}] {entity_label} #{eid} を新規作成しました")

            body = _rewrite_images(raw_body, self.entity, eid, self.client, self.docs_dir, self.project_root)
            if self.target.body_format == "md":
                self._update_entity(eid, body=body, title=title)
            else:
                html = _md_to_html(body)
                self._update_entity(eid, body=html, title=title)
            self._save_hash(f.name, raw_body)

            # push 後のリモート body ハッシュを保存（競合検出用）
            try:
                remote_data = self._get_entity(eid)
                self._save_remote_hash(f.name, remote_data.get("body", "") or "")
            except Exception as e:
                print(f"  [{title}] ⚠ リモートハッシュの保存に失敗: {e}")

            print(f"  [{title}] {entity_label} #{eid} を更新しました")

            _sync_tags(self.client, self.entity, eid, self.target.tags)

            log_path = self.project_root / sync_log.DEFAULT_LOG_PATH
            sync_log.record(log_path, action="push", target=title,
                            entity=self.entity, entity_id=eid, files=[f.name])

            updated += 1

        return updated
