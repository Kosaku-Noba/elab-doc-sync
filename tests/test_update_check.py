"""新バージョン通知のテスト。"""

import json
from unittest.mock import MagicMock

import pytest

from elab_doc_sync import update_check as uc


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv(uc.DISABLE_ENV, raising=False)
    return tmp_path


def test_is_newer():
    assert uc.is_newer("1.2.0", "1.1.2")
    assert uc.is_newer("1.10.0", "1.9.9")
    assert not uc.is_newer("1.1.2", "1.1.2")
    assert not uc.is_newer("1.1.1", "1.1.2")
    assert not uc.is_newer("garbage", "1.1.2")
    assert not uc.is_newer("1.2.0", "unknown")


def test_fetch_latest_version(monkeypatch):
    resp = MagicMock(text='[project]\nname = "x"\nversion = "1.3.0"\n')
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: resp)
    assert uc.fetch_latest_version() == "1.3.0"


def test_fetch_latest_version_network_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(uc.requests, "get", boom)
    assert uc.fetch_latest_version() is None


def test_get_latest_version_uses_fresh_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(uc, "fetch_latest_version", lambda: calls.append(1) or "2.0.0")
    assert uc.get_latest_version(now=1000) == "2.0.0"
    assert uc.get_latest_version(now=1000 + uc.CHECK_INTERVAL_SEC - 1) == "2.0.0"
    assert len(calls) == 1
    assert uc.get_latest_version(now=1000 + uc.CHECK_INTERVAL_SEC) == "2.0.0"
    assert len(calls) == 2


def test_failed_fetch_keeps_old_value_and_throttles(monkeypatch):
    uc._save_cache(uc._cache_path(), {"checked_at": 0, "latest": "1.5.0"})
    calls = []
    monkeypatch.setattr(uc, "fetch_latest_version", lambda: calls.append(1))
    assert uc.get_latest_version(now=uc.CHECK_INTERVAL_SEC + 1) == "1.5.0"
    uc.get_latest_version(now=uc.CHECK_INTERVAL_SEC + 2)
    assert len(calls) == 1
    assert json.loads(uc._cache_path().read_text())["latest"] == "1.5.0"


def _tty(monkeypatch):
    monkeypatch.setattr(uc.sys.stderr, "isatty", lambda: True, raising=False)


def test_notify_prints_when_newer(monkeypatch, capsys):
    _tty(monkeypatch)
    monkeypatch.setattr(uc, "get_latest_version", lambda: "9.0.0")
    uc.notify_if_update_available("1.1.2", "push")
    err = capsys.readouterr().err
    assert "1.1.2 → 9.0.0" in err and "esync update" in err


def test_notify_silent_cases(monkeypatch, capsys):
    monkeypatch.setattr(uc, "get_latest_version", lambda: "9.0.0")
    uc.notify_if_update_available("1.1.2", "push")  # 非 TTY
    _tty(monkeypatch)
    uc.notify_if_update_available("1.1.2", "update")
    uc.notify_if_update_available("unknown", "push")
    monkeypatch.setattr(uc, "get_latest_version", lambda: "1.1.2")
    uc.notify_if_update_available("1.1.2", "push")
    monkeypatch.setattr(uc, "get_latest_version", lambda: "9.0.0")
    monkeypatch.setenv(uc.DISABLE_ENV, "1")
    uc.notify_if_update_available("1.1.2", "push")
    assert capsys.readouterr().err == ""
