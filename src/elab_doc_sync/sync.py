"""Diff-based docs-to-eLabFTW sync with image upload and attachment support.

CLI tool — not intended for use as a library.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from functools import lru_cache
from fnmatch import fnmatch
import hashlib
import ipaddress
import posixpath
import idna
import json
import os as _os
import re
import shlex
import shutil
import tempfile
import uuid
import markdown
from markdownify import markdownify as html_to_md
import html as _html
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from html.parser import HTMLParser
from collections import Counter

from .result import progress, error_text
from .safety import hold_document, DISPLACED_PREFIX, atomic_write, write_json, safe_path, snapshot, local_transaction
from .client import ELabFTWClient, UploadConfirmationError, public_url, server_id, upload_sha256, upload_url
from .config import TargetConfig
from . import sync_log
from .merge import has_conflict_markers

# eLabFTW の画像 URL から upload_id を抽出する正規表現。
# /uploads/{数字} の後に区切り文字（? # / 行末）が続くパターンにマッチ。
# pull で画像を取得する際は、接続先・記事・添付の一覧を _article_upload で照合する。
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


def _tag_names(value):
    if isinstance(value, str):
        value = value.split("|")
    return sorted({str(t.get("tag")) if isinstance(t, dict) else str(t) for t in (value or [])
                   if (t.get("tag") if isinstance(t, dict) else t)})


def _category_value(value):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return str(value)


def _normalize_metadata_signature(signature):
    """Normalize older saved signatures in memory without changing their evidence."""
    return {**signature, "category": _category_value(signature.get("category")),
            "tags": _tag_names(signature.get("tags"))}


def _compute_meta_hash(title: str, category, tags: list[str]) -> str:
    """タイトル・カテゴリ・タグからメタデータハッシュを計算する。"""
    data = json.dumps({"title": title, "category": category, "tags": sorted(tags or [])},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _count_local_images(body: str) -> int:
    return sum(1 for link in _body_links(body) if link.image and not link.url.startswith(("http://", "https://", "//")))


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


class _AttachmentLinks(HTMLParser):
    """実際にリンクとして保存された添付 URL の出現数。"""

    def __init__(self, with_tags=False):
        super().__init__()
        self.with_tags = with_tags
        self.urls = Counter()

    def handle_starttag(self, tag, attrs):
        key = {"a": "href", "img": "src", "video": "src", "source": "src"}.get(tag)
        if key:
            url = dict(attrs).get(key)
            self.urls[(tag, url) if self.with_tags else url] += 1


def _attachment_links(body, content_type, *, with_tags=False):
    parser = _AttachmentLinks(with_tags)
    parser.feed(_md_to_html(body) if str(content_type) == "2" else body)
    parser.close()
    return parser.urls


class _MarkdownLinkPositions(HTMLParser):
    """Read labeled source positions from the links produced by Python-Markdown."""

    def __init__(self, prefix, destinations):
        super().__init__()
        self.marker = re.compile(re.escape(prefix) + r"(\d+)-end")
        self.destinations = destinations
        self.pairs = {}
        self.titles = {}
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ("a", "img"):
            return
        url = attrs.get("href" if tag == "a" else "src") or ""
        target = self.marker.match(url)
        if target and (tag, self.marker.sub("", url)) == self.destinations.get(int(target[1])):
            end = int(target[1])
            self.titles[end] = self.marker.sub("", attrs.get("title") or "")
            if tag == "a":
                self.anchor = end
            else:
                self._label(attrs.get("alt", ""), end, tag)

    def _label(self, label, end, tag):
        start = self.marker.match(label)
        if start:
            self.pairs[int(start[1])] = (end, tag, self.destinations[end][1])

    def handle_data(self, data):
        if self.anchor is not None:
            self._label(data, self.anchor, "a")
            self.anchor = None

    def handle_endtag(self, tag):
        if tag == "a":
            self.anchor = None


@dataclass(frozen=True)
class _BodyLink:
    start: int
    end: int
    label: str
    url: str
    original: str
    image: bool
    target_start: int
    target_end: int

    def with_url(self, url, *, as_file=False):
        prefix = self.original[:self.target_start]
        if as_file and self.image:
            prefix = prefix[1:]
        return prefix + url + self.original[self.target_end:]


_MD_ESCAPE = re.compile(r"""\\([!"#$%&'()*+,./:;<=>?@\[\\\]^_`{|}~-])""")
_HTML_ENTITY = re.compile(r"&(?:#\d+|#x[\da-fA-F]+|[a-zA-Z][a-zA-Z0-9]+);")
_DEST_START = re.compile(r"[ \t]*(?:\n[ \t]*)?(<)?")


def _destination_span(body, closing, url, title):
    """Match the known rendered target to source characters before changing any text."""
    opening = _DEST_START.match(body, closing + 2)
    start = pos = opening.end()
    offset = 0
    while offset < len(url) and pos < len(body):
        token = _MD_ESCAPE.match(body, pos) or _HTML_ENTITY.match(body, pos)
        if token:
            value = token[1] if token.re is _MD_ESCAPE else _html.unescape(token[0])
            if url.startswith(value, offset):
                offset += len(value)
                pos = token.end()
                continue
        if body[pos] != url[offset]:
            return None
        offset += 1
        pos += 1
    if offset != len(url):
        return None
    target_end = pos
    if opening[1]:
        if body[pos:pos+1] != ">":
            return None
        pos += 1
    space = re.compile(r"[ \t]*(?:\n[ \t]*)?")
    pos = space.match(body, pos).end()
    if body[pos:pos+1] == ")" and not title:
        return start, target_end, pos + 1
    quote = body[pos:pos+1]
    if quote not in ("'", '"'):
        return None
    title_start = pos + 1
    while (pos := body.find(quote, pos + 1)) >= 0:
        raw = body[title_start:pos]
        if re.search(r"\n[ \t]*\n", raw):
            break
        end = space.match(body, pos+1).end()
        value = _html.unescape(_MD_ESCAPE.sub(r"\1", raw))
        if body[end:end+1] == ")" and re.sub(r"\s", " ", value.strip()) == title.strip():
            return start, target_end, end + 1
    return None


@lru_cache(maxsize=8)
def _body_links(body):
    """Locate rendered inline links and keep each renderer-confirmed URL with its source span."""
    if "](" not in body:
        return ()
    prefix = "elabsync" + uuid.uuid4().hex + "-"
    token = re.compile(re.escape(prefix) + r"(\d+)-end")

    def mark(match):
        return match.group() + f"{prefix}{match.start()}-end"

    # Preserve reference names when checking which destinations the original Markdown uses.
    urls = _attachment_links(body, 2, with_tags=True)
    destinations = {}
    for tag, url in _attachment_links(re.sub(r"\]\([ \t]*<?", mark, body), 2, with_tags=True):
        if isinstance(url, str) and (marker := token.match(url)):
            key = (tag, token.sub("", url))
            if key in urls:
                destinations[int(marker[1])] = key
    parser = _MarkdownLinkPositions(prefix, destinations)
    parser.feed(_md_to_html(re.sub(r"\[|\]\([ \t]*<?", mark, body)))
    parser.close()

    links = []
    for opening, (closing, tag, url) in sorted(parser.pairs.items()):
        if not url:
            continue
        span = _destination_span(body, closing, url, parser.titles[closing])
        if span is None:
            if not url.startswith(("http://", "https://", "//", "#", "mailto:", "data:")):
                raise ConflictError("本文のローカルリンクの範囲を確認できません。リンク記法を確認してください")
            continue
        target_start, target_end, end = span
        image = tag == "img"
        start = opening - 1 if image else opening
        links.append(_BodyLink(start, end, body[opening+1:closing], url, body[start:end],
                               image, target_start-start, target_end-start))
    return tuple(links)


def _replace_body_links(body, replace, *, images):
    parts = []
    cursor = 0
    for link in _body_links(body):
        if (images is None or link.image == images) and link.start >= cursor:
            replacement = replace(link)
            if replacement != link.original:
                parts.extend((body[cursor:link.start], replacement))
                cursor = link.end
    return "".join(parts) + body[cursor:]


def _article_upload(src, by_name, by_id, base_url, entity, eid):
    """Resolve actual download endpoints on this installation and article."""
    try:
        base = str(base_url).rstrip("/") + "/"
        absolute = urljoin(base, src)
        if _url_origin(absolute, "https") != _url_origin(base, "https"):
            return None
        parsed = urlsplit(absolute)
        prefix = urlsplit(base).path
        if not parsed.path.startswith(prefix):
            return None
        path = parsed.path[len(prefix):]
    except (ValueError, UnicodeError):
        return None
    if path == "app/download.php":
        return by_name.get(parse_qs(parsed.query).get("f", [None])[0])
    match = re.fullmatch(r"(?:api/v2/" + re.escape(f"{entity}/{eid}") + r"/)?uploads/(\d+)/?", path)
    return by_id.get(match[1]) if match else None


def _linked_article_upload_ids(uploads, body, content_type, base_url, entity, eid):
    by_name = {u["long_name"]: u for u in uploads if u.get("long_name")}
    by_id = {str(u["id"]): u for u in uploads if u.get("id") is not None}
    return {matched["id"] for src in _attachment_links(body or "", content_type) if src
            if (matched := _article_upload(src, by_name, by_id, base_url, entity, eid))}


def _download_images(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, strict: bool = False,
                     keep_existing: bool = False, uploads=None, check_path=None, preview=False, exclusive_paths=(), digests=None,
                     expected_files=None, backup=None, keep_paths=()) -> str:
    """Markdown 内の eLabFTW 画像 URL をローカルにダウンロードし相対パスに書き換える。

    preview=True は保存予定パスの検査のみ行い、画像の取得・ディレクトリの作成をしない。
    pull は keep_paths の各画像を保持し、置換する画像は expected_files のハッシュを照合する。
    keep_existing=True は既存の呼び出し用で、既存の画像をすべて保持する。
    """
    try:
        if uploads is None:
            uploads = client.list_uploads(entity, entity_id)
    except Exception as e:
        if strict:
            raise
        progress(f"    ⚠ 添付ファイル一覧の取得に失敗（{entity} #{entity_id}、画像のローカル化をスキップ）: {_error_text(client, e)}", warning=True)
        return body
    saved = set()
    upload_map = {}
    id_map = {}
    for u in uploads:
        ln = u.get("long_name")
        if ln:
            upload_map[ln] = u
        uid = u.get("id")
        if uid is not None:
            id_map[str(uid)] = u

    def replace_match(link):
        alt, src = link.label, link.url
        if "app/download.php" not in src and "/uploads/" not in src:
            return link.original
        matched_upload = _article_upload(src, upload_map, id_map, client.base_url, entity, entity_id)
        if not matched_upload:
            # list_uploads にない画像: 絶対 URL に変換して保持
            if not src.startswith(("http://", "https://", "//")) and ("app/download.php" in src or "/uploads/" in src):
                # 本文に残る URL なので、接続先の認証情報は含めない。
                abs_url = urljoin(public_url(client.base_url).rstrip("/") + "/", src)
                if not preview:
                    progress(f"    画像を絶対 URL に変換: {Path(src).name[:40]}")
                return link.with_url(abs_url)
            return link.original
        real_name = matched_upload.get("real_name", f"upload_{matched_upload['id']}")
        local_name = _image_local_name(entity, entity_id, real_name)
        img_dir = docs_dir / "images"
        dest = safe_path(docs_dir, f"images/{local_name}")
        reference = link.with_url(f"images/{local_name}")
        image = (dest, matched_upload["id"])
        if image in saved:
            return reference
        if check_path:
            check_path(dest, asset=True, upload_id=matched_upload["id"], upload=matched_upload)
        if preview:
            return link.original
        img_dir.mkdir(parents=True, exist_ok=True)
        if dest in keep_paths:
            if digests is not None:
                digests[dest] = expected_files[dest]
        elif not dest.exists() or (strict and not keep_existing):
            data = client.download_upload(
                entity_type=entity,
                entity_id=entity_id,
                upload_id=matched_upload["id"],
            )
            if digests is not None:
                digests[dest] = hashlib.sha256(data).hexdigest()
            if expected_files is None:
                atomic_write(dest, data, exclusive=dest in exclusive_paths)
            else:
                _publish_download(dest, data, backup, expected_files[dest], 0o600)
            progress(f"    画像をダウンロード: {real_name}")
        saved.add(image)
        return reference

    return _replace_body_links(body, replace_match, images=True)


# html_to_md 共通オプション: エスケープを抑制してラウンドトリップを安定させる
# 適用先: pull, diff, clone, new、マージの基準本文（HTML→Markdown 変換の全経路）
# 方針: 本ツール経由の push→pull ラウンドトリップの安定性を優先する。
# Web UI 等で直接作成された HTML 内のリテラルな * や _ は、pull 後に
# Markdown の強調記法として解釈される可能性がある（許容する仕様）。
_MD_OPTS = {"heading_style": "ATX", "escape_asterisks": False, "escape_underscores": False}


def _is_markdown_body(content_type, target):
    # API content_type: 1=HTML, 2=Markdown. Legacy responses use target configuration.
    return str(content_type) == "2" or (content_type is None and target.body_format == "md")


def _remote_markdown(data, target):
    body = data.get("body") or ""
    is_md = _is_markdown_body(data.get("content_type"), target)
    # eLabFTW stores Markdown bodies HTML-escaped ("> " -> "&gt; ", "&&" -> "&amp;&amp;").
    return _html.unescape(body).strip() if is_md else html_to_md(body, **_MD_OPTS).strip()


_ANGLE_RE = re.compile(r"<[^<>\n]*>")


def _dropped_angle_fragments(sent: str, stored: str) -> list[str]:
    """Return <...> fragments in the sent Markdown that eLabFTW removed on save.

    eLabFTW treats e.g. "<string>" in "array<string>" as an HTML tag and drops it.
    That text cannot be recovered by pull, so push must report it.
    """
    from collections import Counter
    kept = Counter(_ANGLE_RE.findall(_html.unescape(stored or "")))
    lost = Counter(_ANGLE_RE.findall(sent)) - kept
    return list(lost)


def _normalize_remote_image_urls(body: str, entity: str, entity_id: int, client: ELabFTWClient, uploads=None) -> str:
    """diff 比較用: リモート MD 内の eLabFTW 画像 URL をローカル相対パスに書き換える（DL なし）。"""
    try:
        if uploads is None:
            uploads = client.list_uploads(entity, entity_id)
    except Exception as e:
        progress(f"    ⚠ 添付ファイル一覧の取得に失敗（{entity} #{entity_id}、画像 URL の正規化をスキップ）: {_error_text(client, e)}", warning=True)
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

    def replace_match(link):
        alt, src = link.label, link.url
        if "app/download.php" not in src and "/uploads/" not in src:
            return link.original
        matched = _article_upload(src, upload_map, id_map, client.base_url, entity, entity_id)
        if matched:
            real_name = matched.get("real_name", f"upload_{matched['id']}")
            return link.with_url(f"images/{_image_local_name(entity, entity_id, real_name)}")
        return link.original

    return _replace_body_links(body, replace_match, images=True)


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
        if candidate.exists() or index == len(candidates) - 1 or ".." in Path(source).parts:
            return candidate.resolve()
    raise FileNotFoundError(source)


@contextmanager
def _staged_asset(root, source, name=None):
    """検証したファイルを専用一時ディレクトリにコピーし、同じ内容を照合・送信する。"""
    source = Path(source)
    checked = _resolve_asset_path(root, root, str(source), strict=True)
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory) / (name or source.name)
        with source.open("rb") as reader:
            current = _resolve_asset_path(root, root, str(source), strict=True)
            if current != checked or not _os.path.samestat(_os.fstat(reader.fileno()), current.stat()):
                raise ConflictError(f"読込中に添付の保存先が変わりました: {source}")
            with staged.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
        yield staged


def _remember_asset(verified, src, digest):
    if verified is not None and verified.setdefault(src, digest) != digest:
        raise ConflictError(f"送信中に同じ添付の内容が変わりました: {src}")


def _upload_body_file(client, entity, eid, path, uploaded, root, name=None, record=None, expected_hash=None):
    """送信に使ったファイルと受領 ID を本文の更新前に記録する。"""
    with _staged_asset(root, path, name) as staged:
        expected = (staged.name, staged.stat().st_size, _compute_file_hash(staged))
        if expected_hash is not None and expected[2] != expected_hash:
            raise ConflictError(f"差分確認後に添付の内容が変わりました: {path.name}")
        try:
            result = client.upload_file(entity, eid, str(staged))
        except UploadConfirmationError as exc:
            if exc.receipt and record:
                record({**exc.receipt, "created": True})
            raise
        receipt = result.get("receipt")
        if receipt is None and result.get("id") is not None:
            receipt = dict(id=result["id"], name=expected[0], size=expected[1], sha256=expected[2])
        if receipt and record:
            record({**receipt, "created": result.get("created") is True})
            if not result.get("url"):
                raise ConflictError(f"受領した添付 ID #{receipt['id']} が一覧に現れていません。一覧への反映後に同じ文書を push してください")
    if uploaded is not None and result.get("url"):
        receipt = result.get("receipt")
        if receipt:
            expected = (receipt["name"], receipt["size"], receipt["sha256"])
        uid = result.get("id")
        if uid is None:
            raise ConflictError("送信した本文用添付の ID を特定できません")
        if uid in uploaded and uploaded[uid] != expected:
            raise ConflictError("同じ添付 ID に異なる内容が返されました")
        uploaded[uid] = expected
    return result


def _matching_upload(entries, name, size, digest, client, entity, eid, strict, preferred):
    # 名前と SHA-256 が受領記録に一致する場合は、その記録にある ID のみ照合する。
    expected = {uid for uid, r in preferred.items() if r["name"] == name and r["sha256"] == digest} if isinstance(preferred, dict) else set()
    for entry in sorted(entries, key=lambda e: e["id"] not in preferred):
        if expected and entry["id"] not in expected:
            continue
        if entry["size"] != size or (not strict and not size):
            continue
        remote_hash = entry.get("hash")
        if strict and not remote_hash:
            if entry["id"] is None:
                continue
            remote_hash = client.upload_digest(entity_type=entity, entity_id=eid, upload_id=entry["id"])
        if not remote_hash or remote_hash == digest:
            return entry
    if expected:
        raise ConflictError(f"受領した添付 ID {sorted(expected)} の URL・内容を確認できません。一覧を確認して通常の push を再実行してください")
    return None


def _cache_uploaded(existing: dict[str, list[dict]], real_name: str, url: str,
                    size: int, upload_id, file_hash: str | None = None) -> None:
    """アップロード成功結果を Upload_Cache に登録し、以降の同一 real_name 参照で再利用させる。

    同一実行内で同じ real_name を複数回参照しても再アップロードせず、ここで登録した
    URL を再利用できるようにする。``fresh=True`` は本実行で新規アップロードした分を示し、
    stale 削除対象から除外するためのマーカーとなる。``file_hash`` は照合済みの送信内容を表す。
    """
    existing.setdefault(real_name, []).append(
        {"url": url, "size": size, "id": upload_id, "hash": file_hash, "fresh": True}
    )


def _rewrite_images(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path, strict: bool = False, stale_out: list | None = None, uploaded=None, verified=None, record=None, preferred=(), used_urls=None) -> str:
    """Markdown 内のローカル画像を eLabFTW にアップロードし URL に書き換える。

    upload_file はファイルパスの basename を real_name としてリモートに保存する。
    プレフィックス付きローカル名（例: items_1_photo.png）は real_name（photo.png）に
    戻してからアップロードし、次回 pull 時の命名安定性を保つ。
    """
    existing: dict[str, list[dict]] = {}
    try:
        for u in client.list_uploads(entity, entity_id):
            rn = u.get("real_name")
            url = upload_url(client.base_url, u)
            if url:
                existing.setdefault(rn, []).append({
                    "url": url,
                    "size": int(u.get("filesize", 0) or 0),
                    "id": u.get("id"),
                    "hash": upload_sha256(u) if strict else u.get("hash") or u.get("sha256"),
                })
        # 照合済み ID の優先度が同じ候補間は ID 昇順で選ぶ
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        if strict:
            raise

    stale_ids: list[int] = []

    def replace_match(link):
        alt, src = link.label, link.url
        if src.startswith(("http://", "https://", "//")):
            return link.original
        # 動画ファイルは _rewrite_videos で処理するためスキップ
        if _is_video(src):
            return link.original
        img_path = _resolve_asset_path(docs_dir, project_root, src, strict)
        if not img_path.exists():
            if strict:
                raise FileNotFoundError(f"画像が見つかりません: {src}")
            progress(f"    ⚠ 画像が見つかりません: {src}", warning=True)
            return link.original
        real_name = _parse_image_local_name(img_path.name) or img_path.name
        entries = existing.get(real_name, [])
        local_size = img_path.stat().st_size
        local_hash = _compute_file_hash(img_path)
        reuse = _matching_upload(entries, real_name, local_size, local_hash, client, entity, entity_id, strict, preferred)
        if reuse:
            if used_urls is not None:
                used_urls[reuse["id"]] = reuse["url"]
                if record:
                    record(dict(id=reuse["id"], name=real_name, size=local_size, sha256=local_hash))
            _remember_asset(verified, src, local_hash)
            # サイズ（+ハッシュ）一致の1件を再利用し、残りの重複は削除予約
            for e in entries:
                if e is not reuse and e.get("id") is not None:
                    stale_ids.append(e["id"])
            progress(f"    ✓ {real_name}（既存アップロードを再利用）")
            return link.with_url(reuse["url"])
        # サイズ不一致 → 新規アップロードを試み、成功時のみ旧添付を削除予約
        progress(f"    画像をアップロード中: {real_name}")
        result = _upload_body_file(client, entity, entity_id, img_path, uploaded, project_root, real_name, record,
                                   expected_hash=(verified or {}).get(src))
        if result.get("url"):
            if used_urls is not None:
                used_urls[result["id"]] = result["url"]
            if verified is not None:
                _remember_asset(verified, src, uploaded[result["id"]][2])
            for e in entries:
                if e is not reuse and e.get("id") is not None and not e.get("fresh"):
                    stale_ids.append(e["id"])
            if uploaded is not None:
                _, local_size, local_hash = uploaded[result["id"]]
            _cache_uploaded(existing, real_name, result["url"], local_size, result.get("id"), local_hash)
            progress(f"    ✓ {real_name}")
            return link.with_url(result["url"])
        if strict:
            raise RuntimeError(f"アップロード失敗: {real_name}")
        progress(f"    ✗ アップロード失敗: {real_name}", warning=True)
        return link.original

    result = _replace_body_links(body, replace_match, images=True)
    # アップロード成功後に古い添付を削除（失敗しても本文は壊さない）
    # strict では削除せず、呼び出し元が同期成功後に削除できるよう返す
    if strict and stale_out is not None:
        stale_out.extend(stale_ids)
    for uid in ([] if strict else stale_ids):
        try:
            client.delete_upload(entity, entity_id, uid)
        except Exception:
            pass
    return result



# ── ローカルファイルリンク ↔ eLabFTW URL 変換 ───────────────

# Markdown リンク（画像以外）: [text](path)

# eLabFTW の記事 URL パターン:
#   items → {base_url}/database.php?mode=view&id={id}
#   experiments → {base_url}/experiments.php?mode=view&id={id}
# フラグメント部分もキャプチャして逆変換時に保持する
_ELAB_URL_RE = re.compile(
    # base はサブパスに設置した eLabFTW（https://host/elab）も含む。
    # リンク先全体がこの形のときだけ一致する。id の後に別のクエリや %xx などが続くリンクは、
    # ローカルリンクで表せない（別の記事を指すこともある）ので対象にしない（元の URL を残す）。
    r"(?P<base>https?://[^/?#\s]+(?:/[^?#\s]*?)?)/(?P<page>database|experiments)\.php\?mode=view&id=(?P<id>\d+)"
    r"(?P<fragment>#\S*)?\Z")

# eLabFTW の entity タイプと URL ページ名の対応
_ENTITY_TO_PAGE = {"items": "database", "experiments": "experiments"}
_PAGE_TO_ENTITY = {"database": "items", "experiments": "experiments"}

def _hosts_match(base_url: str, link_base: str) -> bool:
    """base_url と link_base のホスト・ポートと設置パスが一致するか判定する（認証情報は比べない）。

    前方一致ではなくホスト完全一致を使い、
    elab.example.com と elab.example.co の誤マッチを防ぐ。
    """
    from urllib.parse import urlparse

    # 接続先の認証情報は比較に含めない（本文のリンクには通常付いていない）。同じホストの別のパスに
    # 設置された eLabFTW は別のサーバーなので、ベースパスまで比べる。
    def key(url):
        parsed = urlparse(public_url(url))
        return parsed.netloc.lower(), parsed.path.rstrip("/")
    return key(base_url) == key(link_base)


class LinkTargets:
    """同じ eLabFTW 上で追跡中の文書（全ターゲット）と、そのローカルパスの対応。

    文書間リンクを、ターゲット（docs_dir）やサブディレクトリをまたいでも
    パスで解決するために使う。ファイル名だけでは別ディレクトリの同名文書と区別できない。
    """

    def __init__(self, base_url: str):
        self.base_url = public_url(base_url)
        self._by_path: dict[Path, tuple[str, int]] = {}
        self._by_id: dict[tuple[str, int], Path] = {}

    def add(self, entity: str, eid: int, path: Path) -> None:
        path = Path(path).resolve()
        self._by_path[path] = (entity, eid)
        self._by_id[(entity, eid)] = path

    def url_for(self, path: Path) -> str | None:
        found = self._by_path.get(Path(path).resolve())
        if found is None:
            return None
        entity, eid = found
        return f"{self.base_url}/{_ENTITY_TO_PAGE[entity]}.php?mode=view&id={eid}"

    def path_for(self, entity: str, eid: int) -> Path | None:
        return self._by_id.get((entity, eid))

    def url_for_name(self, filename: str, entity: str) -> str | None:
        """パスで一致しないリンクを、ファイル名で解決する（同じ entity を優先、一意な場合のみ）。"""
        for same_entity in (True, False):
            found = {key for path, key in self._by_path.items()
                     if path.name == filename and (key[0] == entity) == same_entity}
            if len(found) == 1:
                found_entity, eid = found.pop()
                return f"{self.base_url}/{_ENTITY_TO_PAGE[found_entity]}.php?mode=view&id={eid}"
            if found:
                return None
        return None


def _relative_link(path: Path, start: Path) -> str:
    rel = _os.path.relpath(path, start).replace(_os.sep, "/")
    return rel if rel.startswith("../") else f"./{rel}"


def _rewrite_local_links(body: str, entity: str, base_url: str,
                         mapping: dict, all_mappings: list[tuple[str, str, dict]] | None = None,
                         *, source: Path | None = None, links: LinkTargets | None = None) -> str:
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
        source: この本文のローカルファイル。links と併せて相対パスを解決する
        links: 全ターゲットの文書とローカルパスの対応。source と併せて渡すと、これだけで解決する
               （明示パスはそのまま照合する。ファイル名だけで指定され、その場所にファイルがない場合には、同種記事を優先して一意な同名文書を探す）。
               解決できないリンクはそのまま残す
    """
    def replace_link(link):
        text, href = link.label, link.url

        # 外部 URL、アンカーリンク、非 .md ファイルはスキップ
        if href.startswith(("http://", "https://", "//", "#", "mailto:")):
            return link.original
        link_path, sep, fragment = href.partition("#")
        if not link_path.endswith(".md"):
            return link.original
        fragment_suffix = sep + fragment
        # エディタが日本語ファイル名を %E6... とエンコードしたリンクも解決する
        link_path = unquote(link_path)

        # 0. 全ターゲットの対応があれば、それだけで解決する（接続先の異なる紐付けは除外済み）
        if links is not None and source is not None:
            named_path = Path(source).parent / link_path
            try:
                url = links.url_for(named_path)
                if url is None and Path(link_path).name == link_path and not named_path.exists():
                    url = links.url_for_name(link_path, entity)
            except (OSError, ValueError, RuntimeError):
                return link.original
            return link.with_url(url + fragment_suffix) if url is not None else link.original

        # パスからファイル名を抽出
        target_filename = Path(link_path).name

        # 1. 同じターゲット内の mapping を検索
        eid = mapping.get(target_filename)
        target_entity = entity
        if eid is not None:
            page = _ENTITY_TO_PAGE[target_entity]
            url = f"{public_url(base_url)}/{page}.php?mode=view&id={eid}{fragment_suffix}"
            return link.with_url(url)

        # 2. 他のターゲットの mapping を検索
        if all_mappings:
            for _docs_dir, other_entity, other_mapping in all_mappings:
                eid = other_mapping.get(target_filename)
                if eid is not None:
                    page = _ENTITY_TO_PAGE[other_entity]
                    url = f"{public_url(base_url)}/{page}.php?mode=view&id={eid}{fragment_suffix}"
                    return link.with_url(url)

        # 解決できないリンクはそのまま残す
        return link.original

    return _replace_body_links(body, replace_link, images=False)


def _rewrite_elab_links_to_local(body: str, base_url: str,
                                 mapping: dict, entity: str,
                                 all_mappings: list[tuple[str, str, dict]] | None = None,
                                 target_docs_dir: str = "",
                                 *, source: Path | None = None, links: LinkTargets | None = None) -> str:
    """eLabFTW の記事 URL をローカルファイルリンクに逆変換する。

    each モード専用。merge モードでは mapping が空のため変換は行われない。

    対象: [text](https://elab.example.com/database.php?mode=view&id=42)（実験ノートは experiments.php）
    → [text](./file.md)  (同一ターゲット内)
    → [text](../other_dir/file.md)  (他ターゲット)

    Args:
        body: Markdown/HTML 本文
        base_url: eLabFTW のベース URL
        mapping: 現在のターゲットの {filename: entity_id}
        entity: 現在のターゲットの entity タイプ
        all_mappings: 全ターゲットの [(docs_dir, entity_type, {filename: eid}), ...]
        target_docs_dir: 現在のターゲットの docs_dir（相対パス計算用）
        source: この本文を書き込むローカルファイル。links と併せて相対パスを計算する
        links: 全ターゲットの文書とローカルパスの対応。source と併せて渡すと、これだけで解決し、
               mapping・all_mappings は使わない。解決できない URL はそのまま残す
    """
    # reverse mapping: entity_id → filename
    reverse = {v: k for k, v in mapping.items()}

    # 全ターゲットの reverse mapping
    all_reverse: list[tuple[str, str, dict[int, str]]] = []
    if all_mappings:
        for docs_dir, other_entity, other_mapping in all_mappings:
            all_reverse.append((docs_dir, other_entity, {v: k for k, v in other_mapping.items()}))

    def replace_link(link):
        text, href = link.label, link.url

        match = _ELAB_URL_RE.match(href)
        if not match:
            return link.original

        link_base = match.group("base")
        link_page = match.group("page")  # "database" or "experiments"
        link_entity = _PAGE_TO_ENTITY.get(link_page, link_page)  # → "items" or "experiments"
        link_id = int(match.group("id"))
        fragment = match.group("fragment") or ""  # #section など
        # 括弧の対応がとれないフラグメント（数や順序が合わない）は、ローカルリンクに書き戻すと
        # リンク先が変わるので変換しない。
        depth = 0
        for char in fragment:
            depth += {"(": 1, ")": -1}.get(char, 0)
            if depth < 0:
                break
        if depth != 0:
            return link.original

        # ホスト完全一致でなければスキップ（外部 eLabFTW リンク）
        if not _hosts_match(base_url, link_base):
            return link.original

        # 0. 全ターゲットの対応があれば、それだけで解決する（接続先の異なる紐付けは除外済み）
        if links is not None and source is not None:
            path = links.path_for(link_entity, link_id)
            if path is None:
                return link.original
            return link.with_url(_relative_link(path, Path(source).resolve().parent) + fragment)

        # 1. 同じターゲット内で解決
        if link_entity == entity and link_id in reverse:
            filename = reverse[link_id]
            return link.with_url(f"./{filename}{fragment}")

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
                    return link.with_url(rel_path + fragment)
                else:
                    return link.with_url(f"./{filename}{fragment}")

        # 解決できない eLabFTW リンクはそのまま残す
        return link.original

    return _replace_body_links(body, replace_link, images=False)


def _is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def _rewrite_videos(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path, strict: bool = False, stale_out: list | None = None, uploaded=None, verified=None, record=None, preferred=(), used_urls=None) -> str:
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
            url = upload_url(client.base_url, u)
            if url:
                existing.setdefault(rn, []).append({
                    "url": url,
                    "size": int(u.get("filesize", 0) or 0),
                    "id": u.get("id"),
                    "hash": upload_sha256(u) if strict else None,
                })
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        if strict:
            raise

    stale_ids: list[int] = []

    def _process_video_match(alt: str, src: str, full_match: str) -> str:
        if src.startswith(("http://", "https://", "//")):
            return full_match
        if not _is_video(src):
            return full_match

        video_path = _resolve_asset_path(docs_dir, project_root, src, strict)
        if not video_path.exists():
            if strict:
                raise FileNotFoundError(f"動画が見つかりません: {src}")
            progress(f"    ⚠ 動画が見つかりません: {src}", warning=True)
            return full_match

        real_name = video_path.name
        entries = existing.get(real_name, [])
        local_size = video_path.stat().st_size

        local_hash = _compute_file_hash(video_path) if strict else None
        reuse = _matching_upload(entries, real_name, local_size, local_hash, client, entity, entity_id, strict, preferred)
        if reuse:
            if used_urls is not None:
                used_urls[reuse["id"]] = reuse["url"]
                if record:
                    record(dict(id=reuse["id"], name=real_name, size=local_size, sha256=local_hash))
            _remember_asset(verified, src, local_hash)
            for e in entries:
                if e is not reuse and e.get("id") is not None:
                    stale_ids.append(e["id"])
            progress(f"    ✓ {real_name}（既存アップロードを再利用）")
            return f'<video src="{reuse["url"]}" controls>{alt}</video>'

        progress(f"    動画をアップロード中: {real_name}")
        result = _upload_body_file(client, entity, entity_id, video_path, uploaded, project_root, record=record,
                                   expected_hash=(verified or {}).get(src))
        if result.get("url"):
            if used_urls is not None:
                used_urls[result["id"]] = result["url"]
            if verified is not None:
                _remember_asset(verified, src, uploaded[result["id"]][2])
            for e in entries:
                if e is not reuse and e.get("id") is not None and not e.get("fresh"):
                    stale_ids.append(e["id"])
            sent = uploaded[result["id"]] if uploaded is not None else (real_name, local_size, None)
            _cache_uploaded(existing, real_name, result["url"], sent[1], result.get("id"), sent[2])
            progress(f"    ✓ {real_name}")
            return f'<video src="{result["url"]}" controls>{alt}</video>'
        if strict:
            raise RuntimeError(f"アップロード失敗: {real_name}")
        progress(f"    ✗ アップロード失敗: {real_name}", warning=True)
        return full_match

    # 画像と通常のリンクから動画を検出。重複排除して後ろから置換。
    matches: list[tuple[int, int, str, str, str]] = []
    for link in _body_links(body):
        if _is_video(link.url):
            matches.append((link.start, link.end, link.label, link.url, link.original))

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

    if strict and stale_out is not None:
        stale_out.extend(stale_ids)
    for uid in ([] if strict else stale_ids):
        try:
            client.delete_upload(entity, entity_id, uid)
        except Exception:
            pass
    return result


def _count_local_videos(body: str) -> int:
    """本文中のローカル動画リンク数をカウントする。"""
    count = 0
    for link in _body_links(body):
        src = link.url
        if not src.startswith(("http://", "https://", "//")) and _is_video(src):
            count += 1
    return count


def _rewrite_file_links(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path, strict: bool = False, stale_out: list | None = None, uploaded=None, verified=None, record=None, preferred=(), used_urls=None) -> str:
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
            url = upload_url(client.base_url, u)
            if url:
                existing.setdefault(rn, []).append({
                    "url": url,
                    "size": int(u.get("filesize", 0) or 0),
                    "id": u.get("id"),
                    "hash": upload_sha256(u) if strict else None,
                })
        for entries in existing.values():
            entries.sort(key=lambda e: e.get("id") or 0)
    except Exception:
        if strict:
            raise

    stale_ids: list[int] = []

    def _process_file_match(link):
        src, full_match = link.url, link.original
        if src.startswith(("http://", "https://", "//", "#", "mailto:", "data:")):
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
            progress(f"    ⚠ ファイルが見つかりません: {src}", warning=True)
            return full_match

        real_name = file_path.name
        entries = existing.get(real_name, [])
        local_size = file_path.stat().st_size

        local_hash = _compute_file_hash(file_path) if strict else None
        reuse = _matching_upload(entries, real_name, local_size, local_hash, client, entity, entity_id, strict, preferred)
        if reuse:
            if used_urls is not None:
                used_urls[reuse["id"]] = reuse["url"]
                if record:
                    record(dict(id=reuse["id"], name=real_name, size=local_size, sha256=local_hash))
            _remember_asset(verified, src, local_hash)
            for e in entries:
                if e is not reuse and e.get("id") is not None:
                    stale_ids.append(e["id"])
            progress(f"    ✓ {real_name}（既存アップロードを再利用）")
            return link.with_url(reuse["url"], as_file=True)

        progress(f"    ファイルをアップロード中: {real_name}")
        result = _upload_body_file(client, entity, entity_id, file_path, uploaded, project_root, record=record,
                                   expected_hash=(verified or {}).get(src))
        if result.get("url"):
            if used_urls is not None:
                used_urls[result["id"]] = result["url"]
            if verified is not None:
                _remember_asset(verified, src, uploaded[result["id"]][2])
            for e in entries:
                if e is not reuse and e.get("id") is not None and not e.get("fresh"):
                    stale_ids.append(e["id"])
            sent = uploaded[result["id"]] if uploaded is not None else (real_name, local_size, None)
            _cache_uploaded(existing, real_name, result["url"], sent[1], result.get("id"), sent[2])
            progress(f"    ✓ {real_name}")
            return link.with_url(result["url"], as_file=True)
        if strict:
            raise RuntimeError(f"アップロード失敗: {real_name}")
        progress(f"    ✗ アップロード失敗: {real_name}", warning=True)
        return full_match

    result = _replace_body_links(body, _process_file_match, images=None)

    if strict and stale_out is not None:
        stale_out.extend(stale_ids)
    for uid in ([] if strict else stale_ids):
        try:
            client.delete_upload(entity, entity_id, uid)
        except Exception:
            pass
    return result


def _count_local_file_links(body: str) -> int:
    """本文中の非画像・非動画ローカルファイルリンク数をカウントする。"""
    count = 0
    for link in _body_links(body):
        src = link.url
        if not src.startswith(("http://", "https://", "//", "#", "mailto:", "data:")) and not _is_image(src) and not _is_video(src) and not src.split("#", 1)[0].endswith(".md"):
            count += 1
    return count


def _url_origin(url, default_scheme):
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower() or default_scheme
    host = unquote(parsed.hostname or "").rstrip(".")
    if ":" in host:
        host = str(ipaddress.IPv6Address(host))
    elif host:
        # WHATWG のドメイン区切りと既定ポートに合わせる。ASCII の "_" はブラウザーでも有効。
        host = idna.uts46_remap(host, std3_rules=False).rstrip(".").lower()
        if not host.isascii():
            host = idna.encode(host, uts46=True).decode("ascii").lower()
    port = parsed.port if parsed.port is not None else {"http": 80, "https": 443}.get(scheme)
    return scheme, host, port


def _referenced_upload_ids(uploads, body, base_url):
    server = _url_origin(str(base_url), "https")

    def retain_local_url(match):
        return match.group() if _url_origin(match.group(), server[0]) == server else ""

    # %20 などの復号前に URL 全体を切り出し、別サーバーのパスを除外する。
    text = re.sub(r"""(?:https?:)?//[^\s<>"')]+""", retain_local_url, _html.unescape(body).replace("\\", "/"), flags=re.I)
    decoded = unquote(text)
    ids = set(re.findall(r"/uploads/(\d+)(?!\d)", decoded))
    long_names = set()
    for src in _attachment_links(body, 2):
        if not src:
            continue
        url = src.strip(" \t\r\n\f").replace("\\", "/")
        parsed = urlsplit(url)
        if (parsed.scheme or parsed.netloc) and _url_origin(url, server[0]) != server:
            continue
        path = unquote(posixpath.normpath("/" + re.sub(r"%2e", ".", parsed.path, flags=re.I).lstrip("/")))
        ids.update(re.findall(r"/uploads/(\d+)(?!\d)", path))
        if path.rsplit("/", 1)[-1] == "download.php":
            long_names.update(parse_qs(parsed.query).get("f", []))
    return {u["id"] for u in uploads if u.get("id") is not None
            and (str(u["id"]) in ids or (u.get("long_name") and (u["long_name"] in long_names or u["long_name"] in decoded)))}


def _prune_candidates(uploads, local_names, pattern, body, base_url):
    from fnmatch import fnmatch
    referenced_names = set(local_names)
    # Deletion also protects references that the local URL rewriter cannot edit.
    for tag, src in _attachment_links(body, 2, with_tags=True):
        if not src or src.startswith(("//", "#")):
            continue
        src = src.strip(" \t\r\n\f").replace("\\", "/")
        parsed = urlsplit(src)
        if parsed.scheme or parsed.netloc:
            continue
        path_name = posixpath.basename(posixpath.normpath(unquote(parsed.path)))
        referenced_names.update((Path(src).name, path_name))
        if tag == "img":
            referenced_names.add(_parse_image_local_name(path_name) or path_name)
    candidates = [u for u in uploads if u.get("id") is not None and u.get("real_name")
        and u["real_name"] not in referenced_names and not _is_image(u["real_name"])
        and fnmatch(u["real_name"], pattern)]
    if not candidates:
        return []
    referenced_ids = _referenced_upload_ids(candidates, body, base_url)
    return [u for u in candidates if u["id"] not in referenced_ids]


def _localize_attachment_links(body, uploads, directory, source, base_url, entity, eid):
    """Restore links to the files pull saves, using URLs belonging to this article."""
    paths = {}
    for upload in uploads:
        name = upload.get("real_name")
        if not name or Path(name).name != name or _is_image(name) or Path(name).suffix.lower() == ".md":
            continue
        local = _relative_link(directory / name, source.parent)
        if name.startswith(".") or "\\" in local or any(ord(char) < 32 for char in local):
            continue
        url = upload_url(base_url, upload)
        if url:
            paths[url] = local
            parsed = urlsplit(url)
            paths[parsed.path + "?" + parsed.query] = local
        if upload.get("id") is not None:
            path = f"/api/v2/{entity}/{eid}/uploads/{upload['id']}"
            absolute = base_url.rstrip("/") + path
            paths[urlsplit(absolute).path] = paths[absolute] = local

    def replace(link):
        local = paths.get(link.url)
        if local is None:
            base_path = urlsplit(base_url).path.rstrip("/")
            if link.url.startswith(("/app/download.php?", "/api/v2/", base_path + "/app/download.php?", base_path + "/api/v2/")):
                # 本文に残る URL なので、接続先の認証情報は含めない。
                site = urlsplit(public_url(base_url))
                return link.with_url(f"{site.scheme}://{site.netloc}{link.url}")
            return link.original
        destination = _html.escape(local, quote=False)
        if not re.fullmatch(r"[\w./-]+", local) and link.original[link.target_start-1] != "<":
            destination = f"<{destination}>"
        return link.with_url(destination)

    return _replace_body_links(body, replace, images=False)


def _publish_download(dest, data, backup, expected, default_mode):
    with hold_document(dest, backup, expected, asset=True) as held:
        mode = held.stat().st_mode & 0o777 if held else default_mode
        atomic_write(dest, data, mode=mode, exclusive=True)


def _download_attachments(entity: str, entity_id: int, client: ELabFTWClient, attachments_dir: Path, strict: bool = False,
                          keep_existing: bool = False, uploads=None, exclusive_paths=(), backup=None, expected_files=None, keep_paths=(), digests=None) -> None:
    """リモートの非画像添付ファイルをローカルにダウンロードする。

    keep_paths にはマージ時に保持するパスを渡す。pull は expected_files に保存前の
    SHA-256（新規作成なら None）を記録し、既存ファイルを backup に退避してから
    atomic_write で排他的に公開する。digests には確認・取得した内容を記録する。
    keep_existing=True は既存の呼び出し用で、保存済みのファイルをすべて保持する。
    """
    try:
        if uploads is None:
            uploads = client.list_uploads(entity, entity_id)
    except Exception as e:
        if strict:
            raise
        progress(f"    ⚠ 添付ファイル一覧の取得に失敗: {_error_text(client, e)}", warning=True)
        return
    for u in uploads:
        rn = u.get("real_name")
        if not rn or _is_image(rn):
            continue
        # パストラバーサル防止: basename のみ使用
        safe_name = Path(rn).name
        if not safe_name or safe_name in (".", ".."):
            progress(f"    ⚠ 不正なファイル名をスキップ: {rn!r}", warning=True)
            continue
        dest = safe_path(attachments_dir, safe_name)
        attachments_dir.mkdir(parents=True, exist_ok=True)
        if dest in exclusive_paths and dest.exists():
            raise FileExistsError(f"解放した保存先に別のファイルが作成されています: {dest}")
        if dest in keep_paths or (keep_existing and dest.exists()):
            if digests is not None:
                digests[dest] = expected_files[dest]
            continue
        remote_size = int(u.get("filesize", 0) or 0)
        if dest.exists() and remote_size:
            local_size = dest.stat().st_size
            if local_size == remote_size:
                # サイズ一致 → ハッシュも確認（リモートにハッシュがある場合）
                remote_hash = u.get("hash") or u.get("sha256")
                if remote_hash:
                    local_hash = _compute_file_hash(dest)
                    if local_hash == remote_hash:
                        if digests is not None:
                            digests[dest] = local_hash
                        continue
                elif not strict:
                    continue
        try:
            overwriting = dest.exists()
            orig_mode = dest.stat().st_mode & 0o777 if overwriting else None
            data = client.download_upload(entity_type=entity, entity_id=entity_id, upload_id=u["id"])
            if digests is not None:
                digests[dest] = hashlib.sha256(data).hexdigest()
            if expected_files is not None:
                _publish_download(dest, data, backup, expected_files[dest], 0o666 & ~_UMASK)
                progress(f"    添付ファイルをダウンロード: {safe_name}")
                continue
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
                if dest in exclusive_paths:
                    _os.link(tp, dest)
                    tp.unlink()
                else:
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
                progress(f"    ⚠ 上書き: {safe_name}（{entity} #{entity_id} の添付で既存ファイルを置換）", warning=True)
            progress(f"    添付ファイルをダウンロード: {safe_name}")
        except Exception as e:
            if strict:
                raise
            progress(f"    ⚠ 添付ファイルのダウンロードに失敗: {safe_name}: {_error_text(client, e)}", warning=True)



def _sync_tags(client: ELabFTWClient, entity_type: str, entity_id: int, desired_tags: list[str]) -> bool:
    """設定のタグを追記し、取得・更新に失敗した場合はFalseを返す。"""
    if not desired_tags:
        return True
    try:
        remote = client.get_tags(entity_type, entity_id)
        remote_names = set(_tag_names(remote))
        for tag in desired_tags:
            if tag not in remote_names:
                client.add_tag(entity_type, entity_id, tag)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("タグ同期失敗", exc_info=True)
        progress(f"    ⚠ タグ同期に失敗しました（本文の同期は成功しています）", warning=True)
        return False
    return True


def _sync_links(client: ELabFTWClient, entity_type: str, entity_id: int, desired_links: dict) -> bool:
    """設定のリンクを追加し（既存のリンクは削除しない）、取得・作成に失敗した場合はFalseを返す。

    失敗しても残りのリンクは試し、失敗したリンク先と原因（HTTP ステータスなど）を表示する。
    """
    ok = True
    for link_type, ids in (desired_links or {}).items():
        # 自分自身へのリンクは作らない（ターゲットの全文書に同じ設定を適用するため）
        wanted = [i for i in ids if not (link_type == entity_type and i == entity_id)]
        if not wanted:
            continue
        label = "実験ノート" if link_type == "experiments" else "リソース"
        try:
            existing = {link.get("entityid") for link in client.list_links(entity_type, entity_id, link_type)}
        except Exception as exc:
            progress(f"    ⚠ {label}へのリンク一覧の取得に失敗しました: {_describe_error(exc)}", warning=True)
            ok = False
            continue
        for target_id in wanted:
            if target_id in existing:
                continue
            try:
                client.add_link(entity_type, entity_id, link_type, target_id)
            except Exception as exc:
                progress(f"    ⚠ {label} #{target_id} へのリンク追加に失敗しました: {_describe_error(exc)}", warning=True)
                ok = False
    if not ok:
        progress("    （本文・タグ・カテゴリは送信済みです。リンク先の ID と権限を確認し、再度 push してください）")
    return ok


def _error_text(client, exc):
    return error_text(exc, getattr(client, "api_key", None))


def _describe_error(exc):
    if getattr(getattr(exc, "response", None), "status_code", None) is not None:
        return error_text(exc)
    return type(exc).__name__


def _shell_quote(value, windows=None):
    """Quote an argument so a suggested command can be pasted into the shell.

    POSIX shells use shlex.quote. On Windows the target is PowerShell: inside
    single quotes nothing is expanded ($(...), $var, `). PowerShell treats
    ' and the typographic quotes ‘ ’ ‚ ‛ alike, so each of them is written
    twice. cmd.exe is not supported.
    """
    if windows is None:
        windows = _os.name == "nt"
    if not windows:
        return shlex.quote(value)
    if value and re.fullmatch(r"[A-Za-z0-9_@%+=:,./\\-]+", value):
        return value
    return "'" + re.sub(f"([{_POWERSHELL_QUOTES}])", r"\1\1", value) + "'"


_POWERSHELL_QUOTES = "'\u2018\u2019\u201a\u201b"


REMOTE_FIELD_LABELS = {"body": "本文", "title": "タイトル", "content_type": "本文形式",
                       "category": "カテゴリ", "tags": "タグ", "uploads": "添付"}


def _format_category(value):
    return "なし" if value is None else f"#{value}"


def _sync_category(client: ELabFTWClient, entity_type: str, entity_id: int, category, current: dict | None = None) -> None:
    """設定のカテゴリをリモートに設定する。best-effort。

    current（エンティティの現在データ）が既に目的のカテゴリなら PATCH しない。
    """
    if category is None:
        return True
    try:
        cat_id = client.resolve_category_id(entity_type, category, current=current)
        if current is not None and _category_value(current.get("category")) == cat_id:
            return True
        client.patch_entity(entity_type, entity_id, category=cat_id)
    except Exception:
        import logging
        logging.getLogger(__name__).debug("カテゴリ同期失敗", exc_info=True)
        progress(f"    ⚠ カテゴリ同期に失敗しました（本文の同期は成功しています）", warning=True)
        return False
    return True


class EachDocsSyncer:
    """One file per entity, with shared three-way state inspection."""

    # .base keeps the eLabFTW body as of the last sync (converted as pull does)
    # for three-way merges; .synced keeps the local body as of the last sync
    # for diff. Neither may end in .md: the state directory may lie under docs_dir.
    SUFFIXES = (".hash", ".remote_hash", ".meta_hash", ".assets_hash", ".state.json", ".base", ".synced")

    def __init__(self, client, target, project_root):
        self.client = client
        self.target = target
        self.entity = target.entity
        self.project_root = Path(project_root).resolve()
        self.docs_dir = self.project_root / target.docs_dir
        self.mapping_file = (self.project_root / target.id_file).parent / "mapping.json"
        self.hash_dir = self.mapping_file.parent
        self.updated = 0
        self.failures = 0
        self.skipped = 0
        # 文書間リンクの解決に使う全ターゲットの syncer（CLI が設定する）
        self.link_syncers = []

    def readable_link_mapping(self):
        """参照先候補を返す。読めない紐付けはリンクの自動変換には使わない。"""
        try:
            return self._load_mapping(migrate=False)
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def link_targets(self, mapping=None):
        """全ターゲットの追跡中の文書から、文書間リンクの対応を作る。

        接続先のホストが異なるターゲットは含めない（ID が別サーバーのものになるため）。
        mapping を渡すと、このターゲットについては保存前の紐付けを使う。
        """
        links = LinkTargets(self.client.base_url)

        def recorded_here(syncer, name):
            # 接続先を変える前の紐付けは、別サーバーの ID を指すため使わない
            try:
                state = syncer._state(name)
                return state is None or (server_id(state["server"]) == server_id(syncer.client.base_url)
                                         and state["entity"] == syncer.entity)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                return False

        for other in self.link_syncers:
            same_host = (other.client.base_url == self.client.base_url
                         or _hosts_match(self.client.base_url, other.client.base_url))
            if other.mapping_file == self.mapping_file or not same_host:
                continue
            for name, eid in other.readable_link_mapping().items():
                if not recorded_here(other, name):
                    continue
                try:
                    links.add(other.entity, eid, other.file_path(name))
                except ValueError:
                    continue  # 同名ファイルが複数ある文書は特定できない
        for name, eid in (self.readable_link_mapping() if mapping is None else mapping).items():
            if recorded_here(self, name):
                try:
                    links.add(self.entity, eid, self.file_path(name))
                except (OSError, ValueError):
                    continue
        return links

    def _refresh_local_hash(self, filename, raw_body):
        """リモートと無関係にローカル本文だけを書き換えたとき、ローカル側の基準を合わせる。"""
        self._save_hash(filename, raw_body)
        path = self.hash_dir / f"{filename}.state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["local_hash"] = _compute_hash(raw_body)
        write_json(path, state)

    def backup_paths(self):
        paths = [self.docs_dir, self.hash_dir]
        if self.target.attachments_dir:
            paths.append(self.project_root / self.target.attachments_dir)
        return paths

    def _load_mapping(self, *, migrate=True, prospective_name=None):
        source = self.mapping_file
        load_legacy = not source.exists()
        if load_legacy:
            source = self.project_root / ".elab-sync-ids/mapping.json"
            if not source.exists() or source == self.mapping_file:
                return {}
        records = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(records, dict):
            raise ValueError(f"紐付け情報の形式が不正です: {source}")
        mapping = {}
        seen_ids = set()
        for name, eid in records.items():
            if not name or name in (".", "..") or Path(name).name != name or (load_legacy and "\\" in name):
                if load_legacy:
                    continue
                raise ValueError(f"紐付け情報の形式が不正です: {source} のファイル名 {name!r}")
            if load_legacy and name != prospective_name and not (self.docs_dir / name).is_file():
                continue
            if type(eid) is not int or eid <= 0:
                raise ValueError(f"紐付け情報の形式が不正です: {source} の {name!r} の記事 ID")
            if eid in seen_ids:
                raise ValueError(f"同じリモートIDに複数文書が紐付いています。{source} の {name!r} と ID {eid} を確認してください")
            seen_ids.add(eid)
            mapping[name] = eid
        if load_legacy and mapping and migrate:
            snapshot(self.project_root, [self.hash_dir], "旧紐付けの移行")
            self._save_mapping(mapping)
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
        if not path.exists():
            return None
        state = json.loads(path.read_text(encoding="utf-8"))
        state["remote"] = _normalize_metadata_signature(state["remote"])
        return state

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

    def applied_links(self, filename):
        """push で張り終えたと記録したリンク {"experiments": [...], "items": [...]}。"""
        state = self._state(filename)
        return (state or {}).get("links") or {}

    def _links_pending(self, filename):
        """設定の links のうち、この文書でまだ張り終えていないものがあるか。

        pull・link は eLabFTW にリンクを張らないため、張り終えた記録を引き継ぐだけで、
        新しく取得した文書は次の push でリンクを追加する。設定から外した ID は削除しない。
        """
        applied = self.applied_links(filename)
        return any(set(ids) - set(applied.get(t, [])) for t, ids in self.target.links.items())

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

    def _compute_assets_hash(self, raw_body, filename=None, *, body_evidence=None, downloaded=None, observed=None):
        parts = []
        document_dir = self.file_path(filename).parent if filename else self.docs_dir
        # Preserve the image-first order used by existing asset hashes.
        for link in sorted(_body_links(raw_body), key=lambda entry: not entry.image):
            src = link.url
            if src.startswith(("http://", "https://", "//")):
                continue
            if not link.image and (src.startswith(("#", "mailto:", "data:")) or src.split("#")[0].endswith(".md") or _is_image(src)):
                continue
            if body_evidence is not None:
                parts.append(f"{src}:{body_evidence.get(src, 'missing')}")
                continue
            path = _resolve_asset_path(document_dir, self.project_root, src, strict=True)
            if downloaded is not None and path in downloaded:
                parts.append(f"{src}:{downloaded[path]}")
            else:
                digest = _compute_file_hash(path) if path.is_file() else 'missing'
                parts.append(f"{src}:{digest}")
                if observed is not None:
                    _remember_asset(observed, src, digest)
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def asset_changes(self, filename, body, observed, uploads):
        """Compare referenced local files with the article's current uploads for a push preview."""
        images = {link.url for link in _body_links(body) if link.image and not _is_video(link.url)}
        changes = []
        for src, digest in observed.items():
            path = _resolve_asset_path(self.file_path(filename).parent, self.project_root, src, strict=True)
            name = (_parse_image_local_name(path.name) if src in images else None) or path.name
            candidates = [u for u in uploads if u.get("real_name") == name]
            if digest == "missing":
                action = "missing"
            elif not candidates:
                action = "add"
            elif any(upload_sha256(u) == digest for u in candidates):
                continue
            else:
                size = str(path.stat().st_size)
                unknown = any(not upload_sha256(u) and (u.get("filesize") is None or str(u["filesize"]) == size)
                              for u in candidates)
                action = "unverified" if unknown else "replace"
            changes.append({"path": src, "name": name, "action": action})
        return changes

    def previous_asset_paths(self, filename):
        parent = self.file_path(filename).parent
        paths = set()
        for link in _body_links(self.load_base(filename) or ""):
            if (link.url.startswith(("http://", "https://", "//", "/", "#", "mailto:", "data:"))
                    or link.url.split("#", 1)[0].endswith(".md")):
                continue
            paths.add(_resolve_asset_path(parent, self.project_root, link.url, strict=True))
        return paths

    def check_merge_asset_sources(self, filename, uploads, destinations):
        """Refuse to adopt a changed remote upload while a merge can retain an older local source."""
        state = self._state(filename)
        previous = state.get("remote", {}).get("uploads", []) if state else []
        current = self._remote_signature({}, uploads)["uploads"]
        source = self.file_path(filename)
        for link in _body_links(source.read_text(encoding="utf-8")):
            src = link.url
            if src.startswith(("http://", "https://", "//", "#", "mailto:", "data:")) or src.split("#")[0].endswith(".md"):
                continue
            path = _resolve_asset_path(source.parent, self.project_root, src, strict=True)
            if not path.is_file():
                continue
            name = (_parse_image_local_name(path.name) if link.image else None) or path.name
            old = [u for u in previous if u["real_name"] == name]
            new = [u for u in current if u["real_name"] == name]
            if len(old) > 1 or len(new) > 1:
                raise ConflictError(f"{name}: 同名の添付 ID が複数あります。参照する版を確認してからマージしてください")
            if new == old:
                continue
            # Planned downloads perform a separate three-way check at the actual destination.
            if new and path in destinations:
                continue
            digest = _compute_file_hash(path)
            if len(new) == 1 and upload_sha256(new[0]) == digest:
                continue
            raise ConflictError(f"{path}: リモート添付が変更されました。手元の本文と添付を別の場所に保存し、取得する版を確認してください")

    def _assets_changed(self, filename, raw_body):
        state = self._state(filename)
        hp = self.hash_dir / f"{filename}.assets_hash"
        saved = state["assets_hash"] if state else hp.read_text().strip() if hp.exists() else None
        return saved is not None and saved != self._compute_assets_hash(raw_body, filename)

    def _remote_signature(self, data, uploads):
        return {"body": data.get("body") or "", "title": data.get("title") or "",
                "content_type": data.get("content_type"), "category": _category_value(data.get("category")), "tags": _tag_names(data.get("tags")),
                "uploads": sorted([{k: u.get(k) for k in ("id", "real_name", "hash", "sha256", "filesize", "long_name")}
                                   for u in uploads], key=lambda u: str(u["id"]))}

    def remote_changes(self, filename, data, uploads):
        """前回同期時から eLabFTW 側で変わった項目のキーを返す（基準情報がなければ空）。"""
        state = self._state(filename)
        if not state:
            return []
        old, new = state["remote"], self._remote_signature(data, uploads)
        return [k for k in REMOTE_FIELD_LABELS if old.get(k) != new.get(k)]

    def describe_remote_changes(self, filename, data, uploads):
        """前回同期時からの eLabFTW 側の変更を (本文以外の説明行, 前回本文, 現在本文) で返す。"""
        state = self._state(filename)
        if not state:
            return [], None, None
        old, new = state["remote"], self._remote_signature(data, uploads)
        lines = []
        if old["title"] != new["title"]:
            lines.append(f"タイトル: {old['title']!r} → {new['title']!r}")
        if old.get("content_type") != new.get("content_type"):
            lines.append(f"本文形式: {old.get('content_type')} → {new.get('content_type')}")
        if old.get("category") != new.get("category"):
            lines.append(f"カテゴリ: {_format_category(old.get('category'))} → {_format_category(new.get('category'))}")
        added_tags = sorted(set(new["tags"]) - set(old["tags"]))
        removed_tags = sorted(set(old["tags"]) - set(new["tags"]))
        if added_tags or removed_tags:
            lines.append("タグ: " + " ".join([f"+{t}" for t in added_tags] + [f"-{t}" for t in removed_tags]))
        old_uploads = {str(u.get("id")): u for u in old["uploads"]}
        new_uploads = {str(u.get("id")): u for u in new["uploads"]}
        for uid in sorted(set(new_uploads) - set(old_uploads)):
            lines.append(f"添付追加: {new_uploads[uid].get('real_name')} (#{uid})")
        for uid in sorted(set(old_uploads) - set(new_uploads)):
            lines.append(f"添付削除: {old_uploads[uid].get('real_name')} (#{uid})")
        for uid in sorted(set(old_uploads) & set(new_uploads)):
            if old_uploads[uid] != new_uploads[uid]:
                lines.append(f"添付変更: {new_uploads[uid].get('real_name')} (#{uid})")
        return lines, old["body"], new["body"]

    def _delete_stale_uploads(self, eid, stale_ids, pending, filename, prune_ids=(), check_urls=None):
        """旧版・明示的な整理候補を削除し、削除できた ID の集合を返す。

        旧版の削除に失敗したら警告を出力して次の候補に進む。prune_ids の削除失敗は例外を伝播し、
        未完了記録を残して同じオプションでの再開を可能にする。

        文書の本文・タグ・カテゴリ・添付の同期がすべて済んだ後にだけ呼ぶ。
        現在の本文から long_name または /uploads/{id} で参照されている添付は
        削除しない。削除の途中で止まっても再開できるよう、削除候補を先に
        pending の deleting に記録する。
        """
        def checked_body():
            data = self._get_entity(eid)
            if any(data.get(k) != v for k, v in pending[filename]["stored"].items()):
                raise ConflictError("添付削除前にリモート本文が変更されました。diffで確認してください")
            return data.get("body") or ""

        body = checked_body()
        by_id = {u.get("id"): u for u in self.client.list_uploads(self.entity, eid)}
        protected = _referenced_upload_ids(by_id.values(), body, self.client.base_url)
        candidates = [uid for uid in dict.fromkeys(stale_ids) if uid in by_id and uid not in protected]
        if not candidates:
            return set()
        pending[filename]["deleting"] = candidates
        self._save_pending(pending)
        deleted = set()
        expected_uploads = pending[filename]["guard"]["uploads"]
        for uid in candidates:
            current = self.client.list_uploads(self.entity, eid)
            if check_urls:
                check_urls(current)
            expected = [u for u in expected_uploads if u["id"] not in deleted]
            if self._remote_signature({}, current)["uploads"] != expected:
                raise ConflictError("削除前にリモート添付が変更されました。diffで確認してください")
            checked_body()
            name = by_id[uid].get("real_name")
            try:
                self.client.delete_upload(self.entity, eid, uid)
                deleted.add(uid)
                progress(f"    古い版の添付を削除しました: {name} (#{uid})")
            except Exception:
                if uid in prune_ids:
                    raise
                import logging
                logging.getLogger(__name__).debug("古い添付の削除失敗", exc_info=True)
                progress(f"    ⚠ 古い版の添付を削除できませんでした: {name} (#{uid})", warning=True)
        return deleted

    @staticmethod
    def _guard_matches(owned, current_guard):
        """記録した guard と現在を比べる。

        削除途中の添付（deleting）については、消えていることだけを許す。
        残っている候補は記録と完全に一致しなければならない。
        """
        guard = owned.get("guard")
        if guard is None:
            return False
        deleting = set(owned.get("deleting") or [])
        if not deleting:
            return guard == current_guard
        present = {u.get("id") for u in current_guard.get("uploads", [])}
        expected = [u for u in guard.get("uploads", []) if u.get("id") not in deleting or u.get("id") in present]
        return {**guard, "uploads": expected} == current_guard

    def _verify_uploaded_attachment(self, eid, uploads, receipt):
        """保存した送信記録をサーバーの一覧・実体と照合し、確認できた署名を返す。"""
        uid = receipt["id"]
        entry = next((u for u in uploads if uid is not None and u.get("id") == uid), None)
        if not entry:
            raise ConflictError(f"受領した添付 ID #{uid} が一覧に現れていません。一覧への反映後に同じ文書を通常の push で再実行してください")
        if entry.get("real_name") != receipt["name"] or int(entry.get("filesize") or 0) != receipt["size"]:
            raise ConflictError("送信した添付の名前・サイズを確認できません")
        digest = upload_sha256(entry)
        if not digest:
            digest = self.client.upload_digest(entity_type=self.entity, entity_id=eid, upload_id=uid)
        if digest != receipt["sha256"]:
            raise ConflictError("送信した添付の内容が一致しません")
        return self._remote_signature({}, [entry])["uploads"][0]

    @staticmethod
    def _resume_versions(owned):
        # PATCH の保存結果を確認した後は、編集者が以前の版に戻した場合も競合とする。
        if owned.get("stored") is not None:
            return [owned["stored"]]
        return [v for v in (owned.get("expected"), owned.get("before")) if v is not None]

    def _resume_mismatch(self, owned, eid, data, current_guard):
        """未完了の同期記録と現在のリモートで食い違う項目の表示名を返す。"""
        if owned.get("eid") != eid:
            return ["文書ID"]
        labels = [] if self._guard_matches(owned, current_guard) else [
            REMOTE_FIELD_LABELS[k] for k in ("category", "tags", "uploads")
            if (owned.get("guard") or {}).get(k) != current_guard.get(k)]
        versions = self._resume_versions(owned)
        if not any(all(data.get(k) == v for k, v in version.items()) for version in versions):
            keys = {k for version in versions for k in version}
            labels[:0] = [REMOTE_FIELD_LABELS[k] for k in ("body", "title", "content_type")
                          if k in keys and all(data.get(k) != version.get(k) for version in versions if k in version)]
        return labels

    def load_base(self, filename):
        """eLabFTW body as of the last sync, converted as pull does, or None."""
        path = self.hash_dir / f"{filename}.base"
        if not path.is_file():
            return None
        base = path.read_text(encoding="utf-8")
        state = self._state(filename)
        content_type = state["remote"].get("content_type") if state else None
        return _html.unescape(base) if _is_markdown_body(content_type, self.target) else base

    def _save_base(self, filename, base, data):
        # A base converted from a Markdown body is stored HTML-escaped, the form
        # eLabFTW stores Markdown in. Released versions up to v1.0.4 saved such
        # bases unconverted, which is that same form, and saved bases from HTML
        # bodies as markdownify output, which is never unescaped here. So
        # load_base reads old and new files the same way. Whether to unescape
        # follows the remote content_type in state.json, not the current
        # body_format, which may change after the base was saved.
        is_md = _is_markdown_body(data.get("content_type"), self.target)
        atomic_write(self.hash_dir / f"{filename}.base", _html.escape(base, quote=False) if is_md else base)

    def load_synced_local(self, filename):
        """Local body as of the last sync, or None if not recorded."""
        path = self.hash_dir / f"{filename}.synced"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def remote_base(self, data, uploads, eid, mapping, links, source):
        """Convert a remote body the way pull and diff do, without downloads.

        Used as the merge base: where it differs from the local file only by
        conversion (e.g. image paths), the merge keeps the local text.
        """
        body = _remote_markdown(data, self.target)
        body = _normalize_remote_image_urls(body, self.entity, eid, self.client, uploads=uploads)
        if self.target.attachments_dir:
            body = _localize_attachment_links(body, uploads, self.project_root / self.target.attachments_dir, source,
                                              self.client.base_url, self.entity, eid)
        return _rewrite_elab_links_to_local(body, self.client.base_url, mapping, self.entity, source=source, links=links)

    def _save_baseline(self, filename, raw_body, data, uploads, base=None, links=None, assets_hash=None):
        """Record a completed sync. base defaults to raw_body (pull/link write the remote body).

        links is the record of links already applied; pull and link pass the
        previous record, so they never claim links they did not create.
        """
        self._save_base(filename, raw_body if base is None else base, data)
        atomic_write(self.hash_dir / f"{filename}.synced", raw_body)
        self._save_hash(filename, raw_body)
        self._save_remote_hash(filename, data.get("body") or "")
        self._save_meta_hash(filename, Path(filename).stem, self.target.category, self.target.tags)
        if assets_hash is None:
            assets_hash = self._compute_assets_hash(raw_body, filename)
        atomic_write(self.hash_dir / f"{filename}.assets_hash", assets_hash + "\n")
        write_json(self.hash_dir / f"{filename}.state.json", {
            "version": 1, "server": server_id(self.client.base_url), "entity": self.entity,
            "profile": self.target.profile, "team": self.target.team, "body_format": self.target.body_format,
            "local_hash": _compute_hash(raw_body), "assets_hash": assets_hash,
            "meta_hash": _compute_meta_hash(Path(filename).stem, self.target.category, self.target.tags),
            "remote": self._remote_signature(data, uploads),
            **({"links": links} if links else {}),
        })

    def label(self, filename):
        """Path of a document as shown in messages: relative to the project root."""
        path = self.file_path(filename)
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return str(path)

    def next_actions(self, state, filename, eid=None):
        """Commands that move a document in the given state forward, one per line.

        Paths are quoted for the shell and relative to the project root, where
        the commands are meant to be run. --file is relative to docs_dir, as
        link expects. --target is added when the project has several targets.
        """
        path, entity = _shell_quote(self.label(filename)), self.entity
        file_arg = _shell_quote(self.file_path(filename).relative_to(self.docs_dir).as_posix())
        target = ""
        if len(self.link_syncers) > 1:
            target = f" --target {_shell_quote(self.target.title or self.target.docs_dir)}"
        adopt_remote = f"esync pull --id {eid} --entity {entity} --force{target}" if eid else "esync pull --force"
        actions = {
            "送信待ち": [f"送信: esync push {path}"],
            "取得待ち": ["取得: esync pull"],
            "競合": ["両方の変更をマージ: esync pull（同じ箇所の変更はマーカーで残る）",
                     f"ローカルを採用（eLabFTW を上書き）: esync push --force {path}",
                     f"eLabFTW を採用（ローカルを上書き）: {adopt_remote}"],
            "競合マーカーあり": [f"マーカーを消して内容を整えてから送信: esync push {path}",
                               f"マーカーごと破棄して eLabFTW を採用: {adopt_remote}"],
            "基準情報なし": [f"差分を確認: esync diff {path}",
                         f"ローカルを採用: esync push --force {path}",
                         f"eLabFTW を採用: {adopt_remote}"],
            "同期未完了": [f"再開: esync push {path}"],
            "再開不可": [f"差分を確認: esync diff {path}",
                       f"ローカルを採用して同期を完了: esync push --force {path}",
                       f"eLabFTW を採用して同期記録を破棄: {adopt_remote}"],
            "リモート削除": [f"追跡をやめる（ローカルの文書は残る）: esync rm {path}",
                           f"eLabFTW に作り直す: esync rm {path} → esync link --new --file {file_arg}{target} → esync push {path}"],
            "ローカル削除": [f"eLabFTW から取り直す: {adopt_remote}",
                           f"追跡をやめる: esync rm --id {eid} --entity {entity}{target}"],
            "未追跡": [f"eLabFTW に新規作成: esync push {path}"],
            "確認失敗": ["接続先・API キーを確認して再実行"],
            "作成結果不明": ["eLabFTW で記事ができたかを esync list で確認",
                         f"できていれば紐付け: esync link <ID> --file {file_arg}{target}",
                         f"できていなければ作成をやり直す: esync link --new --file {file_arg}{target} → esync push {path}"],
        }
        return actions.get(state, [])

    def _print_next_actions(self, state, filename, eid=None):
        for action in self.next_actions(state, filename, eid):
            progress(f"    → {action}")

    def save_merge_baseline(self, filename, base, data, uploads, metadata_pending):
        """Record the remote side after merging it into local edits on pull.

        Body and asset hashes stay as they were, so the merged body and local
        asset edits are still sent on the next push. The metadata hash stays
        only when a setting change is still unsent (metadata_pending);
        otherwise it is recorded for the current file name, so a title taken
        from eLabFTW does not make push resend the configured tags and
        category over remote changes.
        """
        self._save_base(filename, base, data)
        self._save_remote_hash(filename, data.get("body") or "")
        meta_hash = _compute_meta_hash(Path(filename).stem, self.target.category, self.target.tags)
        if not metadata_pending:
            self._save_meta_hash(filename, Path(filename).stem, self.target.category, self.target.tags)
        state = self._state(filename)
        if state:
            write_json(self.hash_dir / f"{filename}.state.json", {
                # 以前の版が記録した接続先（認証情報付きのことがある）は、書き直すときに除く。
                **state, "server": server_id(state.get("server") or self.client.base_url),
                "remote": self._remote_signature(data, uploads),
                **({} if metadata_pending else {"meta_hash": meta_hash}),
            })

    def checked_state(self, filename):
        """保存した紐付けが現在の接続先に属するかを確かめる。"""
        state = self._state(filename)
        if state and (server_id(state["server"]) != server_id(self.client.base_url) or state["entity"] != self.entity
                      or state.get("profile", self.target.profile) != self.target.profile
                      or state.get("team", self.target.team) != self.target.team):
            raise ValueError("接続先が前回同期時と異なります。別の状態ディレクトリを指定してください")
        return state

    def inspect(self, filename, eid, data=None, uploads=None):
        """Read-only; legacy body hashes remain usable without inventing a baseline."""
        path = self.file_path(filename)
        local_exists = path.is_file()
        body = path.read_text(encoding="utf-8").strip() if local_exists else ""
        result = {"filename": filename, "entity_id": eid, "body": body, "state": "未追跡"}
        if eid is None:
            return result
        try:
            state = self.checked_state(filename)
            result["binding_checked"] = state is not None
            data = self._get_entity(eid) if data is None else data
            uploads = self.client.list_uploads(self.entity, eid) if uploads is None else uploads
            result.update(data=data, uploads=uploads)
            hp = self._remote_hash_path(filename)
            remote_known = bool(state or hp.exists())
            remote_changed = (state["remote"] != self._remote_signature(data, uploads)) if state else (
                hp.read_text().strip() != _compute_hash(data.get("body") or "") if hp.exists() else False)
            local_known = bool(state or self._hash_path(filename).exists())
            local_changed = (self._has_changed(filename, body) or self._assets_changed(filename, body)
                             or self._has_meta_changed(filename, path.stem, self.target.category, self.target.tags)
                             or self._links_pending(filename))
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
            if local_exists and has_conflict_markers(body):
                result["state"] = "競合マーカーあり"
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            result.update(state="リモート削除" if status == 404 else "確認失敗",
                          error=_error_text(self.client, exc))
        return result

    def is_displaced_path(self, path):
        return any(part.lower().startswith(DISPLACED_PREFIX) for part in path.relative_to(self.docs_dir).parts[:-1])

    def _document_files(self):
        for path in self.docs_dir.glob(self.target.pattern):
            if not self.is_displaced_path(path) and path.is_file():
                yield path

    def file_path(self, filename):
        safe_path(self.docs_dir, filename)
        matches = [p for p in self._document_files() if p.name == filename]
        if len(matches) > 1:
            raise ValueError(f"同名ファイルが複数あります: {filename}")
        return matches[0] if matches else self.docs_dir / filename

    def collect_files(self):
        excluded = self._load_excluded()
        files = sorted(f for f in self._document_files() if f.name not in excluded)
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

    def _receipt_path(self, filename, *, base_url=None):
        if base_url is None:
            base_url = self.client.base_url
        identity = f"{base_url}|{self.entity}|{self.hash_dir}|{filename}"
        key = hashlib.sha256(identity.encode()).hexdigest()
        return self.project_root / ".elab-sync-operations" / f"{key}.json"

    def _pending(self):
        path = self.hash_dir / "pending.json"
        pending = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for item in pending.values():
            if item.get("guard") is not None:
                item["guard"] = _normalize_metadata_signature(item["guard"])
        return pending

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

    def _detect_renames(self, mapping, md_files, entity_label, *, dry_run=False):
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
        if dry_run:
            for old, new_name in pairs:
                mapping[new_name] = mapping.pop(old)
            return mapping
        # No remote changes here; title updates use the normal conflict checks.
        with local_transaction(self.project_root, [self.hash_dir], "自動リネームの紐付け変更"):
            for old, new_name in pairs:
                self.move_tracking(old, new_name, mapping)
                progress(f"  リネーム検出: {old} → {new_name}")
        return mapping

    def _check_remote_conflict(self, filename, eid):
        result = self.inspect(filename, eid)
        if result["state"] in ("競合", "取得待ち", "基準情報なし", "リモート削除", "確認失敗"):
            raise ConflictError(f"{filename}: {result['state']}。esync diff で確認し、pull または --force を選択してください")

    def dry_run(self, only=None, prune_attachments=False):
        """添付整理指定時はリネーム・未完了 ID をメモリ内で補い、追跡記事の添付を読む。
        attachments_dir 未設定なら prune_candidates は返さない。件数や本文を読めないときも各文書の error に残す。
        """
        mapping = self._load_mapping(migrate=False)
        files = self.collect_files()
        if prune_attachments:
            for name, item in self._pending().items():
                if item.get("eid") and name not in mapping:
                    mapping[name] = item["eid"]
            mapping = self._detect_renames(mapping, files, self.entity, dry_run=True)
        directory = (self.project_root / self.target.attachments_dir
                     if prune_attachments and self.target.attachments_dir else None)
        local_names = {p.name for p in directory.iterdir() if p.is_file()} if directory and directory.is_dir() else set()
        article_links = self.link_targets(mapping) if directory and directory.is_dir() else None
        results = []
        for f in files:
            if only is not None and f.name not in only:
                continue
            doc = {"filename": f.name, "title": f.stem, "entity_id": mapping.get(f.name)}
            results.append(doc)
            try:
                body = f.read_text(encoding="utf-8").strip()
                doc.update(images=_count_local_images(body), videos=_count_local_videos(body),
                           file_links=_count_local_file_links(body), changed=self._has_changed(f.name, body) or self._assets_changed(f.name, body))
                if directory:
                    uploads = self.client.list_uploads(self.entity, doc["entity_id"]) if directory.is_dir() and doc["entity_id"] else []
                    if article_links is not None:
                        body = _rewrite_local_links(body, self.entity, self.client.base_url, mapping,
                                                    source=f, links=article_links)
                    candidates = _prune_candidates(uploads, local_names, self.target.attachments_pattern, body, self.client.base_url)
                    doc["prune_candidates"] = [{"id": u["id"], "name": u["real_name"]} for u in candidates]
            except Exception as exc:
                doc["error"] = _error_text(self.client, exc)
        return results

    def _resolve_target_category(self, entities):
        """Resolve the target's category to an ID.

        Categories the API key cannot read are missing from the list API, but
        documents already in them still return category_title. Use such a
        document of this target when it identifies exactly one ID.
        """
        category = self.target.category
        ids = {int(e["category"]) for e in entities
               if e.get("category") is not None and e.get("category_title") == category}
        current = next((e for e in entities if len(ids) == 1 and e.get("category_title") == category), None)
        return self.client.resolve_category_id(self.entity, category, current=current)

    def preview_mapping(self, mapping, files):
        planned = mapping.copy()
        for name, pending in self._pending().items():
            if pending.get("eid"):
                planned.setdefault(name, pending["eid"])
        original = planned.copy()
        self._detect_renames(planned, files, self.entity, dry_run=True)
        return planned, {eid: name for name, eid in original.items() if name not in planned}

    def preview_token(self, path, eid, body, assets_hash, mapping, links):
        """Identify the selected article and local inputs in a single-document preview."""
        linked = _rewrite_local_links(body, self.entity, self.client.base_url, mapping,
                                      source=path, links=links)
        inputs = [str(path.resolve()), eid, asdict(self.target), self.client.base_url,
                  str(self.client.api_key), body, linked, assets_hash]
        return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()

    def sync(self, force=False, prune_attachments=False, only=None, *, prune_preview=None, expected_preview=None):
        """Push the target's documents, or only the file names in `only`.

        Rename detection still looks at every document, so unselected files
        are never mistaken for renamed or missing ones. prune_preview contains this target's
        dry_run(prune_attachments=True) results before writes to any selected target.
        A direct sync call computes its own preview if needed.
        """
        if self.target.attachments_dir:
            _resolve_asset_path(self.project_root, self.project_root, self.target.attachments_dir, strict=True)
        md_files = self.collect_files()
        self.updated = self.failures = self.skipped = 0
        if not md_files:
            if self._load_excluded() and self.docs_dir.is_dir():
                return 0
            raise FileNotFoundError(f"{self.docs_dir} に {self.target.pattern} に一致するファイルがありません")
        if prune_attachments and self.target.attachments_dir and prune_preview is None:
            prune_preview = self.dry_run(only=only, prune_attachments=True)
        preview_by_name = {doc["filename"]: doc for doc in prune_preview or ()}
        if expected_preview is not None:
            planned, _ = self.preview_mapping(self._load_mapping(migrate=False), md_files)
            [name] = only
            source = self.file_path(name)
            body = source.read_text(encoding="utf-8").strip()
            assets_hash = self._compute_assets_hash(body, name)
            if self.preview_token(source, planned.get(name), body, assets_hash, planned, self.link_targets(planned)) != expected_preview:
                raise ConflictError("送信先または文書の内容が変わりました。差分を開き直してください")
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
        observed_entities = []
        # Preflight all known destinations before creating any entities.
        for f in md_files:
            if only is not None and f.name not in only:
                continue
            eid = mapping.get(f.name)
            preview = preview_by_name.get(f.name, {})
            if "error" in preview:
                self.failures += 1
                progress(f"  [{f.stem}] 添付削除の事前確認に失敗: {preview['error']}", warning=True)
                continue
            result = self.inspect(f.name, eid)
            if expected_preview is not None:
                result["reviewed_assets"] = {}
                assets_hash = self._compute_assets_hash(result["body"], f.name, observed=result["reviewed_assets"])
                result["reviewed_links"] = self.link_targets(mapping)
                if self.preview_token(f, eid, result["body"], assets_hash, mapping, result["reviewed_links"]) != expected_preview:
                    raise ConflictError("送信先または文書の内容が変わりました。差分を開き直してください")
            else:
                self._compute_assets_hash(result["body"], f.name)
            result["preview_prune_ids"] = {u["id"] for u in preview.get("prune_candidates", [])
                                           if eid is not None and eid == preview.get("entity_id")}
            state = result["state"]
            if result.get("data"):
                observed_entities.append(result["data"])
            if state in ("確認失敗", "リモート削除"):
                self.failures += 1
                reason = "eLabFTW で記事が削除されています（push では作り直しません）" if state == "リモート削除" else result.get("error", "")
                progress(f"  [{f.stem}] {state}: {reason}", warning=True)
                self._print_next_actions(state, f.name, eid)
                continue
            owned = pending.get(f.name, {})
            # before/expected are the body fields before/after our PATCH. Either
            # may be observed after a lost response. guard covers metadata and
            # uploads: these must still match the last confirmed checkpoint.
            current_guard = {k: v for k, v in self._remote_signature(result.get("data", {}), result.get("uploads", [])).items() if k not in ("body", "title", "content_type")}
            # stored is the body as eLabFTW saved it after our PATCH; eLabFTW may
            # rewrite what we sent (e.g. "> " to "&gt; "), so expected alone never matches.
            receipt = owned.get("verifying_upload")
            present_ids = {u["id"] for u in result.get("uploads", [])}
            retired = set(owned.get("deleting", [])) - present_ids
            body_receipts = [r for r in owned.get("body_receipts", []) if r["id"] not in retired]
            result["body_receipts"] = body_receipts
            receipts = body_receipts + ([receipt] if receipt else [])
            if receipts and not force and owned.get("eid") == eid:
                try:
                    uploads_by_id = {u["id"]: u for u in result.get("uploads", [])}
                    for r in body_receipts:
                        entry = uploads_by_id.get(r["id"], {})
                        if not entry.get("long_name") or entry.get("storage") in (None, ""):
                            raise ConflictError(f"受領した添付 ID #{r['id']} の URL が未反映です。一覧への反映後に通常の push を再実行してください")
                    additions = [self._verify_uploaded_attachment(eid, result.get("uploads", []), r) for r in receipts]
                    recorded = {u["id"]: u for u in owned["guard"]["uploads"]}
                    for added in additions:
                        recorded.setdefault(added["id"], added)
                    expected_uploads = sorted(recorded.values(), key=lambda u: str(u["id"]))
                    expected_guard = {**owned["guard"], "uploads": expected_uploads}
                    if not self._guard_matches({**owned, "guard": expected_guard}, current_guard):
                        raise ConflictError("添付の照合待ちの間にリモート情報が変更されたため、自動では再開しません")
                    result["confirmed_upload_ids"] = {r["id"]: r for r in receipts}
                    # 再実行でも URL が確定するまで受領記録を使えるよう、ここではディスクから消さない。
                    owned = {**owned, "guard": expected_guard}
                except Exception as exc:
                    self.failures += 1
                    progress(f"  [{f.stem}] 添付検証を再開できません: {_error_text(self.client, exc)}。diffで確認してください",
                             warning=True)
                    self._print_next_actions("再開不可", f.name, eid)
                    continue
            resuming = bool(owned.get("eid") == eid and self._guard_matches(owned, current_guard) and any(
                version is not None and all(result["data"].get(k) == v for k, v in version.items())
                for version in self._resume_versions(owned)))
            if not force and owned and not resuming:
                self.failures += 1
                progress(f"  [{f.stem}] 前回の push が途中で止まった後に eLabFTW 側が変更されたため、自動では再開しません", warning=True)
                mismatch = self._resume_mismatch(owned, eid, result["data"], current_guard)
                if mismatch:
                    progress(f"    前回の同期記録と異なる項目: {', '.join(mismatch)}")
                self._print_next_actions("再開不可", f.name, eid)
                continue
            if state == "競合マーカーあり":
                self.failures += 1
                progress(f"  [{f.stem}] 競合マーカーが残っています", warning=True)
                self._print_next_actions(state, f.name, eid)
                continue
            if not force and not resuming and state in ("競合", "取得待ち", "基準情報なし"):
                self.failures += 1
                progress(f"  [{f.stem}] {state}のため送信しません", warning=True)
                self._print_next_actions(state, f.name, eid)
                continue
            if not force and not prune_attachments and not resuming and state == "最新":
                self.skipped += 1
                progress(f"  [{f.stem}] 変更なし（スキップ）")
                continue
            jobs.append((f, result, resuming))

        def resumed(f, resuming, step):
            """再開時、前回の未完了記録でその手順が必要だったか（記録がない旧形式は必要とみなす）。"""
            return resuming and (pending.get(f.name) or {}).get("needs", {}).get(step, True)

        def needs_meta(f, result, resuming):
            return (force or result.get("data") is None or resumed(f, resuming, "meta")
                    or self._has_meta_changed(f.name, f.stem, self.target.category, self.target.tags))

        def needs_links(f, result, resuming):
            # リンクの追加はタグ・カテゴリと別に判定する（リンクだけの変更・再試行でタグ・カテゴリを再適用しない）
            return (force or result.get("data") is None or resumed(f, resuming, "links") or self._links_pending(f.name))

        # Resolve the category before any body update, so an unresolvable name
        # never leaves documents half-synced (body updated, category not).
        category_id = None
        if self.target.category is not None and any(needs_meta(*job) for job in jobs):
            try:
                category_id = self._resolve_target_category(observed_entities)
            except ValueError as exc:
                progress(f"  カテゴリを解決できないため、カテゴリの設定が必要な文書の同期を中止しました: {_error_text(self.client, exc)}", warning=True)
                kept = []
                for job in jobs:
                    if needs_meta(*job):
                        self.failures += 1
                        progress(f"  [{job[0].stem}] カテゴリ未解決のためスキップ（eLabFTW は変更していません）", warning=True)
                    else:
                        kept.append(job)
                jobs = kept
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
                try:
                    result["created_data"] = self._get_entity(eid)
                except Exception as exc:
                    self.failures += 1
                    result["creation_read_failed"] = True
                    progress(f"  [{f.stem}] #{eid} を作成しましたが、本文更新前の取得に失敗しました: "
                             f"{_error_text(self.client, exc)}", warning=True)
                    continue
                progress(f"  [{f.stem}] #{eid} を新規作成しました")
        links = self.link_targets(mapping) if jobs else None
        for f, result, resuming in jobs:
            if result.get("creation_read_failed"):
                continue
            eid = result["entity_id"]
            raw_body = result["body"]
            try:
                if force and result.get("data") is not None:
                    snapshot(self.project_root, [], "強制push前のリモート本文", remote={
                        "server": server_id(self.client.base_url), "entity": self.entity, "id": eid,
                        "title": result["data"].get("title"), "body": result["data"].get("body"),
                        "content_type": result["data"].get("content_type"),
                    })
                previous = result.get("created_data") or result.get("data") or self._get_entity(eid)
                stale_uploads: list[int] = []
                uploaded = {}
                verified_body = result.get("reviewed_assets", {})
                body_receipts = list(result["body_receipts"]) if resuming else []
                def record_body_upload(receipt):
                    if not body_receipts:
                        baseline = self._remote_signature(previous, result.get("uploads", []))
                        pending[f.name] = {"eid": eid, "before": {k: previous.get(k) for k in ("body", "title", "content_type")},
                                           "guard": {k: baseline[k] for k in ("tags", "category", "uploads")},
                                           "body_receipts": body_receipts,
                                           "needs": {"meta": needs_meta(f, result, resuming),
                                                     "links": needs_links(f, result, resuming)}}
                    pending[f.name]["body_receipts"] = body_receipts
                    if not any(all(r.get(k) == v for k, v in receipt.items()) for r in body_receipts):
                        body_receipts.append(receipt)
                    self._save_pending(pending)
                used_urls = {}
                def check_download_urls(uploads):
                    available = {u["id"]: upload_url(self.client.base_url, u) for u in uploads}
                    if any(available.get(uid) != url for uid, url in used_urls.items()):
                        raise ConflictError("本文に使う添付 URL が変わりました。eLabFTW の添付一覧を確認してください")

                preferred = result.get("confirmed_upload_ids", set())
                body = _rewrite_images(raw_body, self.entity, eid, self.client, f.parent, self.project_root, strict=True, stale_out=stale_uploads, uploaded=uploaded, verified=verified_body, record=record_body_upload, preferred=preferred, used_urls=used_urls)
                body = _rewrite_videos(body, self.entity, eid, self.client, f.parent, self.project_root, strict=True, stale_out=stale_uploads, uploaded=uploaded, verified=verified_body, record=record_body_upload, preferred=preferred, used_urls=used_urls)
                body = _rewrite_file_links(body, self.entity, eid, self.client, f.parent, self.project_root, strict=True, stale_out=stale_uploads, uploaded=uploaded, verified=verified_body, record=record_body_upload, preferred=preferred, used_urls=used_urls)
                body = _rewrite_local_links(body, self.entity, self.client.base_url, mapping, source=f,
                                            links=result.get("reviewed_links", links))
                body = body if self.target.body_format == "md" else _md_to_html(body)
                expected = {"body": body, "title": f.stem, "content_type": 2 if self.target.body_format == "md" else 1}
                expected_links = _attachment_links(body, expected["content_type"]) if used_urls else {}
                if any(not expected_links[url] for url in used_urls.values()):
                    raise ConflictError("本文の添付リンクを確認できません。Markdown のリンク記法を確認してください")
                before = {key: previous.get(key) for key in expected}
                guard = {k: v for k, v in self._remote_signature(previous, self.client.list_uploads(self.entity, eid)).items() if k not in ("body", "title", "content_type")}
                # 本文のリンクを書き換える間に既存の添付が変わった場合は削除・本文更新を止める。
                initial_uploads = self._remote_signature({}, result.get("uploads", []))["uploads"]
                initial_ids = {u["id"] for u in initial_uploads}
                current_originals = [u for u in guard["uploads"] if u["id"] in initial_ids]
                current = {u["id"]: u for u in guard["uploads"]}
                for uid, (name, size, digest) in uploaded.items():
                    entry = current.get(uid)
                    if not entry or entry["real_name"] != name or int(entry["filesize"] or 0) != size:
                        raise ConflictError("送信した本文用添付の名前・サイズを確認できません")
                    stored_hash = upload_sha256(entry)
                    if not stored_hash:
                        stored_hash = self.client.upload_digest(entity_type=self.entity, entity_id=eid, upload_id=uid)
                    if stored_hash != digest:
                        raise ConflictError("送信した本文用添付の内容が一致しません")
                if stale_uploads:
                    previously_linked = _linked_article_upload_ids(result.get("uploads", []), previous.get("body"),
                                                                   previous.get("content_type"), self.client.base_url,
                                                                   self.entity, eid)
                    owned_ids = previously_linked.union(r["id"] for r in body_receipts if r.get("created") is True)
                    if resuming:
                        owned_ids.update(pending[f.name].get("cleanup_ids", []))
                    stale_uploads = [uid for uid in stale_uploads if uid not in uploaded and uid in owned_ids]
                if current_originals != initial_uploads or set(current) != initial_ids | set(uploaded) or not set(stale_uploads) <= initial_ids:
                    raise ConflictError("本文の添付を準備している間にリモート添付が変更されました。diffで確認してください")
                meta_changed = needs_meta(f, result, resuming)
                links_changed = needs_links(f, result, resuming)
                pending[f.name] = {"eid": eid, "expected": expected, "before": before, "guard": guard,
                                   "needs": {"meta": meta_changed, "links": links_changed}}
                if stale_uploads:
                    pending[f.name]["cleanup_ids"] = stale_uploads.copy()
                if body_receipts:
                    pending[f.name]["body_receipts"] = body_receipts
                self._save_pending(pending)
                # 添付ハッシュを確認する間に本文・メタデータ・添付が変わっていないか再読する。
                planned_prune = set()
                prune_body = body
                if prune_attachments and self.target.attachments_dir:
                    directory = self.project_root / self.target.attachments_dir
                    if directory.is_dir():
                        local_links = _rewrite_local_links(raw_body, self.entity, self.client.base_url, mapping, source=f, links=links)
                        prune_body = local_links + "\n\n" + body
                        candidates = _prune_candidates(initial_uploads, {p.name for p in directory.iterdir() if p.is_file()},
                                                       self.target.attachments_pattern, prune_body,
                                                       self.client.base_url)
                        planned_prune = result["preview_prune_ids"].intersection(u["id"] for u in candidates)
                if stale_uploads:
                    _referenced_upload_ids(guard["uploads"], body, self.client.base_url)
                latest_uploads = self.client.list_uploads(self.entity, eid)
                check_download_urls(latest_uploads)
                latest = self._get_entity(eid)
                latest_signature = self._remote_signature(latest, latest_uploads)
                if any(latest.get(k) != v for k, v in before.items()) or any(latest_signature[k] != v for k, v in guard.items()):
                    raise ConflictError("本文更新前にリモートが変更されました。diffで確認してください")
                self._update_entity(eid, **expected)
                def checkpoint(expected_changes=None):
                    """Confirm the predicted result, never adopt an unknown update.

                    expected_changes contains only values our completed operation
                    was intended to produce (tag union or resolved category ID).
                    All other guard fields must remain exactly unchanged.
                    """
                    observed = self._get_entity(eid)
                    listed = self.client.list_uploads(self.entity, eid)
                    check_download_urls(listed)
                    if used_urls:
                        saved_body = observed.get("body") or ""
                        saved_type = observed.get("content_type")
                        saved_links = _attachment_links(saved_body, saved_type)
                        if str(saved_type) == "2" and saved_body != body and _html.unescape(saved_body) == body:
                            saved_links = expected_links
                        if any(saved_links[url] < count for url, count in expected_links.items() if url in used_urls.values()):
                            raise ConflictError("保存された本文の添付リンクを確認できません。本文と添付一覧を確認してください")
                    signature = self._remote_signature(observed, listed)
                    observed_guard = {k: v for k, v in signature.items() if k not in ("body", "title", "content_type")}
                    expected_guard = {**pending[f.name]["guard"], **(expected_changes or {})}
                    if observed_guard != expected_guard:
                        raise ConflictError("同期処理中にリモートのメタデータ・添付が変更されました。diffで確認してください")
                    pending[f.name]["guard"] = observed_guard
                    self._save_pending(pending)
                    return observed, signature["uploads"]

                observed, _ = checkpoint()
                pending[f.name]["stored"] = {key: observed.get(key) for key in expected}
                self._save_pending(pending)
                dropped = _dropped_angle_fragments(body, observed.get("body")) if self.target.body_format == "md" else []
                tags_ok = _sync_tags(self.client, self.entity, eid, self.target.tags) if meta_changed else True
                if not tags_ok:
                    raise RuntimeError("本文更新後にタグ同期が失敗しました。リモートを確認して再実行してください")
                if meta_changed:
                    observed, _ = checkpoint({"tags": sorted(set(pending[f.name]["guard"]["tags"]) | set(self.target.tags))})
                category_ok = _sync_category(self.client, self.entity, eid, category_id, current=observed) if meta_changed else True
                if not category_ok:
                    raise RuntimeError("本文更新後にカテゴリ同期が失敗しました。リモートを確認して再実行してください")
                if meta_changed:
                    checkpoint({"category": _category_value(category_id)} if category_id is not None else None)
                links_ok = _sync_links(self.client, self.entity, eid, self.target.links) if links_changed else True
                if not links_ok:
                    raise RuntimeError("本文更新後にリンク同期が失敗しました。リモートを確認して再実行してください")
                prune_ids = set()
                if planned_prune and directory.is_dir():
                    local_names = {p.name for p in directory.iterdir() if p.is_file()}
                    candidates = _prune_candidates(self.client.list_uploads(self.entity, eid), local_names,
                                                   self.target.attachments_pattern, prune_body, self.client.base_url)
                    prune_ids = planned_prune.intersection(u["id"] for u in candidates)
                stale_uploads.extend(sorted(prune_ids))
                deleted = self._delete_stale_uploads(eid, stale_uploads, pending, f.name, prune_ids, check_download_urls) if stale_uploads else set()
                if "deleting" in pending[f.name]:
                    checkpoint({"uploads": [u for u in pending[f.name]["guard"]["uploads"] if u.get("id") not in deleted]})
                    if body_receipts:
                        pending[f.name]["body_receipts"] = [r for r in body_receipts if r["id"] not in deleted]
                    pending[f.name].pop("deleting")
                    self._save_pending(pending)
                data = self._get_entity(eid)
                uploads = self.client.list_uploads(self.entity, eid)
                check_download_urls(uploads)
                actual = self._remote_signature(data, uploads)
                if any(data.get(k) != v for k, v in pending[f.name]["stored"].items()):
                    raise ConflictError("完了確認時にリモート本文が変更されました")
                if any(actual[k] != pending[f.name]["guard"][k] for k in ("category", "tags", "uploads")):
                    raise ConflictError("完了確認時にリモートのカテゴリ・タグ・添付が期待値と異なります")
                base = self.remote_base(data, uploads, eid, mapping, links, f)
                # When eLabFTW dropped <...>, record what it kept as the synced local
                # body: the file stays "送信待ち", and pull merges instead of
                # overwriting the original with the lossy remote body.
                applied = self.applied_links(f.name)
                if links_ok and links_changed:
                    applied = {t: sorted(set(applied.get(t, [])) | set(ids))
                               for t, ids in {**applied, **self.target.links}.items()}
                self._save_baseline(f.name, base if dropped else raw_body, data, uploads, base=base, links=applied,
                                    assets_hash=self._compute_assets_hash(raw_body, f.name, body_evidence=verified_body))
                pending.pop(f.name, None)
                self._save_pending(pending)
                sync_log.record(self.project_root / sync_log.DEFAULT_LOG_PATH, action="push", target=f.stem,
                                entity=self.entity, entity_id=eid, files=[f.name])
                self.updated += 1
                progress(f"  [{f.stem}] #{eid} を更新しました")
                if dropped:
                    self.failures += 1
                    shown = ", ".join(dropped[:5]) + (f" ほか{len(dropped) - 5}件" if len(dropped) > 5 else "")
                    progress(f"  [{f.stem}] 警告: eLabFTW が本文の <…> を削除しました: {shown}", warning=True)
                    progress("    ローカルの原稿はそのままですが、eLabFTW 上の本文からは失われています。"
                          "解消するまで、この文書は「送信待ち」のままになります。表記を見直して再度 push してください", warning=True)
            except Exception as exc:
                self.failures += 1
                progress(f"  [{f.stem}] 同期失敗: {_error_text(self.client, exc)}", warning=True)
        return self.updated
