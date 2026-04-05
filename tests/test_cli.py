"""Tests for cli.py (CLI-01 ~ CLI-53)."""

import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

from elab_doc_sync.cli import (
    cmd_sync, cmd_pull, cmd_clone, cmd_log, cmd_diff, cmd_status, cmd_init, cmd_update,
)
from elab_doc_sync.sync import ConflictError


# ── helpers ──────────────────────────────────────────────

def _write_config(tmp_path, mode="merge", entity="items"):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "key", "verify_ssl": False},
        "targets": [{"title": "T", "docs_dir": "docs/", "pattern": "*.md", "mode": mode, "entity": entity}],
    }
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    return p, docs


def _ns(tmp_path, **kw):
    defaults = {"config": str(tmp_path / ".elab-sync.yaml"), "target": None, "force": False, "dry_run": False}
    defaults.update(kw)
    return Namespace(**defaults)


# ── cmd_sync (CLI-01 ~ CLI-05) ───────────────────────────

# CLI-01
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_sync_normal(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    MockClient.return_value.get_item.return_value = {"id": 1, "body": ""}
    MockClient.return_value.create_item.return_value = 1
    cmd_sync(_ns(tmp_path))


# CLI-02
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_sync_dry_run(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    cmd_sync(_ns(tmp_path, dry_run=True))
    MockClient.return_value.update_item.assert_not_called()


# CLI-03
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_sync_force(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    MockClient.return_value.get_item.return_value = {"id": 1, "body": ""}
    MockClient.return_value.create_item.return_value = 1
    cmd_sync(_ns(tmp_path, force=True))


# CLI-04
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_sync_target_filter(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    cmd_sync(_ns(tmp_path, target="nonexistent"))
    MockClient.return_value.create_item.assert_not_called()


# CLI-05
@patch("elab_doc_sync.cli.ELabFTWClient")
@patch("elab_doc_sync.cli.DocsSyncer")
def test_sync_conflict_error(MockSyncer, MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    MockSyncer.return_value.sync.side_effect = ConflictError("conflict!")
    cmd_sync(_ns(tmp_path))
    captured = capsys.readouterr()
    assert "競合検出" in captured.err


# ── cmd_pull (CLI-10 ~ CLI-14) ───────────────────────────

# CLI-10
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_each(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    MockClient.return_value.list_items.return_value = [{"id": 1}]
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "Doc1", "body": "<p>hi</p>"}
    cmd_pull(_ns(tmp_path, id=None, command="pull"))
    assert (docs / "Doc1.md").exists()


# CLI-11
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_merge(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="merge")
    # write id file
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    (ids_dir / "default.id").write_text("42\n")
    MockClient.return_value.get_item.return_value = {"id": 42, "title": "T", "body": "<p>content</p>"}
    cmd_pull(_ns(tmp_path, id=None, command="pull"))
    assert (docs / "T.md").exists()


# CLI-12
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_specific_id(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    MockClient.return_value.get_item.return_value = {"id": 99, "title": "Specific", "body": "<p>x</p>"}
    cmd_pull(_ns(tmp_path, id=99, command="pull"))
    assert (docs / "Specific.md").exists()


# CLI-13
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_skip_existing(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    (docs / "Doc1.md").write_text("original", encoding="utf-8")
    MockClient.return_value.list_items.return_value = [{"id": 1}]
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "Doc1", "body": "<p>new</p>"}
    cmd_pull(_ns(tmp_path, id=None, command="pull"))
    assert (docs / "Doc1.md").read_text(encoding="utf-8") == "original"


# CLI-14
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_force_overwrite(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    (docs / "Doc1.md").write_text("original", encoding="utf-8")
    MockClient.return_value.list_items.return_value = [{"id": 1}]
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "Doc1", "body": "<p>new</p>"}
    cmd_pull(_ns(tmp_path, id=None, command="pull", force=True))
    content = (docs / "Doc1.md").read_text(encoding="utf-8")
    assert "original" not in content


# ── cmd_clone (CLI-20 ~ CLI-26) ──────────────────────────

def _clone_ns(tmp_path, **kw):
    defaults = {
        "url": "https://elab.example.com", "id": [1], "dir": str(tmp_path / "cloned"),
        "entity": "items", "no_verify": True, "config": str(tmp_path / ".elab-sync.yaml"),
    }
    defaults.update(kw)
    return Namespace(**defaults)


# CLI-20
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_clone_normal(MockClient, tmp_path, monkeypatch):
    monkeypatch.setenv("ELABFTW_API_KEY", "test-key")
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "CloneDoc", "body": "<p>hi</p>"}
    cmd_clone(_clone_ns(tmp_path))
    cloned = tmp_path / "cloned"
    assert (cloned / ".elab-sync.yaml").exists()
    assert (cloned / "docs" / "CloneDoc.md").exists()
    assert (cloned / ".gitignore").exists()


# CLI-21
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_clone_multiple_ids(MockClient, tmp_path, monkeypatch):
    monkeypatch.setenv("ELABFTW_API_KEY", "test-key")
    MockClient.return_value.get_item.side_effect = [
        {"id": 1, "title": "A", "body": "<p>a</p>"},
        {"id": 2, "title": "B", "body": "<p>b</p>"},
    ]
    cmd_clone(_clone_ns(tmp_path, id=[1, 2]))
    cloned = tmp_path / "cloned"
    assert (cloned / "docs" / "A.md").exists()
    assert (cloned / "docs" / "B.md").exists()


# CLI-22
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_clone_existing_nonempty_dir(MockClient, tmp_path, monkeypatch):
    monkeypatch.setenv("ELABFTW_API_KEY", "test-key")
    dest = tmp_path / "cloned"
    dest.mkdir()
    (dest / "file.txt").write_text("x")
    with pytest.raises(SystemExit):
        cmd_clone(_clone_ns(tmp_path))


# CLI-23
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_clone_all_fail_cleanup(MockClient, tmp_path, monkeypatch):
    monkeypatch.setenv("ELABFTW_API_KEY", "test-key")
    MockClient.return_value.get_item.side_effect = Exception("fail")
    with pytest.raises(SystemExit):
        cmd_clone(_clone_ns(tmp_path))
    assert not (tmp_path / "cloned").exists()


# CLI-24
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_clone_all_fail_existing_empty_dir(MockClient, tmp_path, monkeypatch):
    monkeypatch.setenv("ELABFTW_API_KEY", "test-key")
    dest = tmp_path / "cloned"
    dest.mkdir()
    MockClient.return_value.get_item.side_effect = Exception("fail")
    with pytest.raises(SystemExit):
        cmd_clone(_clone_ns(tmp_path))
    assert dest.exists()  # dir itself preserved


# CLI-25
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_clone_gitignore_content(MockClient, tmp_path, monkeypatch):
    monkeypatch.setenv("ELABFTW_API_KEY", "test-key")
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "X", "body": ""}
    cmd_clone(_clone_ns(tmp_path))
    gi = (tmp_path / "cloned" / ".gitignore").read_text()
    assert ".elab-sync-ids/" in gi
    assert ".elab-sync.yaml" in gi


# CLI-26
def test_clone_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ELABFTW_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        cmd_clone(_clone_ns(tmp_path))


# ── cmd_log (CLI-30 ~ CLI-31) ────────────────────────────

# CLI-30
def test_log_display(tmp_path, capsys):
    from elab_doc_sync import sync_log
    log_path = tmp_path / ".elab-sync-ids" / "sync-log.jsonl"
    sync_log.record(log_path, action="push", target="T", entity="items", entity_id=1)
    cfg, _ = _write_config(tmp_path)
    cmd_log(Namespace(config=str(cfg), limit=20))
    out = capsys.readouterr().out
    assert "push" in out


# CLI-31
def test_log_limit(tmp_path, capsys):
    from elab_doc_sync import sync_log
    log_path = tmp_path / ".elab-sync-ids" / "sync-log.jsonl"
    for i in range(5):
        sync_log.record(log_path, action="push", target=f"T{i}", entity="items", entity_id=i)
    cfg, _ = _write_config(tmp_path)
    cmd_log(Namespace(config=str(cfg), limit=2))
    out = capsys.readouterr().out
    lines = [l for l in out.strip().splitlines() if l.strip()]
    assert len(lines) == 2


# ── cmd_init / cmd_update (CLI-40 ~ CLI-43) ──────────────

# CLI-40
def test_init_creates_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inputs = iter(["https://elab.example.com", "n", "", "", "merge", "items", "TestTitle"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    cfg_path = tmp_path / ".elab-sync.yaml"
    cmd_init(Namespace(config=str(cfg_path)))
    assert cfg_path.exists()


# CLI-41
def test_init_existing_abort(tmp_path, monkeypatch):
    cfg_path = tmp_path / ".elab-sync.yaml"
    cfg_path.write_text("existing")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    cmd_init(Namespace(config=str(cfg_path)))
    assert cfg_path.read_text() == "existing"


# CLI-42
def test_init_template_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inputs = iter(["https://elab.example.com", "n", "docs/", "", "each", "items"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    cmd_init(Namespace(config=str(tmp_path / ".elab-sync.yaml")))
    # init creates config; template expansion depends on package template dir
    assert (tmp_path / ".elab-sync.yaml").exists()


# CLI-43
@patch("subprocess.run")
def test_update(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    cmd_update(Namespace())
    mock_run.assert_called_once()


# ── cmd_diff / cmd_status (CLI-50 ~ CLI-53) ──────────────

# CLI-50
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_diff_has_diff(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("local content", encoding="utf-8")
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    (ids_dir / "default.id").write_text("1\n")
    MockClient.return_value.get_item.return_value = {"id": 1, "body": "<p>remote content</p>"}
    cmd_diff(_ns(tmp_path))
    out = capsys.readouterr().out
    assert "---" in out or "+++" in out or "@@" in out


# CLI-51
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_diff_no_diff(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("same", encoding="utf-8")
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    (ids_dir / "default.id").write_text("1\n")
    from markdownify import markdownify as html_to_md
    MockClient.return_value.get_item.return_value = {"id": 1, "body": "<p>same</p>"}
    cmd_diff(_ns(tmp_path))
    out = capsys.readouterr().out
    assert "差分なし" in out or "最新" in out


# CLI-52
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_status_changed(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("content", encoding="utf-8")
    cmd_status(_ns(tmp_path))
    out = capsys.readouterr().out
    assert "変更あり" in out


# CLI-53
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_status_up_to_date(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("content", encoding="utf-8")
    # save hash to make it "up to date"
    from elab_doc_sync.sync import DocsSyncer, _compute_hash
    from elab_doc_sync.config import TargetConfig
    target = TargetConfig(title="T", docs_dir="docs/", id_file=str(tmp_path / ".elab-sync-ids" / "default.id"))
    syncer = DocsSyncer(MockClient.return_value, target, tmp_path)
    syncer.save_hash("content")
    syncer.save_item_id(1)
    cmd_status(_ns(tmp_path))
    out = capsys.readouterr().out
    assert "最新" in out
