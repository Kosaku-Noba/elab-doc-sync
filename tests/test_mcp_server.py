"""本物の stdio クライアントから一時プロジェクトのツールを呼ぶ。"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import timedelta

import pytest
import yaml

mcp = pytest.importorskip("mcp")
from mcp.client.stdio import stdio_client


def test_stdio_tools(tmp_path):
    cfg = tmp_path / ".elab-sync.yaml"
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# A")
    state = tmp_path / ".ids"
    state.mkdir()
    mapping = state / "mapping.json"
    mapping.write_text('{"a.md":42}')
    secret = "private-test-token"
    cfg.write_text(yaml.safe_dump({
        "elabftw": {"url": "https://example.invalid", "api_key": secret},
        "targets": [{"docs_dir": "docs", "id_file": ".ids/default.id"}],
    }))

    async def run():
        from elab_doc_sync import mcp_server
        src = Path(mcp_server.__file__).resolve().parents[1]
        params = mcp.StdioServerParameters(command=sys.executable,
                    args=["-m", "elab_doc_sync.mcp_server", "--config", str(cfg)],
                    env={"PYTHONPATH": str(src)})
        async with stdio_client(params) as streams, mcp.ClientSession(*streams, read_timeout_seconds=timedelta(seconds=15)) as client:
            await client.initialize()
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(tools) == set(mcp_server.OPERATIONS)
            assert not {"init", "update", "profile_add", "profile_remove", "entity_status_set"} & tools.keys()
            from jsonschema.validators import validator_for
            for tool in tools.values():
                validator_for(tool.inputSchema).check_schema(tool.inputSchema)
                props = tool.inputSchema["properties"]
                assert "config" not in props and "api_key" not in props
                if not tool.annotations.readOnlyHint:
                    assert props["dry_run"]["default"] is True
            assert (await client.call_tool("pull", {})).isError
            assert (await client.call_tool("rm", {"id": [], "entity": "items"})).isError
            assert (await client.call_tool("rm", {"files": ["docs/a.md"], "dry_run": "false"})).isError
            assert (await client.call_tool("clone", {"id": [1], "url": "https://example.invalid"})).isError
            preview = await client.call_tool("rm", {"files": ["docs/a.md"], "local": True})
            assert not preview.isError and preview.structuredContent["data"]["dry_run"]
            assert (docs / "a.md").is_file() and json.loads(mapping.read_text()) == {"a.md": 42}
            done = await client.call_tool("rm", {"id": [42], "entity": "items", "dry_run": False})
            assert not done.isError and done.structuredContent["data"]["documents"][0]["tracking"] == "untracked"
            assert (docs / "a.md").is_file() and json.loads(mapping.read_text()) == {}
            profiles = await client.call_tool("profile_list", {})
            assert secret not in profiles.model_dump_json()
            cfg.write_text("invalid: [")
            backups = await client.call_tool("backup_list", {})
            assert not backups.isError
            backup_id = backups.structuredContent["data"]["backups"][0]["id"]
            assert not (await client.call_tool("restore", {"backup_id": backup_id})).isError
            cfg.unlink()
            error = await client.call_tool("status", {})
            assert error.isError and error.structuredContent["exit_code"] == 2
            assert not (await client.call_tool("backup_list", {})).isError
    asyncio.run(run())


def test_remote_preview_apply_and_partial_failure(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from mcp.shared.memory import create_connected_server_and_client_session
    from elab_doc_sync import cli, mcp_server
    from elab_doc_sync.safety import project_lock

    cfg = tmp_path / ".elab-sync.yaml"
    key = "private-remote-key"
    cfg.write_text(yaml.safe_dump({
        "elabftw": {"url": "https://example.invalid", "api_key": key},
        "targets": [{"docs_dir": "docs", "id_file": ".ids/default.id"}],
    }))
    (tmp_path / ".ids").mkdir()
    (tmp_path / ".ids/mapping.json").write_text('{"a.md": 1, "b.md": 2}')
    remote = MagicMock(base_url="https://example.invalid")
    remote.get_tags.return_value = []
    remote.add_tag.side_effect = [None, ValueError(f"invalid header {key!r}")]
    monkeypatch.setattr(cli, "ELabFTWClient", lambda *args: remote)

    async def run():
        server = mcp_server.create_server(cfg)
        async with create_connected_server_and_client_session(server) as client:
            preview = await client.call_tool("tag_add", {"tag_name": "sample"})
            assert preview.structuredContent["data"]["entities"][0]["result"] == "would_add"
            remote.add_tag.assert_not_called()
            with project_lock(tmp_path):
                locked = await client.call_tool("tag_add", {"tag_name": "sample", "dry_run": False})
                assert locked.isError
                remote.add_tag.assert_not_called()
            failed = await client.call_tool("tag_add", {"tag_name": "sample", "dry_run": False})
            assert failed.isError and key not in failed.model_dump_json()
            first, second = failed.structuredContent["data"]["entities"]
            assert first["result"] == "added" and "result" not in second
    asyncio.run(run())
