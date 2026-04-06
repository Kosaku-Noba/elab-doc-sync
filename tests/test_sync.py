"""Tests for sync.py (S-01 ~ S-44)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elab_doc_sync.sync import (
    _compute_hash, _count_local_images, _md_to_html, _rewrite_images,
    _download_images, _normalize_remote_image_urls, _image_local_name,
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


# ── FR-15 タグ同期テスト ─────────────────────────────────

from elab_doc_sync.sync import _sync_tags


# S-45: タグ同期 — 新規タグを追加
def test_sync_tags_adds_missing():
    client = MagicMock()
    client.get_tags.return_value = [{"id": 1, "tag": "existing"}]
    _sync_tags(client, "items", 42, ["existing", "new-tag"])
    client.add_tag.assert_called_once_with("items", 42, "new-tag")


# S-46: タグ同期 — 全て既存なら何もしない
def test_sync_tags_no_op():
    client = MagicMock()
    client.get_tags.return_value = [{"id": 1, "tag": "a"}, {"id": 2, "tag": "b"}]
    _sync_tags(client, "items", 42, ["a", "b"])
    client.add_tag.assert_not_called()


# S-47: タグ同期 — 空リストなら何もしない
def test_sync_tags_empty():
    client = MagicMock()
    _sync_tags(client, "items", 42, [])
    client.get_tags.assert_not_called()


# S-48: タグ同期 — 既存タグを外さない（追記のみ）
def test_sync_tags_does_not_remove():
    client = MagicMock()
    client.get_tags.return_value = [{"id": 1, "tag": "extra"}, {"id": 2, "tag": "wanted"}]
    _sync_tags(client, "items", 42, ["wanted"])
    client.untag_by_name.assert_not_called()


# S-49: タグ同期 — API 失敗時は例外を握りつぶす
def test_sync_tags_best_effort(capsys):
    client = MagicMock()
    client.get_tags.side_effect = Exception("API error")
    _sync_tags(client, "items", 42, ["tag1"])
    captured = capsys.readouterr()
    assert "タグ同期に失敗" in captured.out


# ── _download_images ─────────────────────────────────────

# S-45
def test_download_images_replaces_url(tmp_path):
    client = MagicMock()
    client.list_uploads.return_value = [
        {"id": 10, "long_name": "abc123.png", "real_name": "photo.png", "storage": "1"},
    ]
    client.download_upload.return_value = b"\x89PNG"
    body = "![alt](https://elab.example.com/app/download.php?f=abc123.png&name=photo.png&storage=1)"
    result = _download_images(body, "items", 42, client, tmp_path)
    assert "images/items_42_photo.png" in result
    assert (tmp_path / "images" / "items_42_photo.png").exists()
    client.download_upload.assert_called_once_with("items", 42, 10)


# S-46
def test_download_images_skips_non_elab_url():
    client = MagicMock()
    client.list_uploads.return_value = []
    body = "![a](https://example.com/img.png)"
    result = _download_images(body, "items", 1, client, Path("."))
    assert result == body
    client.download_upload.assert_not_called()


# S-47
def test_download_images_no_duplicate_download(tmp_path):
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "items_42_photo.png").write_bytes(b"\x89PNG")
    client = MagicMock()
    client.list_uploads.return_value = [
        {"id": 10, "long_name": "abc123.png", "real_name": "photo.png", "storage": "1"},
    ]
    body = "![alt](https://elab.example.com/app/download.php?f=abc123.png&name=photo.png&storage=1)"
    _download_images(body, "items", 42, client, tmp_path)
    client.download_upload.assert_not_called()


# S-48: 異なるエンティティの同名画像が衝突しない
def test_download_images_entity_id_namespace(tmp_path):
    client = MagicMock()
    client.list_uploads.return_value = [
        {"id": 10, "long_name": "abc.png", "real_name": "photo.png", "storage": "1"},
    ]
    client.download_upload.return_value = b"data1"
    body = "![a](https://elab.example.com/app/download.php?f=abc.png&name=photo.png&storage=1)"
    r1 = _download_images(body, "items", 1, client, tmp_path)
    client.list_uploads.return_value = [
        {"id": 20, "long_name": "def.png", "real_name": "photo.png", "storage": "1"},
    ]
    client.download_upload.return_value = b"data2"
    body2 = "![a](https://elab.example.com/app/download.php?f=def.png&name=photo.png&storage=1)"
    r2 = _download_images(body2, "items", 2, client, tmp_path)
    assert "images/items_1_photo.png" in r1
    assert "images/items_2_photo.png" in r2
    assert (tmp_path / "images" / "items_1_photo.png").read_bytes() == b"data1"
    assert (tmp_path / "images" / "items_2_photo.png").read_bytes() == b"data2"


# ── _normalize_remote_image_urls ─────────────────────────

# S-49
def test_normalize_remote_image_urls():
    client = MagicMock()
    client.list_uploads.return_value = [
        {"id": 10, "long_name": "abc123.png", "real_name": "photo.png", "storage": "1"},
    ]
    body = "![alt](https://elab.example.com/app/download.php?f=abc123.png&name=photo.png&storage=1)"
    result = _normalize_remote_image_urls(body, "items", 42, client)
    assert result == "![alt](images/items_42_photo.png)"


# S-50
def test_normalize_preserves_non_elab():
    client = MagicMock()
    client.list_uploads.return_value = []
    body = "![a](https://example.com/img.png)"
    assert _normalize_remote_image_urls(body, "items", 1, client) == body


# ── _rewrite_images: 既存 upload 再利用 ─────────────────

# S-51
def test_rewrite_images_reuses_existing_upload(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "photo.png").write_bytes(b"\x89PNG")
    client = MagicMock()
    client.base_url = "https://elab.example.com"
    client.list_uploads.return_value = [
        {"id": 10, "real_name": "photo.png", "long_name": "abc123.png", "storage": "1", "filesize": 4},
    ]
    result = _rewrite_images("![a](photo.png)", "items", 1, client, docs, tmp_path)
    client.upload_file.assert_not_called()
    assert "app/download.php?f=abc123.png" in result


# S-52
def test_rewrite_images_uploads_new_file(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "new.png").write_bytes(b"\x89PNG")
    client = MagicMock()
    client.list_uploads.return_value = []
    client.upload_file.return_value = {"url": "https://elab.example.com/dl/new.png"}
    result = _rewrite_images("![a](new.png)", "items", 1, client, docs, tmp_path)
    client.upload_file.assert_called_once()
    assert "https://elab.example.com/dl/new.png" in result


# S-53: 同名だがサイズが異なる画像は再アップロードされる
def test_rewrite_images_reuploads_changed_file(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "photo.png").write_bytes(b"\x89PNG_UPDATED")  # 12 bytes
    client = MagicMock()
    client.base_url = "https://elab.example.com"
    client.list_uploads.return_value = [
        {"id": 10, "real_name": "photo.png", "long_name": "abc123.png", "storage": "1", "filesize": 4},
    ]
    client.upload_file.return_value = {"url": "https://elab.example.com/dl/new_photo.png"}
    result = _rewrite_images("![a](photo.png)", "items", 1, client, docs, tmp_path)
    client.upload_file.assert_called_once()
    assert "new_photo.png" in result


# S-54: list_uploads 失敗時に _download_images は body をそのまま返す
def test_download_images_list_uploads_failure():
    client = MagicMock()
    client.list_uploads.side_effect = Exception("API error")
    body = "![a](https://elab.example.com/app/download.php?f=abc.png&name=x.png&storage=1)"
    result = _download_images(body, "items", 1, client, Path("."))
    assert result == body


# S-55: list_uploads 失敗時に _normalize_remote_image_urls は body をそのまま返す
def test_normalize_list_uploads_failure():
    client = MagicMock()
    client.list_uploads.side_effect = Exception("API error")
    body = "![a](https://elab.example.com/app/download.php?f=abc.png&name=x.png&storage=1)"
    result = _normalize_remote_image_urls(body, "items", 1, client)
    assert result == body


# S-56: _image_local_name に entity 種別が含まれる
def test_image_local_name_includes_entity():
    assert _image_local_name("items", 1, "photo.png") == "items_1_photo.png"
    assert _image_local_name("experiments", 1, "photo.png") == "experiments_1_photo.png"
    assert _image_local_name("items", 1, "photo.png") != _image_local_name("experiments", 1, "photo.png")
