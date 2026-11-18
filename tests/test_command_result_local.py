"""ローカル操作の構造化結果、逐次出力、ロックの回帰テスト。"""

import json
from argparse import Namespace
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
    assert doc["entity_id"] == 42 and doc["path"].endswith("/docs/note.md")
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
    from pathlib import Path
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
