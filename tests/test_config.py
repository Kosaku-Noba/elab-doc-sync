"""Tests for config.py (C-01 ~ C-16)."""

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


# C-09: tags フィールドの読み込み
def test_config_tags(tmp_path):
    from elab_doc_sync.config import load_config
    data = {
        "elabftw": {"url": "https://x.com", "api_key": "k"},
        "targets": [{"title": "T", "docs_dir": "docs/", "tags": ["alpha", "beta"]}],
    }
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    config = load_config(p)
    assert config.targets[0].tags == ["alpha", "beta"]


# C-10: tags フィールド省略時はデフォルト空リスト
def test_config_tags_default(tmp_path):
    from elab_doc_sync.config import load_config
    data = {
        "elabftw": {"url": "https://x.com", "api_key": "k"},
        "targets": [{"title": "T", "docs_dir": "docs/"}],
    }
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    config = load_config(p)
    assert config.targets[0].tags == []


# C-11: entity に resources を指定すると items に正規化される
def test_config_entity_resources_alias(tmp_path):
    from elab_doc_sync.config import load_config
    data = {
        "elabftw": {"url": "https://x.com", "api_key": "k"},
        "targets": [{"title": "T", "docs_dir": "docs/", "entity": "resources"}],
    }
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    config = load_config(p)
    assert config.targets[0].entity == "items"


# C-12: body_format 未指定時は html（既存設定互換 — load_config 経路）
def test_config_body_format_default(tmp_path):
    from elab_doc_sync.config import load_config
    data = {
        "elabftw": {"url": "https://x.com", "api_key": "k"},
        "targets": [{"title": "T", "docs_dir": "docs/"}],
    }
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    config = load_config(p)
    assert config.targets[0].body_format == "html"


# C-13: body_format=md を明示指定すると md になる
def test_config_body_format_md(tmp_path):
    from elab_doc_sync.config import load_config
    data = {
        "elabftw": {"url": "https://x.com", "api_key": "k"},
        "targets": [{"title": "T", "docs_dir": "docs/", "body_format": "md"}],
    }
    p = tmp_path / ".elab-sync.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    config = load_config(p)
    assert config.targets[0].body_format == "md"


# C-14: cp932 で保存された設定ファイルをフォールバックで読めること
def test_load_config_cp932_fallback(tmp_path):
    """cp932 で保存された設定ファイルをフォールバックで読めること。"""
    data = _base_data()
    data["targets"][0]["title"] = "実験メモ"
    p = tmp_path / ".elab-sync.yaml"
    p.write_bytes(yaml.dump(data, allow_unicode=True).encode("cp932"))
    cfg = load_config(p)
    assert cfg.targets[0].title == "実験メモ"


# C-15: UTF-8 ファイルは cp932 フォールバックなしで読めること
def test_read_yaml_text_utf8_preferred(tmp_path):
    """UTF-8 ファイルは cp932 フォールバックなしで読めること。"""
    from elab_doc_sync.config import _read_yaml_text
    p = tmp_path / "test.yaml"
    p.write_text("title: テスト", encoding="utf-8")
    assert "テスト" in _read_yaml_text(p)


# C-16: cp932 設定を _ensure_target_in_config で読み→UTF-8 で再保存
def test_ensure_target_rewrites_cp932_to_utf8(tmp_path):
    from elab_doc_sync.cli import _ensure_target_in_config
    data = _base_data()
    data["targets"][0]["title"] = "実験メモ"
    p = tmp_path / ".elab-sync.yaml"
    p.write_bytes(yaml.dump(data, allow_unicode=True).encode("cp932"))
    config = load_config(p)
    _ensure_target_in_config(p, "experiments", config)
    # 再保存後は UTF-8 で読め、日本語タイトルが保持されること
    raw = p.read_text(encoding="utf-8")
    assert "experiments" in raw
    assert "実験メモ" in raw
