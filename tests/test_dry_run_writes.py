"""eLabFTW を書き換えるコマンド（tag / relate / metadata / category / entity-status）と new の --dry-run。"""

import json
import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from elab_doc_sync import cli
from elab_doc_sync.cli import cmd_category, cmd_entity_status, cmd_metadata, cmd_new, cmd_relate, cmd_tag


def _project(tmp_path, tracked=True):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "key", "verify_ssl": False},
        "targets": [{"title": "T", "docs_dir": "docs/", "pattern": "*.md", "mode": "each", "entity": "items",
                     "id_file": ".elab-sync-ids/default.id"}],
    }
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    if tracked:
        (docs / "a.md").write_text("# A\n", encoding="utf-8")
        ids = tmp_path / ".elab-sync-ids"
        ids.mkdir()
        (ids / "mapping.json").write_text(json.dumps({"a.md": 42}))
    return cfg


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_tag_add_dry_run_does_not_write(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path)
    client = MockClient.return_value
    client.get_tags.return_value = [{"tag": "old"}]
    cmd_tag(Namespace(config=str(cfg), target=None, tag_action="add", tag_name="new", id=None, entity=None,
                      dry_run=True))
    client.add_tag.assert_not_called()
    assert "リソース #42: タグ「new」を追加予定" in capsys.readouterr().out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_tag_add_dry_run_reports_existing(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path)
    MockClient.return_value.get_tags.return_value = [{"tag": "old"}]
    cmd_tag(Namespace(config=str(cfg), target=None, tag_action="add", tag_name="old", id=7, entity="experiments",
                      dry_run=True))
    MockClient.return_value.add_tag.assert_not_called()
    assert "実験ノート #7: タグ「old」は既にあります" in capsys.readouterr().out


@pytest.mark.parametrize("tags, expected", [([{"tag": "old"}], "を外す予定"), ([], "が見つかりません")])
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_tag_remove_dry_run(MockClient, tmp_path, capsys, tags, expected):
    cfg = _project(tmp_path)
    client = MockClient.return_value
    client.get_tags.return_value = tags
    cmd_tag(Namespace(config=str(cfg), target=None, tag_action="remove", tag_name="old", id=None, entity=None,
                      dry_run=True))
    client.untag_by_name.assert_not_called()
    assert f"タグ「old」{expected}" in capsys.readouterr().out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_relate_add_dry_run(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path, tracked=False)
    client = MockClient.return_value
    client.list_links.return_value = [{"entityid": 12}]
    cmd_relate(Namespace(config=str(cfg), target=None, relate_action="add", target_ids=[12, 15], to="experiments",
                         id=42, entity="items", dry_run=True))
    client.add_link.assert_not_called()
    out = capsys.readouterr().out
    assert "実験ノート #12 へのリンクは既にあります" in out
    assert "実験ノート #15 へのリンクを追加予定" in out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_relate_remove_dry_run(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path)
    client = MockClient.return_value
    client.list_links.return_value = [{"entityid": 5}]
    cmd_relate(Namespace(config=str(cfg), target=None, relate_action="remove", target_ids=[5, 6], to="items",
                         id=None, entity=None, dry_run=True))
    client.remove_link.assert_not_called()
    out = capsys.readouterr().out
    assert "リソース #5 へのリンクを外す予定" in out
    assert "リソース #6 へのリンクが見つかりません" in out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_metadata_set_dry_run_shows_merged_result(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path)
    client = MockClient.return_value
    client.get_metadata.return_value = {"old": "val"}
    client.get_metadata_raw.return_value = '{"old": "val"}'
    cmd_metadata(Namespace(config=str(cfg), target=None, meta_action="set", keyvalues=["new=data"], id=None,
                           dry_run=True))
    client.update_metadata.assert_not_called()
    out = capsys.readouterr().out
    assert "メタデータを更新予定" in out
    assert '"old": "val"' in out and '"new": "data"' in out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_category_set_dry_run(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path, tracked=False)
    client = MockClient.return_value
    client.get_entity.return_value = {"category": 1}
    client.resolve_category_id.return_value = 3
    cmd_category(Namespace(config=str(cfg), target=None, cat_action="set", category_value="プロトコル", id=42,
                           entity="items", dry_run=True))
    client.patch_entity.assert_not_called()
    assert "リソース #42: カテゴリを設定予定 (#3)" in capsys.readouterr().out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_entity_status_set_dry_run_skips_prompt(MockClient, tmp_path, capsys, monkeypatch):
    cfg = _project(tmp_path)
    (tmp_path / "docs" / "b.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / ".elab-sync-ids" / "mapping.json").write_text(json.dumps({"a.md": 42, "b.md": 43}))
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=AssertionError("input() must not be called")))
    client = MockClient.return_value
    client.get_entity.side_effect = lambda etype, eid: (
        {"status": 1, "status_title": "Running"} if eid == 42 else {"status": 3, "status_title": "Done"})
    cmd_entity_status(Namespace(config=str(cfg), target=None, status_action="set", status_id="3", id=None,
                                dry_run=True))
    client.patch_entity.assert_not_called()
    out = capsys.readouterr().out
    assert "リソース #42: ステータスを Running から #3 に変更予定" in out
    assert "リソース #43: すでにステータス #3（Done）です" in out


@pytest.mark.parametrize("dry_run", [True, False])
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_entity_status_set_rejects_non_numeric_id(MockClient, tmp_path, dry_run):
    cfg = _project(tmp_path)
    with pytest.raises(ValueError, match="数値"):
        cmd_entity_status(Namespace(config=str(cfg), target=None, status_action="set", status_id="done", id=42,
                                    dry_run=dry_run))
    MockClient.return_value.patch_entity.assert_not_called()


def _legacy_project(tmp_path):
    """id_file が別ディレクトリにあり、旧形式の共有 mapping.json だけが残るプロジェクト。"""
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "key", "verify_ssl": False},
        "targets": [{"title": "T", "docs_dir": "docs/", "pattern": "*.md", "mode": "each", "entity": "items",
                     "id_file": ".elab-sync-ids/t/default.id"}],
    }
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / ".elab-sync-ids").mkdir()
    (tmp_path / ".elab-sync-ids" / "mapping.json").write_text(json.dumps({"a.md": 42}))
    return cfg


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


@pytest.mark.parametrize("args", [
    dict(command=cmd_tag, tag_action="add", tag_name="x", id=None, entity=None),
    dict(command=cmd_relate, relate_action="add", target_ids=[5], to="items", id=None, entity=None),
    dict(command=cmd_metadata, meta_action="set", keyvalues=["k=v"], id=None),
    dict(command=cmd_entity_status, status_action="set", status_id="3", id=None),
])
@patch("elab_doc_sync.cli.ELabFTWClient")
def test_dry_run_does_not_migrate_legacy_mapping(MockClient, tmp_path, capsys, args):
    cfg = _legacy_project(tmp_path)
    client = MockClient.return_value
    client.get_tags.return_value = []
    client.list_links.return_value = []
    client.get_metadata.return_value = {}
    client.get_metadata_raw.return_value = ""
    client.get_entity.return_value = {"status": 1, "status_title": "Running"}
    before = _tree(tmp_path)
    command = args.pop("command")
    command(Namespace(config=str(cfg), target=None, dry_run=True, **args))
    assert _tree(tmp_path) == before
    assert "#42" in capsys.readouterr().out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_new_dry_run_does_not_create_file(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path, tracked=False)
    MockClient.return_value._req.return_value = MagicMock(
        json=MagicMock(return_value={"id": 1, "title": "My Template", "body": "<p>x</p>"}))
    cmd_new(Namespace(config=str(cfg), target=None, force=False, list_templates=False, template_id=1, title=None,
                      output=None, dry_run=True))
    assert not (tmp_path / "docs" / "My_Template.md").exists()
    assert "My_Template.md を作成予定" in capsys.readouterr().out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_main_accepts_dry_run_for_remote_writes(MockClient, tmp_path, monkeypatch, capsys):
    cfg = _project(tmp_path, tracked=False)
    MockClient.return_value.get_tags.return_value = []
    monkeypatch.setattr(cli.update_check, "notify_if_update_available", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["esync", "tag", "-c", str(cfg), "--dry-run", "add", "x", "--id", "9",
                                      "--entity", "items"])
    cli.main()
    MockClient.return_value.add_tag.assert_not_called()
    assert "タグ「x」を追加予定" in capsys.readouterr().out
    assert not (tmp_path / ".elab-sync.lock").exists()


@pytest.mark.parametrize("argv", [["init", "--dry-run"], ["profile", "--dry-run", "remove", "p"]])
def test_main_still_rejects_dry_run_for_init_and_profile(tmp_path, monkeypatch, capsys, argv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.update_check, "notify_if_update_available", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["esync", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "--dry-run に対応していません" in capsys.readouterr().err
