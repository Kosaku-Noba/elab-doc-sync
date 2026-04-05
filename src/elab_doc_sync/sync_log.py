"""Sync log: record and display push/pull history in JSONL format."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
DEFAULT_LOG_PATH = ".elab-sync-ids/sync-log.jsonl"


def _now_iso() -> str:
    return datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S%z")


def record(log_path: Path, *, action: str, target: str, entity: str,
           entity_id: int | None, files: list[str] | None = None,
           user: str | None = None) -> None:
    """Append one log entry. Best-effort: never raises."""
    try:
        entry = {
            "timestamp": _now_iso(),
            "action": action,
            "target": target,
            "entity": entity,
            "entity_id": entity_id,
            "files": files or [],
        }
        if user:
            entry["user"] = user
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as f:
            f.write((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
    except Exception:
        pass


def read_log(log_path: Path, limit: int = 20) -> list[dict]:
    """Read last N valid entries from log file."""
    if not log_path.exists():
        return []
    try:
        raw = log_path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.strip().splitlines()
    entries = []
    for line in reversed(lines):
        try:
            entries.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
        if len(entries) >= limit:
            break
    entries.reverse()
    return entries


def format_log(entries: list[dict]) -> str:
    """Format log entries for display."""
    if not entries:
        return "同期ログはまだありません"
    lines = []
    for e in entries:
        ts = e.get("timestamp", "?")
        action = e.get("action", "?")
        target = e.get("target", "?")
        eid = e.get("entity_id", "?")
        entity = e.get("entity", "?")
        files = e.get("files", [])
        file_str = f" ({len(files)}件)" if files else ""
        entity_label = "実験ノート" if entity == "experiments" else "リソース"
        lines.append(f"  {ts}  {action:<5} [{target}] {entity_label} #{eid}{file_str}")
    return "\n".join(lines)
