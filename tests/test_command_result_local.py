"""ローカル操作の構造化結果、逐次出力、ロックの回帰テスト。"""

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from elab_doc_sync import cli
from elab_doc_sync.safety import project_lock, snapshot


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.safe_dump({
        "elabftw": {"url": "https://example.invalid", "api_key": "test"},
        "targets": [{"docs_dir": "docs", "id_file": ".ids/default.id"}],
    }))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/note.md").write_text("# note")
    (tmp_path / ".ids").mkdir()
    (tmp_path / ".ids/mapping.json").write_text('{"note.md": 42}')
    return Namespace(config=str(cfg), target=None, dry_run=True, force=False)


def test_local_previews(project, capsys):
    project.files = ["docs/note.md"]
    project.local = True
    project.id = project.entity = None
    [doc] = cli.run_rm(project).data["documents"]
    assert doc["entity_id"] == 42 and Path(doc["path"]) == Path("docs/note.md").resolve()
    project.old, project.new = "docs/note.md", "docs/next.md"
    assert cli.run_mv(project).data["entity_id"] == 42
    [target] = cli.run_push(project).data["targets"]
    assert target["documents"][0]["filename"] == "note.md"
    assert capsys.readouterr().out == ""


def test_restore_result_and_lock(project, tmp_path, capsys):
    path = tmp_path / "docs/note.md"
    project.backup_id = snapshot(tmp_path, [path], "test")
    path.write_text("changed")
    with project_lock(tmp_path):
        assert cli.run_restore(project).data["paths"][0]["path"] == "docs/note.md"
        project.dry_run = False
        with pytest.raises(RuntimeError, match="実行中"):
            cli.run_restore(project)
    res = cli.run_restore(project)
    assert path.read_text() == "# note"
    assert any("バックアップ" in line for line in res.messages)
    json.dumps(res.to_dict())
    assert capsys.readouterr().out == ""


def test_pull_result_partial_failure(project, capsys):
    project.id, project.entity, project.auto, project.dir = [42, 43], "items", True, None
    with patch.object(cli, "ELabFTWClient") as mock_client:
        client = mock_client.return_value
        client.base_url = "https://example.invalid"
        client.get_item.side_effect = [{"title": "note"}, ValueError("missing")]
        project.force = True
        res = cli.run_pull(project)
    assert res.exit_code == 1
    assert (res.data["pulled"], res.data["failed"]) == (1, 1)
    assert {d["entity_id"] for d in res.data["documents"]} == {42, 43}
    assert any("取得予定" in line for line in res.messages)
    assert capsys.readouterr() == ("", "")


def test_pull_uses_shared_candidate_profile_and_hides_key(project, tmp_path):
    path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["profiles"] = {"lab": {"url": "https://lab.invalid", "api_key": "private-key"}}
    cfg["targets"] = [{"docs_dir": name, "profile": "lab"} for name in ("one", "two")]
    path.write_text(yaml.safe_dump(cfg))
    project.id, project.entity, project.auto, project.dir = [1, 2], "items", False, None
    project.dry_run = False
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.get_item.side_effect = [ValueError("header: private-key"), {"title": "X"}]
        res = cli.run_pull(project, choose_target=lambda *_: "SKIP")
    assert all(call.args[0] == "https://lab.invalid" for call in factory.call_args_list)
    assert "private-key" not in json.dumps(res.to_dict())
    assert res.data["documents"][1]["result"] == "skipped"


def test_rm_reports_completed_deletions(project, tmp_path, monkeypatch):
    project.id, project.entity, project.files = [41, 42], "items", []
    project.local, project.dry_run = True, False
    (tmp_path / "docs/a.md").touch()
    (tmp_path / ".ids/mapping.json").write_text('{"a.md":41,"note.md":42}')
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == tmp_path / "docs/note.md":
            raise OSError("busy")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(OSError) as caught:
        cli.run_rm(project)
    a, note = caught.value.partial_result.data["documents"]
    assert a["file_absent"] and "file_absent" not in note
    assert a["tracking"] == note["tracking"] == "untracked"


def test_pull_new_target_keeps_source_profile(project, tmp_path):
    path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["profiles"] = {"lab": {"url": "https://lab.invalid", "api_key": "lab-secret"}}
    cfg["targets"] = [{"docs_dir": name, "profile": "lab"} for name in ("one", "two")]
    path.write_text(yaml.safe_dump(cfg))
    project.id, project.entity, project.auto, project.dir = [11], "items", False, None
    project.dry_run = False
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://lab.invalid"
        client.get_item.return_value = {"title": "doc", "body": "from lab", "category_title": "incoming"}
        client.list_uploads.return_value = []
        res = cli.run_pull(project, choose_target=lambda *_: None)
    assert res.exit_code == 0 and "from lab" in (tmp_path / "incoming/doc.md").read_text()
    assert yaml.safe_load(path.read_text())["targets"][-1]["profile"] == "lab"
    assert {call.args[0] for call in factory.call_args_list} == {"https://lab.invalid"}


@pytest.mark.parametrize("entity, directory", [("experiments", None), ("items", "other")])
def test_pull_rejects_contradictory_source_before_fetch(project, tmp_path, entity, directory):
    cfg_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["profiles"] = {"second": {"url": "https://other.invalid", "api_key": "foreign"}}
    cfg["targets"].append({"docs_dir": "other", "profile": "second"})
    cfg_path.write_text(yaml.safe_dump(cfg))
    project.id, project.entity, project.target, project.dir = [123], entity, "docs", directory
    before = cfg_path.read_bytes()
    with patch.object(cli, "ELabFTWClient") as factory, pytest.raises(ValueError):
        cli.run_pull(project)
    factory.assert_not_called()
    assert before == cfg_path.read_bytes()


def test_rm_dangling_symlink_remains_unconfirmed(project, tmp_path):
    project.id, project.entity, project.files = None, None, ["docs/missing.md"]
    project.local, project.dry_run = True, False
    (tmp_path / ".ids/excluded.json").write_text('["missing.md"]')
    link = tmp_path / "docs/missing.md"
    try:
        link.symlink_to("absent")
    except OSError:
        pytest.skip("symlink unavailable")
    result = cli.run_rm(project)
    assert result.exit_code and result.data["documents"] == [] and link.is_symlink()


def test_http_error_omits_signed_url():
    import requests
    from elab_doc_sync.result import error_text
    reply = requests.Response()
    reply.status_code = 403
    assert error_text(requests.HTTPError("https://server/?sig=secret", response=reply)) == "HTTP 403（権限がありません）"


def test_batch_pull_validates_export_before_fetch(project, tmp_path):
    cfg_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["profiles"] = {"other": {"url": "https://other.invalid", "api_key": "other-key"}}
    cfg["targets"].append({"docs_dir": "other", "profile": "other"})
    cfg_path.write_text(yaml.safe_dump(cfg))
    project.target, project.dir, project.id = "docs", "other", None
    with patch.object(cli, "ELabFTWClient") as factory, pytest.raises(ValueError):
        cli.run_pull(project)
    factory.assert_not_called()


def test_generated_pull_directory_cannot_mix_entity_types(project, tmp_path):
    cfg_path = tmp_path / ".elab-sync.yaml"
    before = cfg_path.read_bytes()
    project.id, project.entity, project.dir = [1], "experiments", None
    project.dry_run = False
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.get_experiment.return_value = {"title": "entry", "category_title": "docs"}
        res = cli.run_pull(project)
    assert res.exit_code == 1 and before == cfg_path.read_bytes()
    assert not (tmp_path / "docs/entry.md").exists()


@pytest.mark.parametrize("last_folder", ["same", "other"])
def test_multiple_ids_reuse_created_target(project, tmp_path, last_folder):
    project.id, project.entity, project.dir = [1, 2], "experiments", None
    project.dry_run = False
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_experiment.side_effect = lambda eid: {"title": f"entry{eid}", "category_title": "same" if eid == 1 else last_folder}
        client.list_uploads.return_value = []
        res = cli.run_pull(project)
    assert res.exit_code == 0 and res.data["pulled"] == 2
    targets = yaml.safe_load((tmp_path / ".elab-sync.yaml").read_text())["targets"]
    assert sum(t["docs_dir"] == "same/" for t in targets) == 1
    assert (tmp_path / last_folder / "entry2.md").is_file()


@pytest.mark.parametrize("nested", [False, True])
def test_force_pull_protects_other_target_document(project, tmp_path, nested):
    path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(path.read_text())
    folder = "docs/private" if nested else "other"
    cfg["targets"][0]["pattern"] = "**/*.md"
    cfg["targets"].append({"docs_dir": folder, "id_file": ".other/state.id", "profile": "lab" if nested else "default"})
    cfg["profiles"] = {"lab": {"url": "https://other.invalid", "api_key": "another"}}
    path.write_text(yaml.safe_dump(cfg))
    dest = tmp_path / folder / "note.md"
    dest.parent.mkdir()
    if nested:
        (tmp_path / "docs/note.md").rename(dest)
    dest.write_text("keep")
    (tmp_path / ".other").mkdir()
    (tmp_path / ".other/mapping.json").write_text('{"note.md": 43}')
    project.target, project.dir, project.id = "docs", "docs" if nested else "other", None
    project.force, project.dry_run = True, False
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.base_url = "https://example.invalid"
        factory.return_value.get_item.return_value = {"title": "note", "body": "foreign"}
        res = cli.run_pull(project)
    assert res.exit_code == 1 and dest.read_text() == "keep"


def test_clone_recovery_hides_http_url(project, tmp_path, monkeypatch, capsys):
    import requests
    monkeypatch.setenv("ELABFTW_API_KEY", "private-test-key")
    project.id, project.entity, project.dir = [1], "items", str(tmp_path / "clone")
    project.url, project.no_verify, project.dry_run = "https://example.invalid", False, False
    response = requests.Response()
    response.status_code = 403
    error = requests.HTTPError("https://example.invalid/?sig=private-signature", response=response)
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.get_item.return_value = {"title": "note", "body": "body"}
        factory.return_value.list_uploads.return_value = [{"id": 1, "real_name": "asset.csv"}]
        factory.return_value.download_upload.side_effect = error
        with pytest.raises(RuntimeError) as caught:
            cli.run_clone(project, echo=cli.cli_echo)
    res = caught.value.partial_result
    assert "HTTP 403" in str(caught.value)
    assert any("restore" in line for line in res.messages)
    assert "private-signature" not in str(caught.value) + capsys.readouterr().err + json.dumps(res.to_dict())


def test_asset_cannot_replace_other_document(project, tmp_path):
    path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["targets"][0]["attachments_dir"] = "other"
    cfg["targets"].append({"docs_dir": "other", "id_file": ".other/id"})
    path.write_text(yaml.safe_dump(cfg))
    (tmp_path / ".other").mkdir()
    (tmp_path / ".other/mapping.json").write_text('{"attachment.md":43}')
    (tmp_path / "other").mkdir()
    dest = tmp_path / "other/attachment.md"
    dest.write_text("keep me")
    project.target, project.dir, project.id = "docs", None, None
    project.force, project.dry_run = True, False
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.return_value = {"title": "note", "body": "body"}
        client.list_uploads.return_value = [{"id": 9, "real_name": "attachment.md"}]
        res = cli.run_pull(project)
    assert res.exit_code == 1 and dest.read_text() == "keep me"
    assert json.loads((tmp_path / ".other/mapping.json").read_text()) == {"attachment.md": 43}
    client.download_upload.assert_not_called()


def test_same_target_export_does_not_overwrite_other_id(project, tmp_path):
    cfg_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["targets"][0]["pattern"] = "**/*.md"
    cfg_path.write_text(yaml.safe_dump(cfg))
    sub = tmp_path / "docs/sub"
    sub.mkdir()
    dest = sub / "note.md"
    (tmp_path / "docs/note.md").rename(dest)
    project.target, project.dir, project.id, project.entity = "docs", "docs/sub", [1], "items"
    project.force, project.dry_run = True, False
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.get_item.return_value = {"title": "note", "body": "foreign"}
        res = cli.run_pull(project)
    assert res.exit_code == 1 and dest.read_text() == "# note"
    assert json.loads((tmp_path / ".ids/mapping.json").read_text()) == {"note.md": 42}


def test_child_target_can_update_its_own_document(project, tmp_path):
    cfg_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["targets"].append({"docs_dir": "docs/sub", "id_file": ".child/id"})
    cfg_path.write_text(yaml.safe_dump(cfg))
    dest = tmp_path / "docs/sub/note.md"
    dest.parent.mkdir()
    dest.write_text("child")
    (tmp_path / ".child").mkdir()
    (tmp_path / ".child/mapping.json").write_text('{"note.md": 7}')
    project.target, project.dir, project.id = "docs/sub", None, None
    project.force, project.dry_run = True, False
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.return_value = {"title": "note", "body": "updated child"}
        client.list_uploads.return_value = []
        res = cli.run_pull(project)
    assert res.exit_code == 0 and "updated child" in dest.read_text()
    assert (tmp_path / "docs/note.md").read_text() == "# note"


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("blocked_by_file", [False, True])
def test_image_directory_conflict_before_transaction(project, tmp_path, dry_run, blocked_by_file):
    cfg_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    if blocked_by_file:
        (tmp_path / "docs/images").write_text("keep")
    else:
        cfg["targets"].append({"docs_dir": "docs/images", "entity": "experiments"})
    cfg_path.write_text(yaml.safe_dump(cfg))
    project.target, project.entity, project.id, project.dir = "docs", "items", [3, 4], None
    project.force, project.dry_run = True, dry_run
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.side_effect = [{"title": "bad", "body": '<img src="/uploads/99">'},
                                      {"title": "good", "body": "body"}]
        client.list_uploads.return_value = [{"id": 99, "real_name": "abc.png"}]
        res = cli.run_pull(project)
    assert res.data["failed"] == res.data["pulled"] == 1
    assert (tmp_path / "docs/images").is_file() == blocked_by_file
    assert not (tmp_path / ".elab-sync-recovery.json").exists()
    assert (tmp_path / "docs/good.md").exists() != dry_run


@pytest.mark.parametrize("tracked", [True, False])
def test_pull_rejects_new_duplicate_for_recursive_parent(project, tmp_path, tracked):
    if not tracked:
        (tmp_path / ".ids/mapping.json").write_text("{}")
    path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["targets"][0]["pattern"] = "**/*.md"
    cfg["targets"].append({"docs_dir": "docs/sub", "id_file": ".child/id"})
    path.write_text(yaml.safe_dump(cfg))
    project.target, project.entity, project.id, project.dir = "docs/sub", "items", [7], None
    project.dry_run = False
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.get_item.return_value = {"title": "note", "body": "child"}
        res = cli.run_pull(project)
    assert res.exit_code == 1 and not (tmp_path / "docs/sub/note.md").exists()
    assert (tmp_path / "docs/note.md").read_text() == "# note"


def test_pull_compares_existing_case_alias_by_identity(project, tmp_path):
    tracked = tmp_path / "docs/note.md"
    alias = tracked.with_name("NOTE.md")
    if not alias.exists():
        alias.hardlink_to(tracked)
    project.target, project.entity, project.id, project.dir = "docs", "items", [11], None
    project.force, project.dry_run = True, False
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.get_item.return_value = {"title": "NOTE", "body": "wrong"}
        res = cli.run_pull(project)
    assert res.exit_code == 1 and alias.read_text() == tracked.read_text() == "# note"


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("destination", ["docs", "docs/sub", "docs/new.md"])
def test_pull_rejects_attachment_named_after_new_document(project, tmp_path, dry_run, destination):
    cfg_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["targets"][0].update(attachments_dir=destination, pattern="**/*.md")
    cfg_path.write_text(yaml.safe_dump(cfg))
    project.target, project.entity, project.id, project.dir = "docs", "items", [7], None
    project.dry_run = dry_run
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.get_item.return_value = {"title": "new", "body": "body"}
        client.list_uploads.return_value = [{"id": 3, "real_name": "new.md"}]
        res = cli.run_pull(project)
    assert res.exit_code == 1 and not (tmp_path / "docs/new.md").exists()
    assert not (tmp_path / ".elab-sync-recovery.json").exists()
    client.download_upload.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
def test_pull_rejects_two_uploads_for_single_image(project, tmp_path, dry_run):
    project.target, project.entity, project.id, project.dir = "docs", "items", [7], None
    project.dry_run = dry_run
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.get_item.return_value = {"title": "picture", "body": '<img src="/uploads/1"><img src="/uploads/2">'}
        client.list_uploads.return_value = [{"id": i, "real_name": "sample.png"} for i in (1, 2)]
        res = cli.run_pull(project)
    assert res.exit_code == 1 and not (tmp_path / "docs/picture.md").exists()
    assert not (tmp_path / "docs/images").exists()
    client.download_upload.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("other_name", ["table.csv", "Table.csv"])
def test_batch_pull_prevents_overwrite_between_articles(project, tmp_path, dry_run, other_name):
    path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["targets"][0]["attachments_dir"] = "assets"
    path.write_text(yaml.safe_dump(cfg))
    project.target, project.entity, project.id, project.dir = "docs", "items", [7, 8, 9], None
    project.dry_run = dry_run
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.get_item.side_effect = lambda eid: {"title": f"entry{eid}", "body": "body"}
        client.list_uploads.side_effect = lambda entity, eid: (
            [{"id": eid + 20, "real_name": "table.csv" if eid == 7 else other_name}] if eid != 9 else [])
        client.download_upload.side_effect = lambda **kwargs: str(kwargs["entity_id"]).encode()
        res = cli.run_pull(project)
    assert res.data["failed"] == 1 and res.data["pulled"] == 2
    if dry_run:
        assert not (tmp_path / "assets").exists()
    else:
        assert (tmp_path / "assets/table.csv").read_bytes() == b"7"
        assert (tmp_path / "docs/entry9.md").is_file()
        assert not (tmp_path / "docs/entry8.md").exists()

@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("missing_directory", [False, True])
def test_batch_protects_previously_pulled_asset_before_owner_is_processed(project, tmp_path, dry_run, missing_directory):
    path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["targets"][0]["attachments_dir"] = "assets"
    path.write_text(yaml.safe_dump(cfg))
    project.target, project.entity, project.id, project.dir = "docs", "items", [7], None
    project.dry_run = False
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.side_effect = lambda eid: {"title": f"entry{eid}", "body": "body"}
        client.list_uploads.side_effect = lambda entity, eid: [{"id": eid * 10, "real_name": "table.csv"}]
        client.download_upload.return_value = b"original"
        assert cli.run_pull(project).exit_code == 0
        (tmp_path / "assets/table.csv").write_bytes(b"local changes")
        (tmp_path / "docs/entry7.md").write_text("<<<<<<< local\n=======\n>>>>>>> remote")
        if missing_directory:
            (tmp_path / "assets/table.csv").unlink()
            (tmp_path / "assets").rmdir()
        project.id, project.dry_run = [8, 7], dry_run
        res = cli.run_pull(project)
    assert "error" in res.data["documents"][0]
    if not missing_directory:
        assert (tmp_path / "assets/table.csv").read_bytes() == b"local changes"
    assert not (tmp_path / "docs/entry8.md").exists()


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("tracked", [False, True])
def test_pull_batch_can_reuse_renamed_document_path(project, tmp_path, dry_run, tracked):
    if tracked:
        (tmp_path / "docs/beta.md").write_text("second")
        (tmp_path / ".ids/mapping.json").write_text('{"note.md":42,"beta.md":8}')
    project.target, project.entity, project.id, project.dir = "docs", "items", [42, 8], None
    project.force, project.dry_run = True, dry_run
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.side_effect = lambda eid: {"title": "renamed" if eid == 42 else "note", "body": "body"}
        client.list_uploads.return_value = []
        res = cli.run_pull(project)
    assert res.exit_code == 0 and res.data["pulled"] == 2
    if not dry_run:
        assert json.loads((tmp_path / ".ids/mapping.json").read_text()) == {"renamed.md": 42, "note.md": 8}


@pytest.mark.parametrize("same_directory", [True, False])
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("record", ["broken", '{"remote":{}}'])
def test_unreadable_attachment_records_only_block_affected_destinations(project, tmp_path, same_directory, dry_run, record):
    config_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    cfg["targets"][0]["attachments_dir"] = "assets"
    cfg["targets"].append({"docs_dir": "other", "id_file": ".other/id",
                           "attachments_dir": "assets" if same_directory else "other_assets"})
    config_path.write_text(yaml.safe_dump(cfg))
    (tmp_path / ".other").mkdir()
    (tmp_path / ".other/mapping.json").write_text('{"old.md":55}')
    (tmp_path / ".other/old.md.state.json").write_text(record)
    (tmp_path / "other").mkdir()
    (tmp_path / "other/old.md").write_text("keep")
    project.target, project.entity, project.id, project.dir = "docs", "items", [7], None
    project.dry_run = dry_run
    with patch.object(cli, "ELabFTWClient") as factory:
        factory.return_value.get_item.return_value = {"title": "new", "body": "body"}
        factory.return_value.list_uploads.return_value = [{"id": 4, "real_name": "report.csv"}]
        factory.return_value.base_url = "https://example.invalid"
        factory.return_value.download_upload.return_value = b"csv"
        res = cli.run_pull(project)
    assert res.exit_code == int(same_directory)
    assert not (tmp_path / ".elab-sync-recovery.json").exists()
    assert (tmp_path / "docs/new.md").exists() == (not dry_run and not same_directory)


def test_shared_attachment_still_checks_each_upload_id(project, tmp_path):
    from hashlib import sha256
    config_path = tmp_path / ".elab-sync.yaml"
    cfg = yaml.safe_load(config_path.read_text())
    cfg["targets"][0]["attachments_dir"] = "assets"
    config_path.write_text(yaml.safe_dump(cfg))
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/report.csv").write_bytes(b"shared")
    (tmp_path / ".ids/mapping.json").write_text('{"note.md":42,"other.md":43}')
    digest = sha256(b"shared").hexdigest()
    entries = [{"id": i, "real_name": "report.csv", "hash": digest} for i in (1, 2)]
    for name in ("note.md", "other.md"):
        (tmp_path / ".ids" / f"{name}.state.json").write_text(json.dumps(
            {"server": "https://example.invalid", "remote": {"uploads": entries[:1]}}))
    project.target, project.entity, project.id, project.dir = "docs", "items", [42], None
    project.dry_run = True
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.return_value = {"title": "note", "body": "body"}
        client.list_uploads.return_value = entries
        res = cli.run_pull(project)
    assert res.exit_code == 1 and "異なる添付 ID" in res.data["documents"][0]["error"]


def test_rename_protects_new_file_at_released_path(project, tmp_path):
    project.target, project.entity, project.id, project.dir = "docs", "items", [42, 8], None
    project.force, project.dry_run = True, False
    original = cli._pull_entity_to_target
    released = tmp_path / "docs/note.md"
    def pull(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[5] == 42:
            released.write_text("editor save")
        return result
    with patch.object(cli, "ELabFTWClient") as factory, patch.object(cli, "_pull_entity_to_target", side_effect=pull):
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.side_effect = lambda eid: {"title": "renamed" if eid == 42 else "note", "body": "body"}
        client.list_uploads.return_value = []
        res = cli.run_pull(project)
    assert res.data["pulled"] == res.data["failed"] == 1
    assert released.read_text() == "editor save"


@pytest.mark.parametrize("asset", [True, False])
def test_pull_preserves_recreated_file_during_download(project, tmp_path, asset):
    cfg = Path(project.config)
    settings = yaml.safe_load(cfg.read_text())
    settings["targets"][0]["attachments_dir"] = "docs" if asset else "attachments"
    cfg.write_text(yaml.safe_dump(settings))
    project.target, project.entity, project.id, project.dir = "docs", "items", [42, 8], None
    project.force, project.dry_run = True, False
    released = tmp_path / "docs/note.md"

    def download(**kwargs):
        released.write_text("editor save")
        return b"remote attachment"

    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.base_url = "https://example.invalid"
        client.get_item.side_effect = lambda eid: {
            "title": "renamed" if eid == 42 else ("second" if asset else "note"), "body": "body"}
        client.list_uploads.side_effect = lambda entity, eid: (
            [] if eid == 42 else [{"id": 7, "real_name": "note.md" if asset else "data.csv"}])
        client.download_upload.side_effect = download
        target = cli.load_config(cfg).targets[0]
        cli.EachDocsSyncer(client, target, tmp_path)._save_baseline(
            "note.md", "# note", {"title": "note", "body": "# note"}, [], base="# note")
        res = cli.run_pull(project)
    assert res.data["pulled"] == res.data["failed"] == 1
    assert released.read_text() == "editor save"


def test_missing_state_keeps_existing_attachment(project, tmp_path):
    cfg = Path(project.config)
    settings = yaml.safe_load(cfg.read_text())
    settings["targets"][0]["attachments_dir"] = "assets"
    cfg.write_text(yaml.safe_dump(settings))
    existing = tmp_path / "assets/table.csv"
    existing.parent.mkdir()
    existing.write_bytes(b"local edit")
    project.target, project.entity, project.id, project.dir = "docs", "items", [8], None
    project.force, project.dry_run = True, False
    with patch.object(cli, "ELabFTWClient") as factory:
        client = factory.return_value
        client.get_item.return_value = {"title": "second", "body": "body"}
        client.list_uploads.return_value = [{"id": 9, "real_name": "table.csv"}]
        res = cli.run_pull(project)
    assert res.exit_code == 1
    assert existing.read_bytes() == b"local edit"
    client.download_upload.assert_not_called()


def test_unreadable_target_never_redirects_explicit_link(tmp_path):
    from elab_doc_sync.sync import LinkTargets, _rewrite_local_links

    intended = tmp_path / "a/ref.md"
    intended.parent.mkdir()
    intended.write_text("unreadable tracking record")
    links = LinkTargets("https://example.invalid")
    links.add("items", 9, tmp_path / "b/ref.md")
    body = "[reference](../a/ref.md)"
    assert _rewrite_local_links(body, "items", links.base_url, {}, source=tmp_path / "c/doc.md", links=links) == body
