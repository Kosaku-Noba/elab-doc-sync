"""Tests for config.py (C-01 ~ C-08)."""

import os
from pathlib import Path

import pytest
import yaml

from elab_doc_sync.config import load_config


def _write_config(tmp_path, data):
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _base_data(**overrides):
    d = {
        "elabftw": {"url": "https://elab.example.com", "api_key": "key123", "verify_ssl": False},
        "targets": [{"title": "T", "docs_dir": "docs/", "mode": "merge", "entity": "items"}],
    }
    d.update(overrides)
    return d


# C-01
def test_load_config_normal(tmp_path):
    cfg = load_config(_write_config(tmp_path, _base_data()))
    assert cfg.url == "https://elab.example.com"
    assert cfg.api_key == "key123"
    assert len(cfg.targets) == 1
    assert cfg.targets[0].title == "T"


# C-02
def test_env_api_key_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("ELABFTW_API_KEY", "env-key")
    cfg = load_config(_write_config(tmp_path, _base_data()))
    assert cfg.api_key == "env-key"


# C-03
def test_missing_url(tmp_path):
    data = _base_data()
    data["elabftw"]["url"] = ""
    with pytest.raises(SystemExit):
        load_config(_write_config(tmp_path, data))


# C-04
def test_missing_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ELABFTW_API_KEY", raising=False)
    data = _base_data()
    data["elabftw"]["api_key"] = ""
    with pytest.raises(SystemExit):
        load_config(_write_config(tmp_path, data))


# C-05
def test_no_targets(tmp_path):
    data = _base_data()
    data["targets"] = []
    with pytest.raises(SystemExit):
        load_config(_write_config(tmp_path, data))


# C-06
def test_missing_config_file(tmp_path):
    with pytest.raises(SystemExit):
        load_config(tmp_path / "nonexistent.yaml")


# C-07
def test_default_mode_entity(tmp_path):
    data = _base_data()
    del data["targets"][0]["mode"]
    del data["targets"][0]["entity"]
    cfg = load_config(_write_config(tmp_path, data))
    assert cfg.targets[0].mode == "merge"
    assert cfg.targets[0].entity == "items"


# C-08
def test_each_experiments(tmp_path):
    data = _base_data()
    data["targets"][0]["mode"] = "each"
    data["targets"][0]["entity"] = "experiments"
    cfg = load_config(_write_config(tmp_path, data))
    assert cfg.targets[0].mode == "each"
    assert cfg.targets[0].entity == "experiments"
