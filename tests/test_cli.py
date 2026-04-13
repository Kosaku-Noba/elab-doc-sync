"""Tests for cli.py (CLI-01 ~ CLI-53, CAT-01 ~ CAT-05)."""

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
    cmd_tag, cmd_metadata, cmd_entity_status, cmd_whoami, cmd_new,
    cmd_list, cmd_link, cmd_verify, cmd_category, REPO_URL,
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
    defaults = {"config": str(tmp_path / ".elab-sync.yaml"), "target": None, "force": False, "dry_run": False, "entity": None}
    defaults.update(kw)
    return Namespace(**defaults)


# ── cmd_sync (CLI-01 ~ CLI-05) ───────────────────────────

# CLI-01
@patch("elab_doc_sync.cli.ELabFTWClient")
@patch("elab_doc_sync.cli.DocsSyncer")
def test_sync_normal(MockSyncer, MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    MockSyncer.return_value.sync.return_value = True
    cmd_sync(_ns(tmp_path))
    MockSyncer.return_value.sync.assert_called_once_with(force=False)


# CLI-02
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_sync_dry_run(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    cmd_sync(_ns(tmp_path, dry_run=True))
    MockClient.return_value.update_item.assert_not_called()


# CLI-03
@patch("elab_doc_sync.cli.ELabFTWClient")
@patch("elab_doc_sync.cli.DocsSyncer")
def test_sync_force(MockSyncer, MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    MockSyncer.return_value.sync.return_value = True
    cmd_sync(_ns(tmp_path, force=True))
    MockSyncer.return_value.sync.assert_called_once_with(force=True)


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
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "Doc1", "body": "<p>hi</p>"}
    cmd_pull(_ns(tmp_path, id=[1], entity="items", command="pull"))
    assert (docs / "Doc1.md").exists()
    ids_dir = tmp_path / ".elab-sync-ids"
    assert (ids_dir / "mapping.json").exists()
    assert (ids_dir / "Doc1.md.hash").exists()
    assert (ids_dir / "Doc1.md.remote_hash").exists()


# CLI-11
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_merge(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="merge")
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    (ids_dir / "default.id").write_text("42\n")
    MockClient.return_value.get_item.return_value = {"id": 42, "title": "T", "body": "<p>content</p>"}
    cmd_pull(_ns(tmp_path, id=None, command="pull"))
    assert (docs / "T.md").exists()
    assert (ids_dir / "default.hash").exists()
    assert (ids_dir / "default.remote_hash").exists()


# CLI-12
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_specific_id(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    MockClient.return_value.get_item.return_value = {"id": 99, "title": "Specific", "body": "<p>x</p>"}
    cmd_pull(_ns(tmp_path, id=[99], entity="items", command="pull"))
    assert (docs / "Specific.md").exists()


# CLI-13
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_skip_existing(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    (docs / "Doc1.md").write_text("original", encoding="utf-8")
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    import json as _json
    (ids_dir / "mapping.json").write_text(_json.dumps({"Doc1.md": 1}))
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "Doc1", "body": "<p>new</p>"}
    cmd_pull(_ns(tmp_path, id=None, command="pull"))
    assert (docs / "Doc1.md").read_text(encoding="utf-8") == "original"


# CLI-14
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_force_overwrite(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    (docs / "Doc1.md").write_text("original", encoding="utf-8")
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    import json as _json
    (ids_dir / "mapping.json").write_text(_json.dumps({"Doc1.md": 1}))
    MockClient.return_value.get_item.return_value = {"id": 1, "title": "Doc1", "body": "<p>new</p>"}
    cmd_pull(_ns(tmp_path, id=None, command="pull", force=True))
    content = (docs / "Doc1.md").read_text(encoding="utf-8")
    assert "original" not in content


# ── cmd_clone (CLI-20 ~ CLI-26) ──────────────────────────


# CLI-15a: pull --id 指定時に --entity 未指定 → エラー終了
def test_pull_id_without_entity_exits(tmp_path, capsys):
    _write_config(tmp_path, mode="each")
    with pytest.raises(SystemExit) as exc_info:
        cmd_pull(_ns(tmp_path, id=[42], command="pull"))
    assert exc_info.value.code == 1
    assert "--entity も指定してください" in capsys.readouterr().err


# CLI-15: pull --id なし + mapping なし → エラーメッセージ
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_no_id_no_mapping(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path, mode="each")
    cmd_pull(_ns(tmp_path, id=None, command="pull"))
    out = capsys.readouterr().out
    assert "--id を指定してください" in out


# CLI-16: pull 複数 --id (each モード)
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_multiple_ids_each(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    MockClient.return_value.get_item.side_effect = [
        {"id": 1, "title": "A", "body": "<p>a</p>"},
        {"id": 2, "title": "B", "body": "<p>b</p>"},
    ]
    cmd_pull(_ns(tmp_path, id=[1, 2], entity="items", command="pull"))
    assert (docs / "A.md").exists()
    assert (docs / "B.md").exists()


# CLI-17: pull merge モードで複数 --id → 警告 + 先頭のみ使用
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_merge_multiple_ids_warning(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path, mode="merge")
    client = MockClient.return_value
    client.get_item.return_value = {"id": 10, "title": "T", "body": "<p>x</p>"}
    cmd_pull(_ns(tmp_path, id=[10, 20], entity="items", command="pull"))
    out = capsys.readouterr().out
    assert "最初の ID のみ使用" in out
    assert (docs / "T.md").exists()
    client.get_item.assert_called_once_with(10)


# CLI-18: pull --id --entity experiments で items ターゲットのみの yaml → 自動追加 + items 側は無影響
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_auto_add_target(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path, mode="each", entity="items")
    client = MockClient.return_value
    client.get_experiment.return_value = {"id": 42, "title": "Exp1", "body": "<p>exp</p>"}
    cmd_pull(_ns(tmp_path, id=[42], entity="experiments", command="pull"))
    out = capsys.readouterr().out
    # ターゲットが自動追加された
    assert "ターゲットを .elab-sync.yaml に追加" in out
    # experiments/ に保存された
    exp_dir = tmp_path / "experiments"
    assert (exp_dir / "Exp1.md").exists()
    # items 側の docs/ には何も保存されていない
    assert not list(docs.glob("Exp1*"))
    # items の get_item は呼ばれていない
    client.get_item.assert_not_called()
    # id_file が分離されている（experiments.id ベース）
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    exp_target = [t for t in raw["targets"] if t["entity"] == "experiments"][0]
    assert "experiments" in exp_target.get("id_file", "")


# CLI-19: 既に該当 entity のターゲットがあれば重複追加しない
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_no_duplicate_target(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each", entity="items")
    client = MockClient.return_value
    client.get_item.return_value = {"id": 1, "title": "D", "body": "<p>d</p>"}
    cmd_pull(_ns(tmp_path, id=[1], entity="items", command="pull"))
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert len(raw["targets"]) == 1


# CLI-20a: same-entity multi-target → --id 指定時は最初のターゲットだけ処理
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_same_entity_multi_target(MockClient, tmp_path):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "key", "verify_ssl": False},
        "targets": [
            {"title": "", "docs_dir": "alpha/", "pattern": "*.md", "mode": "each",
             "entity": "items", "id_file": ".elab-sync-ids/alpha.id"},
            {"title": "", "docs_dir": "beta/", "pattern": "*.md", "mode": "each",
             "entity": "items", "id_file": ".elab-sync-ids/beta.id"},
        ],
    }
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    client = MockClient.return_value
    client.get_item.return_value = {"id": 5, "title": "X", "body": "<p>x</p>"}
    cmd_pull(_ns(tmp_path, id=[5], entity="items", command="pull"))
    # alpha にだけ保存される（最初のターゲット）
    assert (tmp_path / "alpha" / "X.md").exists()
    # beta には保存されない
    assert not (tmp_path / "beta" / "X.md").exists()


# CLI-20b: same-entity multi-target + --target で2件目を指定
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_same_entity_with_target(MockClient, tmp_path):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "key", "verify_ssl": False},
        "targets": [
            {"title": "Alpha", "docs_dir": "alpha/", "pattern": "*.md", "mode": "each",
             "entity": "items", "id_file": ".elab-sync-ids/alpha.id"},
            {"title": "Beta", "docs_dir": "beta/", "pattern": "*.md", "mode": "each",
             "entity": "items", "id_file": ".elab-sync-ids/beta.id"},
        ],
    }
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    client = MockClient.return_value
    client.get_item.return_value = {"id": 7, "title": "Y", "body": "<p>y</p>"}
    cmd_pull(_ns(tmp_path, id=[7], entity="items", command="pull", target="Beta"))
    # beta に保存される（--target で指定）
    assert (tmp_path / "beta" / "Y.md").exists()
    # alpha には保存されない
    assert not (tmp_path / "alpha" / "Y.md").exists()


# CLI-20c: --target 不一致 → 0 件処理、API 呼び出しなし、副作用なし
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_target_mismatch_zero(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path, mode="each", entity="items")
    cmd_pull(_ns(tmp_path, id=[1], entity="items", command="pull", target="NoSuchTarget"))
    out = capsys.readouterr().out
    assert "0 件取得" in out
    # API は呼ばれない
    client = MockClient.return_value
    client.get_item.assert_not_called()
    # ファイルは生成されない
    assert list(docs.glob("*.md")) == []


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
    assert (cloned / ".elab-sync-ids" / "mapping.json").exists()


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
    inputs = iter(["https://elab.example.com", "n", "", "", "merge", "items", "md", "TestTitle"])
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
    inputs = iter(["https://elab.example.com", "n", "docs/", "", "each", "items", "md"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    cmd_init(Namespace(config=str(tmp_path / ".elab-sync.yaml")))
    # init creates config; template expansion depends on package template dir
    assert (tmp_path / ".elab-sync.yaml").exists()


# CLI-43
@patch("subprocess.run")
def test_update(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    cmd_update(Namespace())
    args, kwargs = mock_run.call_args
    assert args[0] == ["uv", "pip", "install", "--upgrade", REPO_URL]
    assert kwargs.get("check") is True
    mock_run.assert_called_once()


@patch("subprocess.run", side_effect=FileNotFoundError)
def test_update_no_uv(mock_run, capsys):
    with pytest.raises(SystemExit):
        cmd_update(Namespace())
    err = capsys.readouterr().err
    assert "uv が見つかりません" in err
    assert "docs.astral.sh/uv" in err


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


# ── FR-15 tag コマンドテスト ─────────────────────────────


# CLI-54: tag list
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_tag_list(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_tags.return_value = [{"id": 1, "tag": "alpha"}, {"id": 2, "tag": "beta"}]
    # merge mode: need an ID file
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="list", id=None, entity=None)
    cmd_tag(args)
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out


# CLI-55: tag add
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_tag_add(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="add", tag_name="newtag", id=None, entity=None)
    cmd_tag(args)
    client.add_tag.assert_called_once_with("items", 42, "newtag")


# CLI-56: tag remove
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_tag_remove(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.untag_by_name.return_value = True
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="remove", tag_name="old", id=None, entity=None)
    cmd_tag(args)
    client.untag_by_name.assert_called_once_with("items", 42, "old")


# CLI-63: tag add with --id and --entity (直接指定)
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_tag_add_direct(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    client = MockClient.return_value
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="add",
                     tag_name="direct-tag", id=99, entity="experiments")
    cmd_tag(args)
    client.add_tag.assert_called_once_with("experiments", 99, "direct-tag")
    assert "実験ノート #99" in capsys.readouterr().out


# CLI-64: tag list with --id and --entity (直接指定)
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_tag_list_direct(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    client = MockClient.return_value
    client.get_tags.return_value = [{"id": 1, "tag": "x"}]
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="list",
                     id=50, entity="items")
    cmd_tag(args)
    client.get_tags.assert_called_once_with("items", 50)
    assert "リソース #50" in capsys.readouterr().out


# CLI-65: tag --entity without --id exits with error
def test_cmd_tag_entity_without_id_exits(tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="list",
                     id=None, entity="items")
    with pytest.raises(SystemExit):
        cmd_tag(args)
    assert "--id" in capsys.readouterr().err


# CLI-66: tag --id without --entity exits with error
def test_cmd_tag_id_without_entity_exits(tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="add",
                     tag_name="x", id=42, entity=None)
    with pytest.raises(SystemExit):
        cmd_tag(args)
    assert "--entity" in capsys.readouterr().err


# CLI-67: tag remove with --id and --entity (直接指定)
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_tag_remove_direct(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    client = MockClient.return_value
    client.untag_by_name.return_value = True
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="remove",
                     tag_name="bye", id=10, entity="experiments")
    cmd_tag(args)
    client.untag_by_name.assert_called_once_with("experiments", 10, "bye")
    assert "実験ノート #10" in capsys.readouterr().out


# ── FR-15 metadata コマンドテスト ────────────────────────


# CLI-57: metadata get
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_metadata_get(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_metadata.return_value = {"project": "X", "version": "1"}
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, meta_action="get", id=None)
    cmd_metadata(args)
    out = capsys.readouterr().out
    assert "project" in out
    assert "X" in out


# CLI-58: metadata set
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_metadata_set(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_metadata.return_value = {"old": "val"}
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, meta_action="set", keyvalues=["new=data"], id=None)
    cmd_metadata(args)
    client.update_metadata.assert_called_once()
    call_meta = client.update_metadata.call_args[0][2]
    assert call_meta["old"] == "val"
    assert call_meta["new"] == "data"


# ── FR-16 entity-status コマンドテスト ───────────────────


# CLI-59: entity-status show
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_entity_status_show(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_entity.return_value = {"id": 42, "status_title": "Running"}
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, status_action="show", id=None)
    cmd_entity_status(args)
    out = capsys.readouterr().out
    assert "Running" in out


# CLI-60: entity-status set
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_entity_status_set_single(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, status_action="set", status_id="3", id=42)
    cmd_entity_status(args)
    client.patch_entity.assert_called_once_with("items", 42, status=3)


# ── FR-17 whoami テスト ──────────────────────────────────


# CLI-61: whoami
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_whoami(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(
        json=MagicMock(return_value={
            "firstname": "太郎", "lastname": "田中",
            "email": "taro@example.com", "userid": 1,
            "teams": [{"name": "Lab A"}],
        })
    )
    args = Namespace(config=str(cfg), target=None, force=False)
    cmd_whoami(args)
    out = capsys.readouterr().out
    assert "太郎" in out
    assert "taro@example.com" in out
    assert "Lab A" in out


# ── FR-18 new テスト ─────────────────────────────────────


# CLI-62: new --list
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_new_list(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(
        json=MagicMock(return_value=[{"id": 1, "title": "Protocol A"}, {"id": 2, "title": "Protocol B"}])
    )
    args = Namespace(config=str(cfg), target=None, force=False, list_templates=True, template_id=None, title=None, output=None)
    cmd_new(args)
    out = capsys.readouterr().out
    assert "Protocol A" in out
    assert "Protocol B" in out


# CLI-63: new --template-id でファイル生成
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_new_create_file(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(
        json=MagicMock(return_value={"id": 1, "title": "My Template", "body": "<h2>Section</h2><p>Content</p>"})
    )
    args = Namespace(config=str(cfg), target=None, force=False, list_templates=False, template_id=1, title=None, output=None)
    cmd_new(args)
    out = capsys.readouterr().out
    assert "✅" in out
    generated = tmp_path / "docs" / "My_Template.md"
    assert generated.exists()
    content = generated.read_text(encoding="utf-8")
    assert "# My Template" in content
    assert "Section" in content


# CLI-64: new — 既存ファイルがある場合はエラー
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_new_existing_file_error(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path)
    (docs / "Existing.md").write_text("old", encoding="utf-8")
    client = MockClient.return_value
    client._req.return_value = MagicMock(
        json=MagicMock(return_value={"id": 1, "title": "Existing", "body": ""})
    )
    args = Namespace(config=str(cfg), target=None, force=False, list_templates=False, template_id=1, title=None, output=None)
    with pytest.raises(SystemExit):
        cmd_new(args)


# CLI-65: new --output で出力先指定
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_new_custom_output(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(
        json=MagicMock(return_value={"id": 1, "title": "T", "body": "<p>body</p>"})
    )
    outfile = tmp_path / "custom" / "out.md"
    args = Namespace(config=str(cfg), target=None, force=False, list_templates=False, template_id=1, title="Custom", output=str(outfile))
    cmd_new(args)
    assert outfile.exists()
    assert "# Custom" in outfile.read_text(encoding="utf-8")


# ── FR-19 list テスト ────────────────────────────────────


# CLI-66: list items
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_list_items(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(
        json=MagicMock(return_value=[
            {"id": 1, "title": "Item A", "status_title": ""},
            {"id": 2, "title": "Item B", "status_title": "Active"},
        ])
    )
    args = Namespace(config=str(cfg), target=None, force=False, entity_type="items", limit=20)
    cmd_list(args)
    out = capsys.readouterr().out
    assert "#1" in out
    assert "Item A" in out
    assert "Item B" in out
    assert "Active" in out


# CLI-67: list experiments
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_list_experiments(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(
        json=MagicMock(return_value=[{"id": 10, "title": "Exp X"}])
    )
    args = Namespace(config=str(cfg), target=None, force=False, entity_type="experiments", limit=5)
    cmd_list(args)
    out = capsys.readouterr().out
    assert "#10" in out
    assert "Exp X" in out


# CLI-68: list 空
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_list_empty(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(json=MagicMock(return_value=[]))
    args = Namespace(config=str(cfg), target=None, force=False, entity_type="items", limit=20)
    cmd_list(args)
    out = capsys.readouterr().out
    assert "ありません" in out


# ── FR-20 link テスト ────────────────────────────────────


# CLI-69: link merge モード
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_link_merge(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_entity.return_value = {"id": 99, "body": "<p>hello</p>"}
    args = Namespace(config=str(cfg), target=None, force=False, entity_id=99, file=None)
    cmd_link(args)
    out = capsys.readouterr().out
    assert "99" in out
    id_file = tmp_path / ".elab-sync-ids" / "default.id"
    assert id_file.exists()
    assert id_file.read_text().strip() == "99"


# CLI-70: link each モード
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_link_each(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path, mode="each")
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_entity.return_value = {"id": 55, "body": "<p>test</p>"}
    args = Namespace(config=str(cfg), target=None, force=False, entity_id=55, file="a.md")
    cmd_link(args)
    out = capsys.readouterr().out
    assert "55" in out
    mapping_file = tmp_path / ".elab-sync-ids" / "mapping.json"
    assert mapping_file.exists()
    mapping = json.loads(mapping_file.read_text())
    assert mapping["a.md"] == 55


# CLI-71: link each モードで --file なしはエラー
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_link_each_no_file(MockClient, tmp_path):
    cfg, _ = _write_config(tmp_path, mode="each")
    args = Namespace(config=str(cfg), target=None, force=False, entity_id=55, file=None)
    with pytest.raises(SystemExit):
        cmd_link(args)


# ── FR-21 verify テスト ──────────────────────────────────


# CLI-72: verify 正常（merge）
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_verify_merge_ok(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_entity.return_value = {"id": 42, "title": "T"}
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False)
    cmd_verify(args)
    out = capsys.readouterr().out
    assert "✓" in out
    assert "問題はありません" in out


# CLI-73: verify リモートアクセス失敗
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_verify_remote_fail(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_entity.side_effect = Exception("404")
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("42", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False)
    cmd_verify(args)
    out = capsys.readouterr().out
    assert "⚠" in out
    assert "アクセスできません" in out


# CLI-74: verify 未同期
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_verify_not_synced(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False)
    cmd_verify(args)
    out = capsys.readouterr().out
    assert "未同期" in out


# CLI-75: verify each モード — ローカルファイル欠損
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_verify_each_missing_file(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path, mode="each")
    client = MockClient.return_value
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    mapping = {"missing.md": 10, "exists.md": 20}
    (id_dir / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    (docs / "exists.md").write_text("# E\n", encoding="utf-8")
    client.get_entity.return_value = {"id": 20}
    args = Namespace(config=str(cfg), target=None, force=False)
    cmd_verify(args)
    out = capsys.readouterr().out
    assert "missing.md" in out
    assert "見つかりません" in out
    assert "✓" in out  # exists.md は OK


# ── 表示ラベル統一の回帰テスト ───────────────────────────


# CLI-76: tag list の出力に「リソース」が含まれる
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_tag_list_shows_resource_label(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_tags.return_value = [{"id": 1, "tag": "t"}]
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("1", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, tag_action="list", id=None, entity=None)
    cmd_tag(args)
    out = capsys.readouterr().out
    assert "リソース" in out
    assert "items" not in out


# CLI-77: entity-status show の出力に「リソース」が含まれる
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_entity_status_shows_resource_label(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("# A\n", encoding="utf-8")
    client = MockClient.return_value
    client.get_entity.return_value = {"id": 1, "status_title": "Running"}
    id_dir = tmp_path / ".elab-sync-ids"
    id_dir.mkdir()
    (id_dir / "default.id").write_text("1", encoding="utf-8")
    args = Namespace(config=str(cfg), target=None, force=False, status_action="show", id=None)
    cmd_entity_status(args)
    out = capsys.readouterr().out
    assert "リソース" in out
    assert "items" not in out


# ── pull 画像ダウンロード (CLI-60 ~ CLI-61) ─────────────

# CLI-60: pull each で画像がダウンロードされる
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_each_downloads_images(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="each")
    client = MockClient.return_value
    client.get_item.return_value = {
        "id": 1, "title": "Doc1",
        "body": '<p><img src="https://elab.example.com/app/download.php?f=abc123.png&name=photo.png&storage=1" alt="pic"></p>',
    }
    client.list_uploads.return_value = [
        {"id": 10, "long_name": "abc123.png", "real_name": "photo.png", "storage": "1"},
    ]
    client.download_upload.return_value = b"\x89PNG"
    cmd_pull(_ns(tmp_path, id=[1], entity="items", command="pull"))
    md = (docs / "Doc1.md").read_text(encoding="utf-8")
    assert "images/items_1_photo.png" in md
    assert (docs / "images" / "items_1_photo.png").exists()


# CLI-61: pull merge で画像がダウンロードされる
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_pull_merge_downloads_images(MockClient, tmp_path):
    cfg, docs = _write_config(tmp_path, mode="merge")
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    (ids_dir / "default.id").write_text("1\n")
    client = MockClient.return_value
    client.get_item.return_value = {
        "id": 1, "title": "T",
        "body": '<p><img src="https://elab.example.com/app/download.php?f=xyz.png&name=fig.png&storage=1" alt="f"></p>',
    }
    client.list_uploads.return_value = [
        {"id": 20, "long_name": "xyz.png", "real_name": "fig.png", "storage": "1"},
    ]
    client.download_upload.return_value = b"\x89PNG"
    cmd_pull(_ns(tmp_path, id=[1], entity="items", command="pull", force=True))
    md = (docs / "T.md").read_text(encoding="utf-8")
    assert "images/items_1_fig.png" in md


# ── diff 画像正規化 (CLI-62) ────────────────────────────

# CLI-62: diff でリモート画像 URL が正規化され、ローカルと一致すれば差分なし
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_diff_no_false_positive_with_images(MockClient, tmp_path, capsys):
    cfg, docs = _write_config(tmp_path)
    (docs / "a.md").write_text("![pic](images/items_1_photo.png)", encoding="utf-8")
    ids_dir = tmp_path / ".elab-sync-ids"
    ids_dir.mkdir(exist_ok=True)
    (ids_dir / "default.id").write_text("1\n")
    client = MockClient.return_value
    client.get_item.return_value = {
        "id": 1,
        "body": '<p><img src="https://elab.example.com/app/download.php?f=abc123.png&name=photo.png&storage=1" alt="pic"></p>',
    }
    client.list_uploads.return_value = [
        {"id": 10, "long_name": "abc123.png", "real_name": "photo.png", "storage": "1"},
    ]
    cmd_diff(_ns(tmp_path))
    out = capsys.readouterr().out
    assert "差分なし" in out or "最新" in out


# CLI-54: _MD_OPTS でラウンドトリップ時に過剰エスケープが入らない
def test_md_opts_no_excessive_escape():
    from markdownify import markdownify as html_to_md
    from elab_doc_sync.cli import _MD_OPTS

    # 本ツール push 済み HTML を想定
    html = '<p>file_name and x*y and $a_{i}$</p>'
    result = html_to_md(html, **_MD_OPTS)
    assert r"\_" not in result, f"アンダースコアがエスケープされている: {result}"
    assert r"\*" not in result, f"アスタリスクがエスケープされている: {result}"
    assert "file_name" in result
    assert "x*y" in result


# CLI-55: Web UI 作成 HTML のリテラル * _ は強調解釈される（許容する仕様）
def test_md_opts_literal_asterisk_underscore_becomes_emphasis():
    from markdownify import markdownify as html_to_md
    from elab_doc_sync.cli import _MD_OPTS

    # Web UI で <em> ではなくリテラルに * を含む HTML
    html = '<p>use *bold* and _italic_ here</p>'
    result = html_to_md(html, **_MD_OPTS)
    # エスケープされないため Markdown の強調記法として解釈される（許容する仕様）
    assert r"\*" not in result
    assert r"\_" not in result
    assert "*bold*" in result
    assert "_italic_" in result


# CLI-56: esync push が cmd_sync と同じ経路に入る
def test_push_subcommand_dispatches_to_sync(tmp_path, capsys):
    """push サブコマンドが main() 経由で cmd_sync に委譲されることを確認。"""
    _write_config(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "test.md").write_text("# Test\n")

    from unittest.mock import patch, MagicMock
    mock_client = MagicMock()
    mock_client.get_item.return_value = {"body": ""}
    mock_client.create_item.return_value = 1
    mock_client.list_uploads.return_value = []

    with patch("elab_doc_sync.cli.ELabFTWClient", return_value=mock_client), \
         patch("sys.argv", ["esync", "push", "--config", str(tmp_path / ".elab-sync.yaml")]):
        from elab_doc_sync.cli import main
        main()

    out = capsys.readouterr().out
    assert "更新しました" in out or "新規作成" in out


# CLI-57: 未知コマンドは argparse が usage error（code 2）で拒否する
def test_unknown_command_exits_with_usage_error(tmp_path, capsys):
    _write_config(tmp_path)
    from unittest.mock import patch
    with patch("sys.argv", ["esync", "nonexistent", "--config", str(tmp_path / ".elab-sync.yaml")]):
        from elab_doc_sync.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 2


# ── カテゴリコマンドテスト ────────────────────────


# CAT-01: category list
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_category_list(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client.list_categories.return_value = [{"id": 1, "title": "試薬"}, {"id": 2, "title": "機器"}]
    args = Namespace(config=str(cfg), target=None, force=False, cat_action="list", entity=None)
    cmd_category(args)
    out = capsys.readouterr().out
    assert "試薬" in out
    assert "機器" in out


# CAT-02: category show
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_category_show(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client.get_entity.return_value = {"category": 1, "category_title": "試薬"}
    args = Namespace(config=str(cfg), target=None, force=False, cat_action="show", id=42, entity="items")
    cmd_category(args)
    out = capsys.readouterr().out
    assert "試薬" in out
    assert "#42" in out


# CAT-03: category set
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_cmd_category_set(MockClient, tmp_path, capsys):
    cfg, _ = _write_config(tmp_path)
    client = MockClient.return_value
    client.resolve_category_id.return_value = 3
    args = Namespace(config=str(cfg), target=None, force=False, cat_action="set",
                     category_value="プロトコル", id=42, entity="items")
    cmd_category(args)
    client.patch_entity.assert_called_once_with("items", 42, category=3)
    assert "#42" in capsys.readouterr().out


# CAT-04: category show without --id exits (argparse required)
def test_cmd_category_show_without_id_exits(tmp_path):
    cfg, _ = _write_config(tmp_path)
    from unittest.mock import patch as _patch
    with _patch("sys.argv", ["esync", "category", "show", "--config", str(cfg)]):
        from elab_doc_sync.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 2


# CAT-05: category set without --id exits (argparse required)
def test_cmd_category_set_without_id_exits(tmp_path):
    cfg, _ = _write_config(tmp_path)
    from unittest.mock import patch as _patch
    with _patch("sys.argv", ["esync", "category", "set", "試薬", "--config", str(cfg)]):
        from elab_doc_sync.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 2
