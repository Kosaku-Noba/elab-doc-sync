"""Integration tests against demo.elabftw.net.

Requires ELABFTW_DEMO_API_KEY environment variable or skip.
Run with: ELABFTW_DEMO_API_KEY=<key> UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_integration.py -v

Notes:
- テストは demo 環境に一時的に item を作成し、終了時に削除する
- cleanup が途中失敗した場合は [test] prefix 付き item が残る可能性がある
"""

import hashlib
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from elab_doc_sync.client import ELabFTWClient
from elab_doc_sync.sync import (
    DocsSyncer,
    _download_attachments,
    _download_images,
    _rewrite_images,
    _sync_attachments,
)
from elab_doc_sync.config import TargetConfig

DEMO_URL = "https://demo.elabftw.net"
API_KEY = os.environ.get("ELABFTW_DEMO_API_KEY", "")

pytestmark = [
    pytest.mark.skipif(not API_KEY, reason="ELABFTW_DEMO_API_KEY not set"),
    pytest.mark.integration,
]


@pytest.fixture
def client():
    return ELabFTWClient(DEMO_URL, API_KEY, verify_ssl=True)


def _safe_delete(client, item_id):
    try:
        client.delete_item(item_id)
    except Exception as e:
        import warnings
        warnings.warn(f"Failed to delete test item #{item_id} on demo.elabftw.net: {e}")


@pytest.fixture
def test_item(client, request):
    """Create a temporary item and register cleanup immediately after ID is known."""
    # create_item internally does POST then PATCH(title). Even if PATCH fails,
    # the item exists on remote, so we register cleanup based on POST result.
    # We use the lower-level _req to get ID first, then update title separately.
    resp = client._req("POST", "/api/v2/items")
    item_id = client._parse_id(resp)
    request.addfinalizer(lambda: _safe_delete(client, item_id))
    try:
        client.update_item(item_id, title="[test] integration")
    except Exception:
        pass
    return item_id


# 1x1 red PNG for tests
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestImageUploadDownload:
    """Phase 1a: 画像の upload/download テスト。"""

    def test_upload_image_rewrites_url(self, client, test_item, tmp_path):
        """ローカル画像を push すると body 内 URL が eLabFTW URL に書き換わる。"""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "test_img.png").write_bytes(_PNG_1x1)
        md_body = "# Test\n\n![photo](test_img.png)"

        result = _rewrite_images(md_body, "items", test_item, client, docs, tmp_path)

        assert "download.php" in result or "/uploads/" in result
        assert "![photo](" in result

    def test_download_image_roundtrip(self, client, test_item, tmp_path):
        """アップロード後に pull で同じ画像がダウンロードできる。"""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "roundtrip.png").write_bytes(_PNG_1x1)
        md_body = "![img](roundtrip.png)"

        # Upload
        rewritten = _rewrite_images(md_body, "items", test_item, client, docs, tmp_path)

        # Download to new dir
        pull_dir = tmp_path / "pulled"
        pull_dir.mkdir()
        _download_images(rewritten, "items", test_item, client, pull_dir)

        # Verify image exists locally
        img_files = list((pull_dir / "images").glob("*.png"))
        assert len(img_files) >= 1
        assert img_files[0].read_bytes() == _PNG_1x1


class TestAttachmentUploadDownload:
    """Phase 1b: バイナリ添付ファイルの upload/download テスト。"""

    def test_upload_attachment(self, client, test_item, tmp_path):
        """非画像ファイルを attachments_dir から push できる。"""
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        csv_data = b"col1,col2\n1,2\n3,4\n"
        (att_dir / "data.csv").write_bytes(csv_data)

        _sync_attachments(att_dir, "items", test_item, client, force=False)

        uploads = client.list_uploads("items", test_item)
        csv_uploads = [u for u in uploads if u.get("real_name") == "data.csv"]
        assert len(csv_uploads) == 1

    def test_download_attachment_roundtrip(self, client, test_item, tmp_path):
        """アップロードした添付ファイルを pull でダウンロードし内容一致を確認。"""
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        pdf_data = b"%PDF-1.4 fake content for testing"
        (att_dir / "report.pdf").write_bytes(pdf_data)

        # Upload
        _sync_attachments(att_dir, "items", test_item, client, force=False)

        # Download to new dir
        pull_dir = tmp_path / "pulled_att"
        pull_dir.mkdir()
        _download_attachments("items", test_item, client, pull_dir)

        downloaded = pull_dir / "report.pdf"
        assert downloaded.exists()
        assert downloaded.read_bytes() == pdf_data

    def test_attachment_skip_same_size(self, client, test_item, tmp_path):
        """同名・同サイズの添付は再アップロードしない。"""
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        (att_dir / "notes.txt").write_bytes(b"hello world")

        _sync_attachments(att_dir, "items", test_item, client, force=False)
        uploads_before = client.list_uploads("items", test_item)

        # Run again — should skip
        _sync_attachments(att_dir, "items", test_item, client, force=False)
        uploads_after = client.list_uploads("items", test_item)

        txt_before = [u for u in uploads_before if u.get("real_name") == "notes.txt"]
        txt_after = [u for u in uploads_after if u.get("real_name") == "notes.txt"]
        assert len(txt_before) == len(txt_after) == 1
        assert txt_before[0]["id"] == txt_after[0]["id"]


class TestEndToEnd:
    """Phase 1c: DocsSyncer 経由の end-to-end テスト（実際に PATCH→GET）。"""

    def test_syncer_push_and_verify_remote(self, client, request, tmp_path):
        """DocsSyncer.sync() で push し、リモート body に内容が反映されることを確認。"""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "e2e.md").write_text("# E2E\n\nEnd to end test.", encoding="utf-8")

        target = TargetConfig(
            title="[test] e2e",
            docs_dir="docs/",
            id_file=str(tmp_path / ".elab-sync-ids" / "default.id"),
            pattern="*.md",
            mode="merge",
            entity="items",
        )
        syncer = DocsSyncer(client, target, tmp_path)

        # Pre-create item and register cleanup before sync
        resp = client._req("POST", "/api/v2/items")
        item_id = client._parse_id(resp)
        request.addfinalizer(lambda: _safe_delete(client, item_id))
        syncer.save_item_id(item_id)

        syncer.sync(force=True)

        # Verify remote body contains our content
        remote = client.get_item(item_id)
        body = remote.get("body", "")
        assert "E2E" in body or "End to end" in body

    def test_push_pull_push_idempotent(self, client, test_item, tmp_path):
        """push → remote PATCH → pull → 再 push で URL が安定する。"""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "stable.png").write_bytes(_PNG_1x1)
        md_body = "# Stable\n\n![pic](stable.png)\n\nSome text."

        # First push: upload image and rewrite
        body1 = _rewrite_images(md_body, "items", test_item, client, docs, tmp_path)

        # Actually update remote
        client.update_item(test_item, body=body1, title="[test] idempotent")

        # Pull from remote
        remote = client.get_item(test_item)
        remote_body = remote.get("body", "")

        # Download images from remote body
        pull_dir = tmp_path / "pull"
        pull_dir.mkdir()
        pulled = _download_images(remote_body, "items", test_item, client, pull_dir)

        # Second push from pulled content
        body2 = _rewrite_images(pulled, "items", test_item, client, pull_dir, tmp_path)

        # URLs should be stable
        assert body1 == body2
