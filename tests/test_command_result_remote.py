"""eLabFTW を書き換えるコマンドと new の run_* が返す CommandResult（MCP 向け）。"""

import json
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from elab_doc_sync import cli


def _project(tmp_path, mapping=None):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "key", "verify_ssl": False},
        "targets": [{"title": "T", "docs_dir": "docs/", "pattern": "*.md", "mode": "each", "entity": "items",
                     "id_file": ".elab-sync-ids/default.id"}],
    }
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    if mapping:
        (tmp_path / ".elab-sync-ids").mkdir()
        (tmp_path / ".elab-sync-ids" / "mapping.json").write_text(json.dumps(mapping))
        for name in mapping:
            (tmp_path / "docs" / name).write_text("# x\n", encoding="utf-8")
    return cfg


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_tag_list_and_add(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path, {"a.md": 42})
    client = MockClient.return_value
    client.base_url = "https://elab.example.com"
    client.get_tags.return_value = [{"tag": "x"}]
    res = cli.run_tag(Namespace(config=str(cfg), target=None, tag_action="list", id=None, entity=None))
    assert res.data["entities"] == [{"target": "T", "server": "https://elab.example.com", "entity": "items", "entity_id": 42,
                                     "tags": ["x"]}]
    res = cli.run_tag(Namespace(config=str(cfg), target=None, tag_action="add", tag_name="y", id=7,
                                entity="experiments"))
    assert res.data["entities"] == [{"target": None, "server": "https://elab.example.com", "entity": "experiments",
                                     "entity_id": 7, "tag": "y", "result": "added"}]
    assert res.data["dry_run"] is False
    assert capsys.readouterr().out == ""


def test_run_tag_argument_error_is_returned(tmp_path, capsys):
    cfg = _project(tmp_path)
    res = cli.run_tag(Namespace(config=str(cfg), target=None, tag_action="list", id=None, entity="items"))
    assert res.exit_code == 1 and "--id" in res.warnings[0] and res.messages == []
    assert capsys.readouterr().err == ""  # echo なしでは表示しない


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_tag_reports_unsynced_targets(MockClient, tmp_path):
    cfg = _project(tmp_path)
    res = cli.run_tag(Namespace(config=str(cfg), target=None, tag_action="list", id=None, entity=None))
    assert res.data["unsynced_targets"] == ["T"] and res.data["entities"] == []


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_relate_list_and_add(MockClient, tmp_path):
    cfg = _project(tmp_path)
    client = MockClient.return_value
    client.list_links.side_effect = lambda e, i, t: [{"entityid": 3, "title": "試薬A"}] if t == "items" else []
    res = cli.run_relate(Namespace(config=str(cfg), target=None, relate_action="list", id=7, entity="experiments"))
    assert res.data["sources"] == [{"server": "https://elab.example.com", "entity": "experiments", "entity_id": 7,
                                    "links": {"experiments": [], "items": [{"id": 3, "title": "試薬A"}]}}]
    res = cli.run_relate(Namespace(config=str(cfg), target=None, relate_action="add", target_ids=[3, 4, 7],
                                   to="experiments", id=7, entity="experiments", dry_run=True))
    assert [c["result"] for c in res.data["changes"]] == ["would_add", "would_add", "self"]
    client.add_link.assert_not_called()


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_metadata_rejects_bad_pair_before_reading(MockClient, tmp_path):
    cfg = _project(tmp_path, {"a.md": 42})
    res = cli.run_metadata(Namespace(config=str(cfg), target=None, meta_action="set", keyvalues=["ok=1", "bad"],
                                     id=None))
    assert res.exit_code == 1 and "key=value" in res.warnings[0]
    MockClient.return_value.update_metadata.assert_not_called()


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_metadata_set_warns_on_unreadable_existing(MockClient, tmp_path, capsys):
    cfg = _project(tmp_path, {"a.md": 42})
    client = MockClient.return_value
    client.get_metadata_raw.return_value = "{broken"
    client.get_metadata.side_effect = lambda *a: {}
    res = cli.run_metadata(Namespace(config=str(cfg), target=None, meta_action="set", keyvalues=["k=v"], id=None))
    [entry] = res.data["entities"]
    assert entry["result"] == "updated" and entry["metadata"] == {"k": "v"} and entry["unreadable_existing"]
    assert "読み取りに失敗" in res.warnings[0]
    # CLI では警告は標準エラー出力
    cli.cmd_metadata(Namespace(config=str(cfg), target=None, meta_action="set", keyvalues=["k=v"], id=None))
    captured = capsys.readouterr()
    assert "読み取りに失敗" in captured.err and "読み取りに失敗" not in captured.out


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_category_actions(MockClient, tmp_path):
    cfg = _project(tmp_path)
    client = MockClient.return_value
    client.base_url = "https://elab.example.com"
    client.list_categories.return_value = [{"id": 1, "title": "試薬"}]
    res = cli.run_category(Namespace(config=str(cfg), target=None, cat_action="list", entity="resources"))
    assert res.data == {"action": "list", "server": "https://elab.example.com", "entity": "items",
                        "categories": [{"id": 1, "title": "試薬"}]}
    client.get_entity.return_value = {"category": 1, "category_title": "試薬"}
    res = cli.run_category(Namespace(config=str(cfg), target=None, cat_action="show", id=5, entity="items"))
    assert res.data["category"] == {"id": 1, "title": "試薬"}
    client.resolve_category_id.return_value = 1
    res = cli.run_category(Namespace(config=str(cfg), target=None, cat_action="set", category_value="試薬", id=5,
                                     entity="items"))
    assert res.data["result"] == "already" and res.data["category_id"] == 1


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_entity_status_without_confirm_refuses_bulk_change(MockClient, tmp_path):
    cfg = _project(tmp_path, {"a.md": 42, "b.md": 43})
    with pytest.raises(ValueError, match="--id"):
        cli.run_entity_status(Namespace(config=str(cfg), target=None, status_action="set", status_id="3", id=None))
    MockClient.return_value.patch_entity.assert_not_called()


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_entity_status_confirm(MockClient, tmp_path):
    cfg = _project(tmp_path, {"a.md": 42, "b.md": 43})
    args = Namespace(config=str(cfg), target=None, status_action="set", status_id="3", id=None)
    res = cli.run_entity_status(args, confirm=lambda prompt: False)
    assert res.data["cancelled"] is True
    MockClient.return_value.patch_entity.assert_not_called()
    res = cli.run_entity_status(args, confirm=lambda prompt: True)
    assert [e["result"] for e in res.data["entities"]] == ["changed", "changed"]
    assert res.data["status_id"] == 3


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_entity_status_show(MockClient, tmp_path):
    cfg = _project(tmp_path, {"a.md": 42})
    MockClient.return_value.base_url = "https://elab.example.com"
    MockClient.return_value.get_entity.return_value = {"status_title": "Running"}
    res = cli.run_entity_status(Namespace(config=str(cfg), target=None, status_action="show", id=None))
    assert res.data["entities"] == [{"target": "T", "server": "https://elab.example.com", "entity": "items", "entity_id": 42,
                                     "status": "Running"}]


@patch("elab_doc_sync.cli.ELabFTWClient")
def test_run_new_list_and_create(MockClient, tmp_path):
    cfg = _project(tmp_path)
    client = MockClient.return_value
    client._req.return_value = MagicMock(json=MagicMock(return_value=[{"id": 1, "title": "Tpl"}]))
    res = cli.run_new(Namespace(config=str(cfg), target=None, force=False, list_templates=True, template_id=None,
                                title=None, output=None))
    assert res.data["templates"] == [{"id": 1, "title": "Tpl"}]
    client._req.return_value = MagicMock(json=MagicMock(return_value={"id": 1, "title": "Tpl", "body": ""}))
    res = cli.run_new(Namespace(config=str(cfg), target=None, force=False, list_templates=False, template_id=1,
                                title="Note", output=None))
    assert res.data["created"] is True and res.data["path"].endswith("Note.md")
    assert (tmp_path / "docs" / "Note.md").exists()
    res = cli.run_new(Namespace(config=str(cfg), target=None, force=False, list_templates=False, template_id=1,
                                title="Note", output=None))
    assert res.exit_code == 1 and res.data["created"] is False and "既に存在" in res.warnings[0]


def _two_server_project(tmp_path):
    data = {
        "elabftw": {"url": "https://a.example.com", "api_key": "ka", "verify_ssl": False},
        "profiles": {"B": {"url": "https://b.example.com", "api_key": "kb", "verify_ssl": False}},
        "targets": [
            {"title": "A", "docs_dir": "a/", "pattern": "*.md", "mode": "each", "entity": "items",
             "id_file": ".elab-sync-ids/a/default.id"},
            {"title": "B", "docs_dir": "b/", "pattern": "*.md", "mode": "each", "entity": "items",
             "id_file": ".elab-sync-ids/b/default.id", "profile": "B"},
        ],
    }
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "x.md").write_text("# x\n", encoding="utf-8")
        ids = tmp_path / ".elab-sync-ids" / name
        ids.mkdir(parents=True)
        (ids / "mapping.json").write_text(json.dumps({"x.md": 42}))
    return cfg


def _clients_by_url():
    clients = {}

    def make(url, *rest):
        if url not in clients:
            clients[url] = MagicMock(base_url=url)
            clients[url].list_links.return_value = []
        return clients[url]
    return clients, make


def test_run_relate_identifies_server_of_same_id(tmp_path):
    """別サーバーの同じ種別・ID を、接続先で区別できる。"""
    cfg = _two_server_project(tmp_path)
    clients, make = _clients_by_url()
    with patch("elab_doc_sync.cli.ELabFTWClient", side_effect=make):
        res = cli.run_relate(Namespace(config=str(cfg), target=None, relate_action="add", target_ids=[5],
                                       to="experiments", id=None, entity=None))
    assert sorted((c["server"], c["entity_id"], c["result"]) for c in res.data["changes"]) == [
        ("https://a.example.com", 42, "added"), ("https://b.example.com", 42, "added")]


def test_partial_result_is_attached_when_a_later_write_fails(tmp_path):
    """1 台目のサーバーへの変更後に 2 台目で失敗しても、済んだ変更を例外から確認できる。"""
    cfg = _two_server_project(tmp_path)
    clients, make = _clients_by_url()
    with patch("elab_doc_sync.cli.ELabFTWClient", side_effect=make):
        make("https://b.example.com").add_link.side_effect = RuntimeError("down")
        with pytest.raises(RuntimeError) as exc:
            cli.run_relate(Namespace(config=str(cfg), target=None, relate_action="add", target_ids=[5],
                                     to="experiments", id=None, entity=None))
    partial = exc.value.partial_result
    done = [c for c in partial.data["changes"] if c.get("result") == "added"]
    assert [(c["server"], c["entity_id"]) for c in done] == [("https://a.example.com", 42)]
    failed = [c for c in partial.data["changes"] if "result" not in c]
    assert [c["server"] for c in failed] == ["https://b.example.com"]


def test_partial_result_absent_for_errors_before_any_result(tmp_path):
    cfg = _project(tmp_path)
    with pytest.raises(ValueError) as exc:
        cli.run_category(Namespace(config=str(cfg), target="nope", cat_action="list", entity=None))
    assert getattr(exc.value, "partial_result", None) is None
