"""Shared fixtures for elab-doc-sync tests."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from elab_doc_sync.client import ELabFTWClient
from elab_doc_sync.config import TargetConfig


@pytest.fixture
def mock_client():
    client = MagicMock(spec=ELabFTWClient)
    client.base_url = "https://elab.example.com"
    client.create_item.return_value = 1
    client.create_experiment.return_value = 1
    client.get_item.return_value = {"id": 1, "title": "test", "body": "<p>hello</p>"}
    client.get_experiment.return_value = {"id": 1, "title": "test", "body": "<p>hello</p>"}
    client.upload_file.return_value = {"id": 1, "filename": "img.png", "url": "https://elab.example.com/dl/img.png"}
    client.list_items.return_value = [{"id": 1}, {"id": 2}]
    client.list_experiments.return_value = [{"id": 1}]
    return client


@pytest.fixture
def merge_target(tmp_path):
    return TargetConfig(
        title="Test Doc",
        docs_dir="docs/",
        id_file=str(tmp_path / ".elab-sync-ids" / "default.id"),
        pattern="*.md",
        mode="merge",
        entity="items",
    )


@pytest.fixture
def each_target(tmp_path):
    return TargetConfig(
        title="",
        docs_dir="docs/",
        id_file=str(tmp_path / ".elab-sync-ids" / "default.id"),
        pattern="*.md",
        mode="each",
        entity="items",
    )


@pytest.fixture
def docs_dir(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.md").write_text("# Doc A\n\nContent A", encoding="utf-8")
    (d / "b.md").write_text("# Doc B\n\nContent B", encoding="utf-8")
    return d


@pytest.fixture
def sample_config_path(tmp_path):
    data = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "test-key", "verify_ssl": False},
        "targets": [{"title": "Test", "docs_dir": "docs/", "pattern": "*.md", "mode": "merge", "entity": "items"}],
    }
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return p
