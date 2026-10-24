"""新バージョンの有無を確認し、あれば stderr で知らせる。

1 日 1 回だけ GitHub 上の pyproject.toml のバージョンを取得し、結果をキャッシュする。
ネットワークエラー等はすべて黙って無視する（本来のコマンドを妨げない）。
`ELAB_SYNC_NO_UPDATE_CHECK=1` で無効化できる。
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

VERSION_URL = "https://raw.githubusercontent.com/Kosaku-Noba/elab-doc-sync/main/pyproject.toml"
CHECK_INTERVAL_SEC = 24 * 60 * 60
FETCH_TIMEOUT_SEC = 2
DISABLE_ENV = "ELAB_SYNC_NO_UPDATE_CHECK"
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "elab-doc-sync" / "update-check.json"


def parse_version(text: str):
    """'1.2.3' → (1, 2, 3)。解釈できなければ None。"""
    m = re.match(r"^v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def fetch_latest_version():
    """GitHub の pyproject.toml から最新バージョンを取得する。失敗時は None。"""
    try:
        resp = requests.get(VERSION_URL, timeout=FETCH_TIMEOUT_SEC)
        resp.raise_for_status()
        m = _VERSION_RE.search(resp.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _load_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def get_latest_version(now=None):
    """キャッシュが新しければそれを、古ければ取得し直して最新バージョンを返す。"""
    now = time.time() if now is None else now
    path = _cache_path()
    cache = _load_cache(path)
    checked_at = cache.get("checked_at")
    if isinstance(checked_at, (int, float)) and 0 <= now - checked_at < CHECK_INTERVAL_SEC:
        return cache.get("latest")
    latest = fetch_latest_version() or cache.get("latest")
    # 取得失敗でも checked_at を更新し、オフライン時に毎回待たされないようにする
    _save_cache(path, {"checked_at": now, "latest": latest})
    return latest


def notify_if_update_available(current: str, command=None) -> None:
    """新バージョンがあれば stderr に案内を出す。"""
    if os.environ.get(DISABLE_ENV) or command == "update":
        return
    if not sys.stderr.isatty() or parse_version(current) is None:
        return
    try:
        latest = get_latest_version()
        if latest and is_newer(latest, current):
            print(
                f"\n💡 新しいバージョンがあります: {current} → {latest}\n"
                f"   `esync update` で更新できます（通知を止めるには {DISABLE_ENV}=1）",
                file=sys.stderr,
            )
    except Exception:
        pass
