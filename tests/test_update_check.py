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


def test_failed_fetch_returns_none_and_throttles(monkeypatch):
    uc._save_cache(uc._cache_path(), {"checked_at": 0, "latest": "1.5.0"})
    calls = []
    monkeypatch.setattr(uc, "fetch_latest_version", lambda: calls.append(1))
    assert uc.get_latest_version(now=uc.CHECK_INTERVAL_SEC + 1) is None
    assert uc.get_latest_version(now=uc.CHECK_INTERVAL_SEC + 2) is None
    assert len(calls) == 1
    assert json.loads(uc._cache_path().read_text())["latest"] is None


def _tty(monkeypatch):
    monkeypatch.setattr(uc.sys.stderr, "isatty", lambda: True, raising=False)


def test_notify_prints_when_newer(monkeypatch, capsys):
    _tty(monkeypatch)
    monkeypatch.setattr(uc, "get_latest_version", lambda: "9.0.0")
    uc.notify_if_update_available("1.1.2", "push")
    err = capsys.readouterr().err
    assert "1.1.2 → 9.0.0" in err and "esync update" in err


@pytest.mark.parametrize("exc", [SystemExit(1), ValueError("bad"), RuntimeError("eLabFTW down")])
def test_main_notifies_even_when_command_fails(monkeypatch, capsys, exc):
    from elab_doc_sync import cli
    _tty(monkeypatch)
    monkeypatch.setattr(uc, "get_latest_version", lambda: "9.0.0")
    monkeypatch.setattr(cli, "cmd_status", lambda args: (_ for _ in ()).throw(exc))
    monkeypatch.setattr(uc.sys, "argv", ["esync", "status"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "→ 9.0.0" in capsys.readouterr().err


def test_main_notifies_on_nonzero_return(monkeypatch, capsys):
    from elab_doc_sync import cli
    _tty(monkeypatch)
    monkeypatch.setattr(uc, "get_latest_version", lambda: "9.0.0")
    monkeypatch.setattr(cli, "cmd_status", lambda args: 1)
    monkeypatch.setattr(uc.sys, "argv", ["esync", "status"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "→ 9.0.0" in capsys.readouterr().err


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


def test_is_major_update():
    assert uc.is_major_update("2.0.0", "1.9.9")
    assert not uc.is_major_update("1.2.0", "1.1.2")
    assert not uc.is_major_update("x", "1.0.0")


@pytest.fixture
def popen(monkeypatch):
    calls = []
    monkeypatch.setattr(uc.shutil, "which", lambda name: "/bin/uv")
    monkeypatch.setattr(uc.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    return calls


def test_auto_update_runs_detached_for_minor(monkeypatch, capsys, popen):
    _tty(monkeypatch)
    monkeypatch.setenv(uc.AUTO_UPDATE_ENV, "1")
    monkeypatch.setattr(uc, "get_latest_version", lambda: "1.2.0")
    uc.notify_if_update_available("1.1.2", "push")
    assert len(popen) == 1
    args = popen[0][0]
    assert uc.REPO_URL in (args if isinstance(args, str) else " ".join(args))
    assert "自動更新をバックグラウンドで開始" in capsys.readouterr().err
    # 同じバージョンへは再度起動しない（通知だけ出る）
    uc.notify_if_update_available("1.1.2", "push")
    assert len(popen) == 1
    assert "esync update" in capsys.readouterr().err


def test_auto_update_skipped_for_major(monkeypatch, capsys, popen):
    _tty(monkeypatch)
    monkeypatch.setenv(uc.AUTO_UPDATE_ENV, "1")
    monkeypatch.setattr(uc, "get_latest_version", lambda: "2.0.0")
    uc.notify_if_update_available("1.1.2", "push")
    assert popen == []
    err = capsys.readouterr().err
    assert "メジャー更新のため自動更新しません" in err and "esync update" in err


def test_auto_update_off_by_default(monkeypatch, popen):
    _tty(monkeypatch)
    monkeypatch.setattr(uc, "get_latest_version", lambda: "1.2.0")
    uc.notify_if_update_available("1.1.2", "push")
    assert popen == []


def test_auto_update_without_uv_falls_back_to_notice(monkeypatch, capsys):
    _tty(monkeypatch)
    monkeypatch.setenv(uc.AUTO_UPDATE_ENV, "1")
    monkeypatch.setattr(uc.shutil, "which", lambda name: None)
    monkeypatch.setattr(uc, "get_latest_version", lambda: "1.2.0")
    uc.notify_if_update_available("1.1.2", "push")
    assert "esync update" in capsys.readouterr().err


def test_auto_update_not_started_when_not_tty_or_update_command(monkeypatch, popen):
    monkeypatch.setenv(uc.AUTO_UPDATE_ENV, "1")
    monkeypatch.setattr(uc, "get_latest_version", lambda: "1.2.0")
    uc.notify_if_update_available("1.1.2", "push")  # 非 TTY
    _tty(monkeypatch)
    uc.notify_if_update_available("1.1.2", "update")
    assert popen == []
