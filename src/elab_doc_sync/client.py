"""eLabFTW API v2 client for items, experiments, uploads, tags, and metadata."""

import json
import logging
import requests
import urllib3
from pathlib import Path
from typing import Any

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


class ELabFTWClient:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self._json_headers = {"Authorization": api_key, "Content-Type": "application/json"}
        self._auth_headers = {"Authorization": api_key}

    # ── helpers ──────────────────────────────────────────────

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        resp = requests.request(
            method, f"{self.base_url}{path}",
            headers=kwargs.pop("headers", self._json_headers),
            verify=self.verify_ssl, timeout=kwargs.pop("timeout", 30), **kwargs,
        )
        resp.raise_for_status()
        return resp

    def _parse_id(self, resp: requests.Response) -> int:
        loc = resp.headers.get("location", "")
        try:
            return int(resp.json().get("id", loc.split("/")[-1]))
        except Exception:
            return int(loc.split("/")[-1])

    # ── items ────────────────────────────────────────────────

    def list_items(self) -> list[dict]:
        return self._req("GET", "/api/v2/items").json()

    def get_item(self, item_id: int) -> dict:
        return self._req("GET", f"/api/v2/items/{item_id}").json()

    def create_item(self, title: str = "", body: str = "") -> int:
        resp = self._req("POST", "/api/v2/items")
        item_id = self._parse_id(resp)
        if title or body:
            self.update_item(item_id, title=title, body=body)
        return item_id

    def update_item(self, item_id: int, **fields) -> None:
        self._req("PATCH", f"/api/v2/items/{item_id}", json=fields)

    def delete_item(self, item_id: int) -> None:
        self._req("DELETE", f"/api/v2/items/{item_id}")

    # ── experiments ──────────────────────────────────────────

    def list_experiments(self) -> list[dict]:
        return self._req("GET", "/api/v2/experiments").json()

    def get_experiment(self, exp_id: int) -> dict:
        return self._req("GET", f"/api/v2/experiments/{exp_id}").json()

    def create_experiment(self, title: str = "", body: str = "") -> int:
        resp = self._req("POST", "/api/v2/experiments")
        exp_id = self._parse_id(resp)
        if title or body:
            self.update_experiment(exp_id, title=title, body=body)
        return exp_id

    def update_experiment(self, exp_id: int, **fields) -> None:
        self._req("PATCH", f"/api/v2/experiments/{exp_id}", json=fields)

    def delete_experiment(self, exp_id: int) -> None:
        self._req("DELETE", f"/api/v2/experiments/{exp_id}")

    def search_experiments(self, tags: list[str]) -> list[dict]:
        return self._req("GET", "/api/v2/experiments", params={"tags[]": tags}).json()

    def append_body(self, exp_id: int, text: str) -> None:
        exp = self.get_experiment(exp_id)
        body = (exp.get("body") or "") + "\n\n" + text
        self.update_experiment(exp_id, body=body)

    def replace_body(self, exp_id: int, body: str) -> None:
        self.update_experiment(exp_id, body=body)

    # ── uploads ──────────────────────────────────────────────

    def get_entity(self, entity_type: str, entity_id: int) -> dict:
        """汎用エンティティ取得。"""
        return self._req("GET", f"/api/v2/{entity_type}/{entity_id}").json()

    def patch_entity(self, entity_type: str, entity_id: int, **fields) -> None:
        """汎用エンティティ更新。"""
        self._req("PATCH", f"/api/v2/{entity_type}/{entity_id}", json=fields)

    # ── uploads ──────────────────────────────────────────────

    def upload_file(self, entity_type: str, entity_id: int, filepath: str, comment: str = "") -> dict:
        """Upload file. entity_type is 'items' or 'experiments'."""
        url = f"/api/v2/{entity_type}/{entity_id}/uploads"
        with open(filepath, "rb") as f:
            self._req("POST", url, headers=self._auth_headers,
                      files={"file": f}, data={"comment": comment}, timeout=60)
        uploads = self._req("GET", url).json()
        filename = Path(filepath).name
        for upload in reversed(uploads):
            if upload.get("real_name") == filename:
                long_name = upload.get("long_name")
                storage = upload.get("storage")
                if long_name and storage:
                    return {
                        "id": upload.get("id"), "filename": filename,
                        "url": f"{self.base_url}/app/download.php?f={long_name}&name={filename}&storage={storage}",
                    }
        return {"filename": filename, "url": None}

    # ── tags ─────────────────────────────────────────────────

    def get_tags(self, entity_type: str, entity_id: int) -> list[dict]:
        return self._req("GET", f"/api/v2/{entity_type}/{entity_id}/tags").json()

    def add_tag(self, entity_type: str, entity_id: int, tag: str) -> None:
        self._req("POST", f"/api/v2/{entity_type}/{entity_id}/tags", json={"tag": tag})

    def remove_tag(self, entity_type: str, entity_id: int, tag_id: int) -> None:
        self._req("DELETE", f"/api/v2/{entity_type}/{entity_id}/tags/{tag_id}")

    def untag_by_name(self, entity_type: str, entity_id: int, tag_name: str) -> bool:
        """エンティティからタグを外す（タグ自体は削除しない）。"""
        for tag in self.get_tags(entity_type, entity_id):
            if tag.get("tag") == tag_name:
                self._req("PATCH", f"/api/v2/{entity_type}/{entity_id}/tags/{tag['id']}",
                          json={"action": "unreference"})
                return True
        return False

    # ── metadata ─────────────────────────────────────────────

    def get_metadata(self, entity_type: str, entity_id: int) -> dict:
        """エンティティのメタデータを dict で返す。

        eLabFTW の metadata フィールドは JSON object 文字列または null。
        パース失敗・非 dict・falsy 値の場合は空 dict を返す（データ消失ではなく、
        eLabFTW 側にメタデータが未設定の状態と同等）。
        """
        entity = self._req("GET", f"/api/v2/{entity_type}/{entity_id}").json()
        raw = entity.get("metadata")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_metadata_raw(self, entity_type: str, entity_id: int) -> str | None:
        """メタデータの生の値を返す（パースせず）。"""
        entity = self._req("GET", f"/api/v2/{entity_type}/{entity_id}").json()
        return entity.get("metadata")

    def update_metadata(self, entity_type: str, entity_id: int, metadata: dict[str, Any]) -> None:
        self._req("PATCH", f"/api/v2/{entity_type}/{entity_id}",
                  json={"metadata": json.dumps(metadata)})
