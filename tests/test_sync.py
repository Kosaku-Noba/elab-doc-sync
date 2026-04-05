"""Tests for sync.py (S-01 ~ S-44)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elab_doc_sync.sync import (
    _compute_hash, _count_local_images, _md_to_html, _rewrite_images,
    ConflictError, DocsSyncer, EachDocsSyncer,
)
from elab_doc_sync.config import TargetConfig


# ── Utilities ────────────────────────────────────────────

# S-01
def test_compute_hash():
    assert _compute_hash("hello") == _compute_hash("hello")
    assert _compute_hash("hello") != _compute_hash("world")
    assert len(_compute_hash("x")) == 16


# S-02
def test_count_local_images():
    body = "![a](img.png) ![b](https://x.com/i.png) ![c](sub/pic.jpg)"
    assert _count_local_images(body) == 2


# S-03
def test_md_to_html():
    html = _md_to_html("# Hello\n\nworld")
    assert "<h1>" in html or "<h1" in html
    assert "world" in html


# ── _rewrite_images ──────────────────────────────────────

# S-25
def test_rewrite_images_upload(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "img.png").write_bytes(b"\x89PNG")
    client = MagicMock()
    client.upload_file.return_value = {"url": "https://elab/dl/img.png"}
    result = _rewrite_images("![alt](img.png)", "items", 1, client, docs, tmp_path)
    client.upload_file.assert_called_once()
    assert "https://elab/dl/img.png" in result


# S-26
def test_rewrite_images_http_preserved():
    client = MagicMock()
    body = "![a](https://example.com/img.png)"
    result = _rewrite_images(body, "items", 1, client, Path("."), Path("."))
    client.upload_file.assert_not_called()
    assert result == body


# S-27
def test_rewrite_images_missing_file(tmp_path):
    client = MagicMock()
    result = _rewrite_images("![a](missing.png)", "items", 1, client, tmp_path, tmp_path)
    assert "missing.png" in result
    client.upload_file.assert_not_called()


# S-28
def test_rewrite_images_project_root_fallback(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "root.png").write_bytes(b"\x89PNG")
    client = MagicMock()
    client.upload_file.return_value = {"url": "https://elab/dl/root.png"}
    result = _rewrite_images("![a](root.png)", "items", 1, client, docs, tmp_path)
    client.upload_file.assert_called_once()


# ── DocsSyncer (merge) ───────────────────────────────────

def _make_merge_syncer(tmp_path, mock_client):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    target = TargetConfig(title="Test", docs_dir="docs/", id_file=str(tmp_path / ".ids" / "default.id"))
    return DocsSyncer(mock_client, target, tmp_path), docs


# S-10
def test_collect_docs(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("AAA", encoding="utf-8")
    (docs / "b.md").write_text("BBB", encoding="utf-8")
    body = syncer.collect_docs()
    assert "AAA" in body and "BBB" in body
    assert "---" in body


# S-11
def test_collect_docs_empty(tmp_path, mock_client):
    syncer, _ = _make_merge_syncer(tmp_path, mock_client)
    with pytest.raises(FileNotFoundError):
        syncer.collect_docs()


# S-12
def test_has_changed_initial(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("x", encoding="utf-8")
    assert syncer.has_changed("x") is True


# S-13
def test_has_changed_no_change(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("x", encoding="utf-8")
    syncer.save_hash("x")
    assert syncer.has_changed("x") is False


# S-14
def test_has_changed_changed(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("x", encoding="utf-8")
    syncer.save_hash("x")
    assert syncer.has_changed("y") is True


# S-15
def test_save_read_hash(tmp_path, mock_client):
    syncer, _ = _make_merge_syncer(tmp_path, mock_client)
    syncer.save_hash("content")
    assert syncer.hash_file.exists()
    assert syncer.hash_file.read_text().strip() == _compute_hash("content")


# S-16
def test_save_read_item_id(tmp_path, mock_client):
    syncer, _ = _make_merge_syncer(tmp_path, mock_client)
    assert syncer.read_item_id() is None
    syncer.save_item_id(42)
    assert syncer.read_item_id() == 42


# S-17
def test_sync_new_entity(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("hello", encoding="utf-8")
    mock_client.create_item.return_value = 10
    mock_client.get_item.return_value = {"id": 10, "body": "<p>hello</p>"}
    result = syncer.sync()
    assert result is True
    assert syncer.read_item_id() == 10
    assert syncer.hash_file.exists()
    assert syncer.remote_hash_file.exists()


# S-18
def test_sync_update(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("v1", encoding="utf-8")
    syncer.save_item_id(5)
    mock_client.get_item.return_value = {"id": 5, "body": "<p>v1</p>"}
    result = syncer.sync()
    assert result is True
    mock_client.update_item.assert_called()


# S-19
def test_sync_skip_no_change(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("same", encoding="utf-8")
    syncer.save_hash("same")
    result = syncer.sync()
    assert result is False


# S-20
def test_sync_force(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("same", encoding="utf-8")
    syncer.save_hash("same")
    syncer.save_item_id(5)
    mock_client.get_item.return_value = {"id": 5, "body": "<p>same</p>"}
    result = syncer.sync(force=True)
    assert result is True


# S-21
def test_sync_deleted_entity(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("x", encoding="utf-8")
    syncer.save_item_id(99)
    mock_client.get_item.side_effect = [Exception("404"), {"id": 20, "body": ""}]
    mock_client.create_item.return_value = 20
    result = syncer.sync()
    assert result is True
    assert syncer.read_item_id() == 20


# S-22
def test_dry_run(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("![img](pic.png)\ncontent", encoding="utf-8")
    info = syncer.dry_run()
    assert info["files"] == 1
    assert info["images"] == 1
    assert info["changed"] is True


# ── Conflict detection ───────────────────────────────────

# S-30
def test_conflict_no_remote_hash(tmp_path, mock_client):
    syncer, _ = _make_merge_syncer(tmp_path, mock_client)
    syncer._check_remote_conflict(1)  # should not raise


# S-31
def test_conflict_hash_match(tmp_path, mock_client):
    syncer, _ = _make_merge_syncer(tmp_path, mock_client)
    mock_client.get_item.return_value = {"id": 1, "body": "<p>x</p>"}
    syncer.save_remote_hash("<p>x</p>")
    syncer._check_remote_conflict(1)  # should not raise


# S-32
def test_conflict_hash_mismatch(tmp_path, mock_client):
    syncer, _ = _make_merge_syncer(tmp_path, mock_client)
    syncer.save_remote_hash("<p>old</p>")
    mock_client.get_item.return_value = {"id": 1, "body": "<p>new</p>"}
    with pytest.raises(ConflictError, match="1"):
        syncer._check_remote_conflict(1)


# S-33
def test_conflict_skipped_with_force(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("x", encoding="utf-8")
    syncer.save_item_id(1)
    syncer.save_remote_hash("<p>old</p>")
    mock_client.get_item.return_value = {"id": 1, "body": "<p>changed</p>"}
    result = syncer.sync(force=True)
    assert result is True


# S-34
def test_remote_hash_saved_after_sync(tmp_path, mock_client):
    syncer, docs = _make_merge_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("x", encoding="utf-8")
    mock_client.create_item.return_value = 1
    mock_client.get_item.return_value = {"id": 1, "body": "<p>x</p>"}
    syncer.sync()
    assert syncer.remote_hash_file.exists()
    assert syncer.remote_hash_file.read_text().strip() == _compute_hash("<p>x</p>")


# ── EachDocsSyncer ───────────────────────────────────────

def _make_each_syncer(tmp_path, mock_client):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    target = TargetConfig(title="", docs_dir="docs/", id_file=str(tmp_path / ".ids" / "default.id"), mode="each")
    return EachDocsSyncer(mock_client, target, tmp_path), docs


# S-40
def test_each_sync_multiple(tmp_path, mock_client):
    syncer, docs = _make_each_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("A", encoding="utf-8")
    (docs / "b.md").write_text("B", encoding="utf-8")
    mock_client.create_item.side_effect = [10, 20]
    mock_client.get_item.side_effect = [{"id": 10, "body": ""}, {"id": 20, "body": ""}]
    updated = syncer.sync()
    assert updated == 2


# S-41
def test_each_sync_skip_unchanged(tmp_path, mock_client):
    syncer, docs = _make_each_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("A", encoding="utf-8")
    (docs / "b.md").write_text("B", encoding="utf-8")
    syncer._save_hash("a.md", "A")
    mock_client.create_item.return_value = 20
    mock_client.get_item.return_value = {"id": 20, "body": ""}
    updated = syncer.sync()
    assert updated == 1  # only b.md


# S-42
def test_each_mapping(tmp_path, mock_client):
    syncer, _ = _make_each_syncer(tmp_path, mock_client)
    syncer._save_mapping({"a.md": 10, "b.md": 20})
    m = syncer._load_mapping()
    assert m == {"a.md": 10, "b.md": 20}


# S-43
def test_each_conflict(tmp_path, mock_client):
    syncer, docs = _make_each_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("A", encoding="utf-8")
    syncer._save_mapping({"a.md": 5})
    syncer._save_remote_hash("a.md", "<p>old</p>")
    mock_client.get_item.return_value = {"id": 5, "body": "<p>new</p>"}
    with pytest.raises(ConflictError):
        syncer.sync()


# S-44
def test_each_remote_hash_saved(tmp_path, mock_client):
    syncer, docs = _make_each_syncer(tmp_path, mock_client)
    (docs / "a.md").write_text("A", encoding="utf-8")
    mock_client.create_item.return_value = 10
    mock_client.get_item.return_value = {"id": 10, "body": "<p>A</p>"}
    syncer.sync()
    hp = syncer._remote_hash_path("a.md")
    assert hp.exists()
    assert hp.read_text().strip() == _compute_hash("<p>A</p>")
