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
