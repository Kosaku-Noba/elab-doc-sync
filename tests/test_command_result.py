"""参照系コマンドの run_* が表示せずに CommandResult を返すこと（MCP 向け）。"""

import json
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from elab_doc_sync import cli, sync_log
from elab_doc_sync.result import CommandResult, redact


def _project(tmp_path, mapping=None, profiles=None):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "secret-key", "verify_ssl": False},
        "targets": [{"title": "T", "docs_dir": "docs/", "pattern": "*.md", "mode": "each", "entity": "items",
                     "id_file": ".elab-sync-ids/default.id"}],
    }
    if profiles:
        data["profiles"] = profiles
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    if mapping:
        (tmp_path / ".elab-sync-ids").mkdir()
        (tmp_path / ".elab-sync-ids" / "mapping.json").write_text(json.dumps(mapping))
        for name in mapping:
            (tmp_path / "docs" / name).write_text("# x\n", encoding="utf-8")
    return cfg


def test_say_records_and_echoes():
    seen = []
    res = CommandResult(echo=seen.append)
    res.say("a")
    res.say()
    assert res.messages == ["a", ""] and seen == ["a", ""]
    assert res.to_dict() == {"exit_code": 0, "data": {}, "messages": ["a", ""], "warnings": []}


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_status_returns_documents_without_printing(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path)
    (tmp_path / "docs" / "a.md").write_text("content", encoding="utf-8")
    res = cli.run_status(Namespace(config=str(cfg), target=None))
    assert capsys.readouterr().out == ""
    assert res.exit_code == 0
    assert res.data["recovery_pending"] is False
    [doc] = res.data["documents"]
    assert doc["file"] == "a.md" and doc["state"] == "未追跡" and doc["entity_id"] is None
    assert doc["target"] == "T" and doc["entity"] == "items"
    assert "[a.md] 未追跡" in res.messages[0]


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_status_json_preserves_paths_and_reports_problem_states(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path, mapping={"missing.md": 7})
    config = yaml.safe_load(cfg.read_text())
    config["targets"][0]["pattern"] = "**/*.md"
    cfg.write_text(yaml.safe_dump(config))
    (tmp_path / "docs/missing.md").unlink()
    (tmp_path / "docs/sub").mkdir()
    (tmp_path / "docs/sub/ノート.md").write_text("# 内容", encoding="utf-8")
    (tmp_path / cli.RECOVERY).touch()
    args = cli.build_parser().parse_args(["status", "--json", "--config", str(cfg)])
    assert cli.cmd_status(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["recovery_pending"]
    assert {d["file"]: d["path"] for d in result["documents"]} == {
        "ノート.md": "docs/sub/ノート.md", "missing.md": None,
    }


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_status_streams_before_error(MockClient, tmp_path, capsys, monkeypatch):
    """CLI は 1 行ずつ表示するため、途中で例外になってもそれまでの表示が残る。"""
    cfg = _project(tmp_path)
    for name in ("a.md", "b.md"):
        (tmp_path / "docs" / name).write_text("content", encoding="utf-8")
    original = cli.EachDocsSyncer.inspect

    def inspect(self, name, eid, *a, **kw):
        if name == "b.md":
            raise RuntimeError("boom")
        return original(self, name, eid, *a, **kw)

    monkeypatch.setattr(cli.EachDocsSyncer, "inspect", inspect)
    with pytest.raises(RuntimeError):
        cli.cmd_status(Namespace(config=str(cfg), target=None))
    assert "[a.md] 未追跡" in capsys.readouterr().out


def test_run_log_returns_entries(tmp_path):
    cfg = _project(tmp_path)
    sync_log.record(tmp_path / sync_log.DEFAULT_LOG_PATH, action="push", target="T", entity="items", entity_id=1)
    res = cli.run_log(Namespace(config=str(cfg), limit=20))
    [entry] = res.data["entries"]
    assert entry["action"] == "push" and entry["entity_id"] == 1


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_list_returns_results(MockClient, tmp_path):
    cfg = _project(tmp_path)
    MockClient.return_value._req.return_value = MagicMock(json=MagicMock(return_value=[
        {"id": 1, "title": "A", "status_title": ""}, {"id": 2, "title": "B", "status_title": "Active"}]))
    res = cli.run_list(Namespace(config=str(cfg), target=None, entity_type="experiments", limit=5))
    assert res.data == {"entity": "experiments", "results": [
        {"id": 1, "title": "A", "status": None}, {"id": 2, "title": "B", "status": "Active"}]}


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_whoami_never_returns_api_key(MockClient, tmp_path):
    cfg = _project(tmp_path)
    MockClient.return_value._req.return_value = MagicMock(json=MagicMock(return_value={
        "firstname": "太郎", "lastname": "田中", "email": "t@example.com", "userid": 1, "team": 1,
        "teams": [{"id": 1, "name": "Lab A"}, {"id": 2, "name": "Lab B"}]}))
    res = cli.run_whoami(Namespace(config=str(cfg), target=None))
    [info] = res.data["profiles"]
    assert info["profile"] == "default" and info["email"] == "t@example.com"
    assert info["team"] == {"id": 1, "name": "Lab A"} and len(info["teams"]) == 2
    assert "secret-key" not in json.dumps(res.to_dict(), ensure_ascii=False)


@patch("elab_doc_sync.cli.ELabFTWClient")
@pytest.mark.parametrize("configured", [False, True])
def test_whoami_masks_credentials_in_profile_names(MockClient, tmp_path, monkeypatch, configured):
    name = "https://reader:private'phrase@lab.example"
    cfg = _project(tmp_path, profiles={name: {"url": "https://lab.example", "api_key_env": "WHOAMI_TEST_KEY"}})
    if configured:
        monkeypatch.setenv("WHOAMI_TEST_KEY", "test-key")
    else:
        monkeypatch.delenv("WHOAMI_TEST_KEY", raising=False)
    MockClient.return_value._req.return_value.json.return_value = {"userid": 1}
    lines = []
    res = cli.run_whoami(Namespace(config=str(cfg)), echo=lines.append)
    assert "[profile: https://***@lab.example]" in lines
    info = next(p for p in res.data["profiles"] if p["profile"] == "https://***@lab.example")
    assert (info["error"] is None) == configured
    assert "private" not in json.dumps([lines, res.to_dict()])


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_whoami_reports_connection_error(MockClient, tmp_path):
    cfg = _project(tmp_path)
    MockClient.return_value._req.side_effect = RuntimeError("down")
    res = cli.run_whoami(Namespace(config=str(cfg), target=None))
    assert "down" in res.data["profiles"][0]["error"]


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_verify_returns_problems(MockClient, tmp_path):
    cfg = _project(tmp_path, mapping={"a.md": 42, "b.md": 43})
    (tmp_path / "docs" / "b.md").unlink()
    res = cli.run_verify(Namespace(config=str(cfg), target=None))
    docs = {d["file"]: d for d in res.data["documents"]}
    assert docs["a.md"]["ok"] is True and docs["a.md"]["entity_id"] == 42
    assert docs["b.md"]["ok"] is False and "見つかりません" in docs["b.md"]["problem"]
    assert res.data["issues"] == 1


def test_run_verify_lists_unsynced_targets(tmp_path):
    cfg = _project(tmp_path)
    res = cli.run_verify(Namespace(config=str(cfg), target=None))
    assert res.data == {"documents": [], "unsynced_targets": ["T"], "issues": 0}


def test_run_backup_lists_manifests(tmp_path):
    cfg = _project(tmp_path)
    backup = tmp_path / ".elab-sync-backups" / "20261118T000000-abc"
    backup.mkdir(parents=True)
    (backup / "manifest.json").write_text(json.dumps({"id": "20261118T000000-abc", "reason": "pull"}))
    res = cli.run_backup(Namespace(config=str(cfg), backup_action="list"))
    assert res.data == {"backups": [{"id": "20261118T000000-abc", "reason": "pull"}]}


def test_run_profile_list_hides_api_keys(tmp_path):
    cfg = _project(tmp_path, profiles={"TeamB": {"url": "https://b.example.com", "api_key": "b-secret",
                                                 "verify_ssl": True}})
    res = cli.run_profile_list(Namespace(config=str(cfg), profile_action="list"))
    profiles = {p["name"]: p for p in res.data["profiles"]}
    assert profiles["TeamB"] == {"name": "TeamB", "url": "https://b.example.com", "has_api_key": True,
                                 "verify_ssl": True}
    assert profiles["default"]["has_api_key"] is True
    dumped = json.dumps(res.to_dict(), ensure_ascii=False)
    assert "b-secret" not in dumped and "secret-key" not in dumped


def test_run_search_returns_json_data_regardless_of_flag(tmp_path):
    cfg = _project(tmp_path)
    fake = MagicMock(base_url="https://elab.example.com")
    found = {"results": [("items", {"id": 1, "title": "A"})], "has_more": False, "next_offset": None,
             "truncated": False}
    args = Namespace(config=str(cfg), target=None, keyword=[], entity_type="items", author=None, since=None,
                     until=None, updated_since=None, updated_until=None, tag=None, category=None, status=None,
                     scope=None, order=None, sort=None, limit=20, offset=0, json=False, body=False)
    with patch("elab_doc_sync.cli._direct_client", return_value=fake), \
            patch("elab_doc_sync.search.search", return_value=found):
        res = cli.run_search(args)
    assert res.data["count"] == 1 and res.data["results"][0]["id"] == 1
    assert not res.messages[0].lstrip().startswith("{")  # 人向け表示は --json なしの形式


def test_redact_variants():
    key = "abc123\nxyz789"
    text = f"plain {key} repr {key!r} bytes {key.encode()!r} part xyz789"
    out = redact(text, key, None, "")
    assert "abc123" not in out and "xyz789" not in out
    assert redact("short ab", "ab\ncd") == "short ab"  # 4 文字未満の断片は置き換えない


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_whoami_redacts_api_key_in_error(MockClient, tmp_path):
    cfg = _project(tmp_path)
    MockClient.return_value._req.side_effect = ValueError(
        "Invalid leading whitespace in header value: b'secret-key'")
    res = cli.run_whoami(Namespace(config=str(cfg), target=None))
    dumped = json.dumps(res.to_dict(), ensure_ascii=False)
    assert "secret-key" not in dumped and "***" in res.data["profiles"][0]["error"]


def test_run_verify_does_not_migrate_legacy_mapping(tmp_path):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "k", "verify_ssl": False},
        "targets": [{"title": "T", "docs_dir": "docs/", "pattern": "*.md", "mode": "each", "entity": "items",
                     "id_file": ".elab-sync-ids/t/default.id"}],
    }
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / ".elab-sync-ids").mkdir()
    (tmp_path / ".elab-sync-ids" / "mapping.json").write_text(json.dumps({"a.md": 42}))
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    with patch("elab_doc_sync.cli.ELabFTWClient"):
        res = cli.run_verify(Namespace(config=str(cfg), target=None))
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    assert res.data["documents"][0]["entity_id"] == 42
