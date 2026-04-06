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
        """ファイルをアップロードする。

        filepath の basename が eLabFTW 上の real_name として保存される。
        entity_type は 'items' または 'experiments'。
        """
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

    def list_uploads(self, entity_type: str, entity_id: int) -> list[dict]:
        """エンティティの添付ファイル一覧を返す。"""
        return self._req("GET", f"/api/v2/{entity_type}/{entity_id}/uploads").json()

    def download_upload(self, *, entity_type: str, entity_id: int, upload_id: int) -> bytes:
        """添付ファイル（画像含む全種別）のバイナリを返す。

        内部メソッド: このリポジトリ内でのみ使用。外部公開 API ではない。

        eLabFTW API v2 の /uploads/{id} に Accept: application/octet-stream と
        format=binary の両方を指定してバイナリを取得する。
        参照: https://doc.elabftw.net/api/v2/#/uploads/readUpload

        eLabFTW API v2 は format=binary 成功時にファイルの実 MIME を返す。
        テキスト系 MIME（json/html/text）が返った場合はメタデータ応答や
        プロキシ応答と判断し RuntimeError を送出する。

        Args:
            entity_type: items / experiments
            entity_id: エンティティ ID
            upload_id: アップロード ID

        Raises:
            RuntimeError: レスポンスがテキスト系（JSON/HTML/text）の場合
        """
        resp = self._req(
            "GET", f"/api/v2/{entity_type}/{entity_id}/uploads/{upload_id}",
            headers={**self._auth_headers, "Accept": "application/octet-stream"},
            params={"format": "binary"},
        )
        ct = resp.headers.get("Content-Type", "")
        if any(t in ct for t in ("application/json", "text/html", "text/plain")):
            raise RuntimeError(
                f"画像のバイナリ取得に失敗しました（upload #{upload_id}: Content-Type={ct}）。"
                f"eLabFTW が format=binary に対応していない可能性があります"
            )
        return resp.content

    def download_by_long_name(self, long_name: str) -> bytes:
        """long_name を使って添付ファイルのバイナリを取得する。

        内部メソッド。list_uploads に含まれない body 埋め込み画像用。
        GET /api/v2/users/me/uploads で自分の全 uploads を取得し、
        long_name が一致する upload を特定してからダウンロードする。
        """
        resp = self._req("GET", "/api/v2/users/me/uploads")
        for u in resp.json():
            if u.get("long_name") == long_name:
                etype = u.get("type") or u.get("page") or "items"
                eid = u.get("entity_id") or u.get("item_id") or 0
                return self.download_upload(
                    entity_type=etype, entity_id=eid, upload_id=u["id"],
                )
        raise RuntimeError(f"upload が見つかりません: {long_name[:60]}")

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
