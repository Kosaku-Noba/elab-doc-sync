"""新バージョンの有無を確認し、あれば stderr で知らせる。

コマンド自体の成否（eLabFTW への接続失敗など）とは無関係に通知する。
通知しないのは次の場合: GitHub 上のバージョンを読めなかったとき、すでに最新のとき、
`ELAB_SYNC_NO_UPDATE_CHECK` 設定時、`update` コマンド実行時、stderr が端末でないとき、
現在のバージョンが不明なとき。

1 日 1 回だけ GitHub 上の pyproject.toml のバージョンを取得し、結果をキャッシュする。
ネットワークエラー等はすべて黙って無視する（本来のコマンドを妨げない）。
`ELAB_SYNC_NO_UPDATE_CHECK=1` で無効化できる。

`ELAB_SYNC_AUTO_UPDATE=1` を設定していると、マイナー・パッチ更新に限り自動で更新する。
更新は実行中の esync とは別プロセスで切り離して起動する（Windows は実行中の exe を
上書きできないため）。メジャー更新は通知のみ。
更新対象は検出したバージョンのタグ（`v<version>`）に固定する。タグがまだ無いときは自動更新しない。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

VERSION_URL = "https://raw.githubusercontent.com/Kosaku-Noba/elab-doc-sync/main/pyproject.toml"
CHECK_INTERVAL_SEC = 24 * 60 * 60
FETCH_TIMEOUT_SEC = 2
DISABLE_ENV = "ELAB_SYNC_NO_UPDATE_CHECK"
AUTO_UPDATE_ENV = "ELAB_SYNC_AUTO_UPDATE"
REPO_URL = "git+https://github.com/Kosaku-Noba/elab-doc-sync.git"
TAG_API_URL = "https://api.github.com/repos/Kosaku-Noba/elab-doc-sync/git/ref/tags/v{version}"
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


def is_major_update(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a[0] > b[0]


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
    latest = fetch_latest_version()
    # 取得失敗でも checked_at を更新し、オフライン時に毎回待たされないようにする。
    # 失敗時は古い値を使い回さず None（通知しない）にする
    _save_cache(path, {**cache, "checked_at": now, "latest": latest})
    return latest


def _auto_update_enabled() -> bool:
    return os.environ.get(AUTO_UPDATE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def tag_exists(version: str) -> bool:
    """検出したバージョンのタグ（v<version>）が公開されているか。"""
    try:
        return requests.get(TAG_API_URL.format(version=version), timeout=FETCH_TIMEOUT_SEC).status_code == 200
    except Exception:
        return False


def start_background_update(version: str) -> bool:
    """`uv tool install --force` を切り離したプロセスで起動する。起動できたら True。"""
    uv = shutil.which("uv")
    if not uv:
        return False
    target = f"{REPO_URL}@v{version}"
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        # 親（実行中の esync.exe）が終了してから上書きできるよう、数秒待ってから実行する
        cmd = f'ping -n 4 127.0.0.1 > nul & "{uv}" tool install --force {target}'
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        args = f"cmd /c {cmd}"  # 文字列のまま渡す（list だと内側の引用符が cmd に解釈されない）
    else:
        kwargs["start_new_session"] = True
        args = ["sh", "-c", f'sleep 3; exec "$0" tool install --force "$1"', uv, target]
    try:
        subprocess.Popen(args, **kwargs)
        return True
    except Exception:
        return False


def _try_auto_update(latest: str, current: str) -> bool:
    """自動更新を起動した場合 True。同じバージョンへは 1 度しか試さない。"""
    if not _auto_update_enabled() or is_major_update(latest, current):
        return False
    path = _cache_path()
    cache = _load_cache(path)
    if cache.get("auto_update_attempted") == latest:
        return False
    # タグ未公開は 1 日 1 回だけ再確認する（毎回 API を叩かない）
    now = time.time()
    checked = cache.get("tag_checked")
    if isinstance(checked, dict) and checked.get("version") == latest             and 0 <= now - checked.get("at", 0) < CHECK_INTERVAL_SEC:
        return False
    if not tag_exists(latest):
        _save_cache(path, {**cache, "tag_checked": {"version": latest, "at": now}})
        return False
    # 起動の成否に関わらず記録し、失敗しても毎回再試行しない
    _save_cache(path, {**cache, "auto_update_attempted": latest})
    return start_background_update(latest)


def notify_if_update_available(current: str, command=None) -> None:
    """新バージョンがあれば stderr に案内を出し、設定されていれば自動更新を起動する。"""
    if os.environ.get(DISABLE_ENV) or command == "update":
        return
    if not sys.stderr.isatty() or parse_version(current) is None:
        return
    try:
        latest = get_latest_version()
        if not (latest and is_newer(latest, current)):
            return
        if _try_auto_update(latest, current):
            print(
                f"\n💡 新しいバージョンがあります: {current} → {latest}\n"
                f"   自動更新をバックグラウンドで開始しました（反映は次回の実行から）",
                file=sys.stderr,
            )
            return
        hint = ""
        if _auto_update_enabled() and is_major_update(latest, current):
            hint = "（メジャー更新のため自動更新しません）"
        print(
            f"\n💡 新しいバージョンがあります: {current} → {latest}{hint}\n"
            f"   `esync update` で更新できます（通知を止めるには {DISABLE_ENV}=1）",
            file=sys.stderr,
        )
    except Exception:
        pass
