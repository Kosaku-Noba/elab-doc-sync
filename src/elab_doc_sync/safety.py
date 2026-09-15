"""Atomic local storage, process locking, and recoverable local snapshots."""

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

BACKUPS = ".elab-sync-backups"
RECOVERY = ".elab-sync-recovery.json"


def atomic_write(path: Path, data: str | bytes, mode: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"シンボリックリンクには書き込めません: {path}")
    if mode is None:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data.encode("utf-8") if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, data) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def safe_path(root: Path, relative: str) -> Path:
    """Reject traversal and symlinks, including symlinked parent directories."""
    root = root.resolve()
    part = Path(relative)
    if part.is_absolute() or not part.parts or any(p in ("..", ".git") for p in part.parts) or "\\" in relative:
        raise ValueError(f"安全でないパスです: {relative}")
    dest = root / part
    for p in (dest, *dest.parents):
        if p == root:
            break
        if p.is_symlink():
            raise ValueError(f"シンボリックリンクは対象外です: {p}")
    if not dest.resolve().is_relative_to(root) or dest == root:
        raise ValueError(f"対象ディレクトリ外のパスです: {relative}")
    return dest


@contextmanager
def project_lock(root: Path):
    """OS-owned locks release automatically even when the process crashes."""
    root = root.resolve()
    lock_dir = Path(tempfile.gettempdir()) / ("elab-doc-sync-locks-" + str(getattr(os, "getuid", lambda: "user")()))
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    lock_name = hashlib.sha256(str(root).encode()).hexdigest() + ".lock"
    with (lock_dir / lock_name).open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("別のesyncが実行中です。終了後に再実行してください") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def project_command(fn):
    @wraps(fn)
    def wrapped(args):
        if getattr(args, "dry_run", False):
            return fn(args)
        root = Path(args.config).resolve().parent
        with project_lock(root):
            if fn.__name__ != "cmd_restore" and (root / RECOVERY).exists():
                pending = json.loads((root / RECOVERY).read_text(encoding="utf-8"))
                raise RuntimeError(f"前回のローカル変更が未完了です。esync restore {pending['backup']} を実行してください")
            return fn(args)
    return wrapped


def snapshot(root: Path, paths: list[Path], reason: str, remote: dict | None = None) -> str:
    root = root.resolve()
    selected = []
    for path in sorted(set(Path(p).absolute() for p in paths), key=lambda p: len(p.parts)):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"バックアップ対象はプロジェクト内に配置してください: {path}") from exc
        path = safe_path(root, relative)
        if relative.split("/")[0] in (BACKUPS, ".elab-sync.lock", RECOVERY, ".elab-sync-operations"):
            raise ValueError(f"バックアップ自身は対象にできません: {relative}")
        if not any(path.is_relative_to(parent) for parent in selected):
            selected.append(path)
    backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    destination = root / BACKUPS / backup_id
    destination.mkdir(parents=True, mode=0o700)
    manifest = {"version": 1, "id": backup_id, "reason": reason, "roots": [], "files": {}, "directories": [], "remote": remote}
    try:
        for path in selected:
            rel = path.relative_to(root).as_posix()
            kind = "directory" if path.is_dir() else "file" if path.is_file() else "absent"
            manifest["roots"].append({"path": rel, "kind": kind})
            entries = [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]
            for entry in entries:
                name = entry.relative_to(root).as_posix()
                safe_path(root, name)
                if entry.is_dir():
                    manifest["directories"].append(name)
                elif entry.is_file():
                    data = entry.read_bytes()
                    digest = hashlib.sha256(data).hexdigest()
                    atomic_write(destination / digest, data)
                    manifest["files"][name] = {"sha256": digest, "mode": entry.stat().st_mode & 0o777}
        write_json(destination / "manifest.json", manifest)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return backup_id


def read_snapshot(root: Path, backup_id: str) -> dict:
    if Path(backup_id).name != backup_id or backup_id in ("", ".", ".."):
        raise ValueError("バックアップIDが不正です")
    base = safe_path(root, f"{BACKUPS}/{backup_id}")
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("未対応のバックアップ形式です")
    roots = [safe_path(root, r["path"]) for r in manifest["roots"]]
    for path in roots:
        if path.relative_to(root.resolve()).parts[0] in (BACKUPS, RECOVERY, ".elab-sync.lock", ".elab-sync-operations"):
            raise ValueError("復元対象が不正です")
    for name in [*manifest["files"], *manifest["directories"]]:
        path = safe_path(root, name)
        if not any(path.is_relative_to(r) for r in roots):
            raise ValueError("復元対象がバックアップ範囲外です")
    for item in manifest["files"].values():
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("バックアップのハッシュが不正です")
        if hashlib.sha256((base / digest).read_bytes()).hexdigest() != digest:
            raise ValueError("バックアップが破損しています")
    return manifest


@contextmanager
def local_transaction(root: Path, paths: list[Path], reason: str):
    root = root.resolve()
    backup_id = snapshot(root, paths, reason)
    write_json(root / RECOVERY, {"backup": backup_id})
    print(f"  バックアップ: {backup_id}")
    try:
        yield backup_id
    except BaseException:
        print(f"  未完了の変更があります。esync restore {backup_id} で復旧してください")
        raise
    else:
        (root / RECOVERY).unlink()


def restore(root: Path, backup_id: str, dry_run: bool = False) -> None:
    root = root.resolve()
    pending_path = root / RECOVERY
    if pending_path.exists() and json.loads(pending_path.read_text(encoding="utf-8"))["backup"] != backup_id:
        raise ValueError("まず未完了の変更に対応するバックアップをrestoreしてください")
    manifest = read_snapshot(root, backup_id)
    paths = [safe_path(root, entry["path"]) for entry in manifest["roots"]]
    export_path = root / BACKUPS / f"{backup_id}-remote.json"
    for entry in manifest["roots"]:
        print(f"  復元対象: {entry['path']} ({entry['kind']})")
    if manifest.get("remote") is not None:
        print(f"  リモート退避データの取り出し: {export_path}")
    if dry_run:
        return
    # Preserve everything currently present before restoring an earlier state.
    with local_transaction(root, paths, f"restore:{backup_id}"):
        for path in paths:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        for name in manifest["directories"]:
            safe_path(root, name).mkdir(parents=True, exist_ok=True)
        base = root / BACKUPS / backup_id
        for name, item in manifest["files"].items():
            atomic_write(safe_path(root, name), (base / item["sha256"]).read_bytes(), item["mode"])
        if manifest.get("remote") is not None:
            write_json(export_path, manifest["remote"])
