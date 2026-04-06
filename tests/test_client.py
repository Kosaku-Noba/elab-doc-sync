"""Tests for client.py (CL-01 ~ CL-16)."""

from unittest.mock import patch, MagicMock, mock_open
import json
import pytest

from elab_doc_sync.client import ELabFTWClient


@pytest.fixture
def client():
    return ELabFTWClient("https://elab.example.com", "api-key-123", verify_ssl=True)


def _mock_response(json_data=None, status_code=200, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.raise_for_status.return_value = None
    return resp


# CL-01
@patch("elab_doc_sync.client.requests.request")
def test_get_item(mock_req, client):
    mock_req.return_value = _mock_response({"id": 42, "title": "t"})
    result = client.get_item(42)
    mock_req.assert_called_once()
    assert mock_req.call_args[0] == ("GET", "https://elab.example.com/api/v2/items/42")
    assert result["id"] == 42


# CL-02
@patch("elab_doc_sync.client.requests.request")
def test_create_item(mock_req, client):
    post_resp = _mock_response({"id": 10}, headers={"location": "/api/v2/items/10"})
    patch_resp = _mock_response()
    mock_req.side_effect = [post_resp, patch_resp]
    item_id = client.create_item(title="New", body="<p>hi</p>")
    assert item_id == 10
    assert mock_req.call_count == 2


# CL-03
@patch("elab_doc_sync.client.requests.request")
def test_update_item(mock_req, client):
    mock_req.return_value = _mock_response()
    client.update_item(5, body="<p>updated</p>", title="T")
    assert mock_req.call_args[1]["json"] == {"body": "<p>updated</p>", "title": "T"}


# CL-04
@patch("elab_doc_sync.client.requests.request")
def test_delete_item(mock_req, client):
    mock_req.return_value = _mock_response()
    client.delete_item(5)
    assert mock_req.call_args[0] == ("DELETE", "https://elab.example.com/api/v2/items/5")


# CL-05
@patch("elab_doc_sync.client.requests.request")
def test_experiment_crud(mock_req, client):
    mock_req.return_value = _mock_response({"id": 3})
    client.get_experiment(3)
    assert "/experiments/3" in mock_req.call_args[0][1]

    post_resp = _mock_response({"id": 7}, headers={"location": "/api/v2/experiments/7"})
    patch_resp = _mock_response()
    mock_req.side_effect = [post_resp, patch_resp]
    eid = client.create_experiment(title="Exp")
    assert eid == 7

    mock_req.side_effect = None
    mock_req.return_value = _mock_response()
    client.update_experiment(7, body="<p>x</p>")
    assert mock_req.call_args[1]["json"] == {"body": "<p>x</p>"}


# CL-06
@patch("elab_doc_sync.client.requests.request")
def test_upload_file(mock_req, client, tmp_path):
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG")
    upload_resp = _mock_response()
    list_resp = _mock_response([{"real_name": "img.png", "long_name": "abc123", "storage": "1", "id": 99}])
    mock_req.side_effect = [upload_resp, list_resp]
    result = client.upload_file("items", 1, str(img))
    assert result["url"] is not None
    assert "img.png" in result["url"]


# CL-07
@patch("elab_doc_sync.client.requests.request")
def test_upload_file_no_url(mock_req, client, tmp_path):
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG")
    mock_req.side_effect = [_mock_response(), _mock_response([])]
    result = client.upload_file("items", 1, str(img))
    assert result["url"] is None


# CL-08
@patch("elab_doc_sync.client.requests.request")
def test_http_error(mock_req, client):
    resp = _mock_response()
    resp.raise_for_status.side_effect = Exception("404")
    mock_req.return_value = resp
    with pytest.raises(Exception, match="404"):
        client.get_item(999)


# CL-09
def test_verify_ssl_false():
    c = ELabFTWClient("https://x.com", "k", verify_ssl=False)
    assert c.verify_ssl is False


# CL-10
@patch("elab_doc_sync.client.requests.request")
def test_add_remove_tag(mock_req, client):
    mock_req.return_value = _mock_response()
    client.add_tag("items", 1, "mytag")
    assert mock_req.call_args[1]["json"] == {"tag": "mytag"}

    client.remove_tag("items", 1, 5)
    assert "/tags/5" in mock_req.call_args[0][1]


# CL-11
@patch("elab_doc_sync.client.requests.request")
def test_list_items_experiments(mock_req, client):
    mock_req.return_value = _mock_response([{"id": 1}, {"id": 2}])
    items = client.list_items()
    assert len(items) == 2
    exps = client.list_experiments()
    assert len(exps) == 2


# CL-12
@patch("elab_doc_sync.client.requests.request")
def test_delete_experiment(mock_req, client):
    mock_req.return_value = _mock_response()
    client.delete_experiment(3)
    assert mock_req.call_args[0] == ("DELETE", "https://elab.example.com/api/v2/experiments/3")


# CL-13
@patch("elab_doc_sync.client.requests.request")
def test_update_metadata(mock_req, client):
    mock_req.return_value = _mock_response()
    client.update_metadata("items", 1, {"key": "val"})
    call_json = mock_req.call_args[1]["json"]
    assert "metadata" in call_json
    assert json.loads(call_json["metadata"]) == {"key": "val"}


# CL-14
@patch("elab_doc_sync.client.requests.request")
def test_search_experiments(mock_req, client):
    mock_req.return_value = _mock_response([{"id": 5}])
    result = client.search_experiments(["tag1"])
    assert result == [{"id": 5}]
    assert mock_req.call_args[1]["params"] == {"tags[]": ["tag1"]}


# CL-15
@patch("elab_doc_sync.client.requests.request")
def test_append_body(mock_req, client):
    get_resp = _mock_response({"id": 1, "body": "<p>old</p>"})
    patch_resp = _mock_response()
    mock_req.side_effect = [get_resp, patch_resp]
    client.append_body(1, "new text")
    patched_body = mock_req.call_args_list[1][1]["json"]["body"]
    assert "old" in patched_body
    assert "new text" in patched_body


# CL-16
@patch("elab_doc_sync.client.requests.request")
def test_replace_body(mock_req, client):
    mock_req.return_value = _mock_response()
    client.replace_body(1, "<p>replaced</p>")
    assert mock_req.call_args[1]["json"] == {"body": "<p>replaced</p>"}


# ── FR-15/16/17 新メソッドのテスト ──────────────────────────


# CL-17: get_tags
@patch("elab_doc_sync.client.requests.request")
def test_get_tags(mock_req, client):
    mock_req.return_value = _mock_response([{"id": 1, "tag": "alpha"}, {"id": 2, "tag": "beta"}])
    tags = client.get_tags("items", 42)
    assert len(tags) == 2
    assert tags[0]["tag"] == "alpha"
    assert "/items/42/tags" in mock_req.call_args[0][1]


# CL-18: untag_by_name — タグが見つかる場合
@patch("elab_doc_sync.client.requests.request")
def test_untag_by_name_found(mock_req, client):
    get_resp = _mock_response([{"id": 5, "tag": "remove-me"}, {"id": 6, "tag": "keep"}])
    patch_resp = _mock_response()
    mock_req.side_effect = [get_resp, patch_resp]
    result = client.untag_by_name("items", 1, "remove-me")
    assert result is True
    assert mock_req.call_args[1]["json"] == {"action": "unreference"}
    assert "/tags/5" in mock_req.call_args[0][1]


# CL-19: untag_by_name — タグが見つからない場合
@patch("elab_doc_sync.client.requests.request")
def test_untag_by_name_not_found(mock_req, client):
    mock_req.return_value = _mock_response([{"id": 1, "tag": "other"}])
    result = client.untag_by_name("items", 1, "nonexistent")
    assert result is False


# CL-20: get_metadata — 正常な JSON object
@patch("elab_doc_sync.client.requests.request")
def test_get_metadata_normal(mock_req, client):
    mock_req.return_value = _mock_response({"id": 1, "metadata": '{"key": "val"}'})
    meta = client.get_metadata("items", 1)
    assert meta == {"key": "val"}


# CL-21: get_metadata — null/空
@patch("elab_doc_sync.client.requests.request")
def test_get_metadata_null(mock_req, client):
    mock_req.return_value = _mock_response({"id": 1, "metadata": None})
    assert client.get_metadata("items", 1) == {}


# CL-22: get_metadata — 不正 JSON
@patch("elab_doc_sync.client.requests.request")
def test_get_metadata_invalid_json(mock_req, client):
    mock_req.return_value = _mock_response({"id": 1, "metadata": "not-json{"})
    assert client.get_metadata("items", 1) == {}


# CL-23: get_metadata — list 型（非 dict）
@patch("elab_doc_sync.client.requests.request")
def test_get_metadata_list_type(mock_req, client):
    mock_req.return_value = _mock_response({"id": 1, "metadata": '[1, 2]'})
    assert client.get_metadata("items", 1) == {}


# CL-24: get_entity / patch_entity
@patch("elab_doc_sync.client.requests.request")
def test_get_entity(mock_req, client):
    mock_req.return_value = _mock_response({"id": 1, "status_title": "Running"})
    entity = client.get_entity("experiments", 1)
    assert entity["status_title"] == "Running"


@patch("elab_doc_sync.client.requests.request")
def test_patch_entity(mock_req, client):
    mock_req.return_value = _mock_response()
    client.patch_entity("experiments", 1, status=2)
    assert mock_req.call_args[1]["json"] == {"status": 2}


# CL-25: list_uploads
@patch("elab_doc_sync.client.requests.request")
def test_list_uploads(mock_req, client):
    mock_req.return_value = _mock_response([{"id": 1, "real_name": "img.png", "long_name": "abc.png"}])
    result = client.list_uploads("items", 42)
    assert len(result) == 1
    assert result[0]["real_name"] == "img.png"


# CL-26: download_upload with format=binary
@patch("elab_doc_sync.client.requests.request")
def test_download_upload(mock_req, client):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.content = b"\x89PNG"
    resp.headers = {"Content-Type": "image/png"}
    mock_req.return_value = resp
    data = client.download_upload("items", 42, 10)
    assert data == b"\x89PNG"
    # format=binary が params に渡されていることを確認
    call_kwargs = mock_req.call_args
    assert call_kwargs[1].get("params") == {"format": "binary"}


# CL-27: download_upload rejects JSON response
@patch("elab_doc_sync.client.requests.request")
def test_download_upload_rejects_json(mock_req, client):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.content = b'{"id": 10}'
    resp.headers = {"Content-Type": "application/json"}
    mock_req.return_value = resp
    with pytest.raises(RuntimeError, match="application/json"):
        client.download_upload("items", 42, 10)
