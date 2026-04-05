"""Diff-based docs sync to eLabFTW items/experiments with image upload."""

import hashlib
import json
import re
import markdown
from pathlib import Path

from .client import ELabFTWClient
from .config import TargetConfig
from . import sync_log

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
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


def _rewrite_images(body: str, entity: str, entity_id: int, client: ELabFTWClient, docs_dir: Path, project_root: Path) -> str:
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
        print(f"    画像をアップロード中: {img_path.name}")
        result = client.upload_file(entity, entity_id, str(img_path))
        if result.get("url"):
            print(f"    ✓ {img_path.name}")
            return f"![{alt}]({result['url']})"
        print(f"    ✗ アップロード失敗: {img_path.name}")
        return m.group(0)
    return IMAGE_RE.sub(replace_match, body)


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
        entity_label = "実験ノート" if self.entity == "experiments" else "アイテム"

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
        html = _md_to_html(body)
        self._update_entity(item_id, body=html, title=self.target.title)
        self.save_hash(raw_body)

        # push 後のリモート body ハッシュを保存（競合検出用）
        try:
            remote_data = self._get_entity(item_id)
            self.save_remote_hash(remote_data.get("body", "") or "")
        except Exception:
            pass

        print(f"  [{self.target.title}] {entity_label} #{item_id} を更新しました")

        log_path = self.project_root / sync_log.DEFAULT_LOG_PATH
        files = [f.name for f in self.collect_files()]
        sync_log.record(log_path, action="push", target=self.target.title,
                        entity=self.entity, entity_id=item_id, files=files)

        return True


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
        entity_label = "実験ノート" if self.entity == "experiments" else "アイテム"
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
            html = _md_to_html(body)
            self._update_entity(eid, body=html, title=title)
            self._save_hash(f.name, raw_body)

            # push 後のリモート body ハッシュを保存（競合検出用）
            try:
                remote_data = self._get_entity(eid)
                self._save_remote_hash(f.name, remote_data.get("body", "") or "")
            except Exception:
                pass

            print(f"  [{title}] {entity_label} #{eid} を更新しました")

            log_path = self.project_root / sync_log.DEFAULT_LOG_PATH
            sync_log.record(log_path, action="push", target=title,
                            entity=self.entity, entity_id=eid, files=[f.name])

            updated += 1

        return updated
