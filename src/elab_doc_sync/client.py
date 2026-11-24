"""eLabFTW API v2 client for items, experiments, uploads, tags, and metadata."""

import hashlib
import json
import logging
import re
import requests
import urllib3
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


def upload_sha256(entry):
    """一覧の SHA-256 だけを採用する。旧添付の MD5 などは実体の照合が必要。"""
    for field in ("sha256", "hash"):
        value = entry.get(field)
        if isinstance(value, str) and re.fullmatch(r"[A-Fa-f0-9]{64}", value):
            return value.lower()
    return None


def upload_url(base_url, upload):
    """eLabFTW の一覧から、取得可能な添付の URL を組み立てる。"""
    if not upload.get("long_name") or not upload.get("real_name") or upload.get("storage") in (None, ""):
        return None
    query = urlencode({"f": upload["long_name"], "name": upload["real_name"], "storage": upload["storage"]}, quote_via=quote)
    return f"{base_url}/app/download.php?{query}"


class UploadConfirmationError(RuntimeError):
    """一覧で確認できなかった添付と、サーバーから受領した ID の記録。"""

    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


class ELabFTWClient:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self._json_headers = {"Authorization": api_key, "Content-Type": "application/json"}
        self._auth_headers = {"Authorization": api_key}

    # ── helpers ──────────────────────────────────────────────

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            resp = requests.request(
                method, f"{self.base_url}{path}",
                headers=kwargs.pop("headers", self._json_headers),
                verify=self.verify_ssl, timeout=kwargs.pop("timeout", 30), **kwargs,
            )
        except requests.exceptions.InvalidHeader:
            raise ValueError("HTTP ヘッダーの形式が不正です。API キーの改行などを確認してください") from None
        resp.raise_for_status()
        return resp

    def _get_entity(self, path: str) -> dict:
        response = self._req("GET", path)
        data = response.json()
        if str(data.get("state")) == "3":
            # eLabFTW can return HTTP 200 for soft-deleted entities. Present the
            # same missing-entity signal used by sync/pull for actual HTTP 404.
            missing = requests.Response()
            missing.status_code = 404
            raise requests.HTTPError(f"削除済み記事: {path}", response=missing)
        return data

    def _parse_id(self, resp: requests.Response) -> int:
        loc = resp.headers.get("location", "")
        try:
            return int(resp.json().get("id", loc.split("/")[-1]))
        except Exception:
            return int(loc.split("/")[-1])

    # ── user info ────────────────────────────────────────────

    def get_user_info(self) -> dict:
        """現在の API キーに紐づくユーザー情報を取得する。

        返り値には userid, firstname, lastname, email, team (アクティブチームID),
        teams (所属チーム一覧) などが含まれる。
        """
        return self._req("GET", "/api/v2/users/me").json()

    def get_active_team(self) -> tuple[int, str | None]:
        """APIキーのアクティブチーム (id, name) を返す。

        name が解決できない場合は (id, None) を返す。
        """
        user = self.get_user_info()
        active_team_id = user.get("team")
        if not active_team_id:
            return (0, None)
        teams = user.get("teams", [])
        for t in teams:
            if t.get("id") == active_team_id:
                return (active_team_id, t.get("name"))
        return (active_team_id, None)

    # ── items ────────────────────────────────────────────────

    def list_items(self) -> list[dict]:
        return self._req("GET", "/api/v2/items").json()

    def get_item(self, item_id: int) -> dict:
        return self._get_entity(f"/api/v2/items/{item_id}")

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
        return self._get_entity(f"/api/v2/experiments/{exp_id}")

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
        """成功時は Location を優先し、候補がなければ url=None を返す。

        応答不明時は再送せず、新しい添付の名前と SHA-256 を照合する。
        特定できない場合は UploadConfirmationError に確認手順を含める。
        URL を返す場合は receipt に id・name・size・sha256 を含める。
        """
        url = f"/api/v2/{entity_type}/{entity_id}/uploads"
        filename = Path(filepath).name
        previous_ids = {u["id"] for u in self.list_uploads(entity_type, entity_id)}
        payload = Path(filepath).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        unknown = (f"{entity_type} #{entity_id} の添付 {filename!r} の送信結果を確認できません。"
                   "自動再送を停止しました。esync diff と eLabFTW の添付一覧で ID・名前・内容を確認してください")
        response = None
        receipt = None
        try:
            response = self._req("POST", url, headers=self._auth_headers,
                                 files={"file": (filename, payload)}, data={"comment": comment}, timeout=60,
                                 allow_redirects=False)
            if 300 <= response.status_code < 400:
                response = None
            else:
                location = response.headers.get("location", "").rstrip("/").split("/")[-1]
                if location.isdecimal() and int(location) not in previous_ids:
                    receipt = {"id": int(location), "name": filename, "size": len(payload), "sha256": digest}
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code < 500:
                raise
        except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ContentDecodingError):
            pass
        try:
            candidates = [u for u in self.list_uploads(entity_type, entity_id)
                          if u["id"] not in previous_ids and u.get("real_name") == filename
                          and upload_url(self.base_url, u)]
            if response is None:
                matches = []
                for candidate in candidates:
                    remote_digest = upload_sha256(candidate)
                    if not remote_digest:
                        remote_digest = self.upload_digest(entity_type=entity_type, entity_id=entity_id,
                                                           upload_id=candidate["id"])
                    if remote_digest == digest:
                        matches.append(candidate)
                if len(matches) != 1:
                    raise ValueError("一致する新規添付を一意に特定できません")
                upload = matches[0]
            else:
                location = response.headers.get("location", "").rstrip("/").split("/")[-1]
                upload = next((u for u in candidates if str(u["id"]) == location), None)
                if upload is None and receipt is None and candidates:
                    same = []
                    for candidate in candidates:
                        known = upload_sha256(candidate)
                        if not known and (candidate.get("hash") or candidate.get("sha256")):
                            known = self.upload_digest(entity_type=entity_type, entity_id=entity_id, upload_id=candidate["id"])
                        if known == digest:
                            same.append(candidate)
                    unverified = [u for u in candidates if not (u.get("sha256") or u.get("hash"))]
                    upload = max(same or unverified, key=lambda u: u["id"], default=None)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise UploadConfirmationError(unknown, receipt) from exc
        if upload is None:
            return {"filename": filename, "url": None, **({"receipt": receipt} if receipt else {})}
        return {
            "id": upload.get("id"), "filename": filename,
            "receipt": {"id": upload["id"], "name": filename, "size": len(payload), "sha256": digest},
            "url": upload_url(self.base_url, upload),
        }

    def delete_upload(self, entity_type: str, entity_id: int, upload_id: int) -> None:
        """添付ファイルを削除する。"""
        self._req("DELETE", f"/api/v2/{entity_type}/{entity_id}/uploads/{upload_id}")

    def list_uploads(self, entity_type: str, entity_id: int) -> list[dict]:
        """エンティティの添付ファイル一覧を返す。"""
        return self._req("GET", f"/api/v2/{entity_type}/{entity_id}/uploads").json()

    def upload_digest(self, *, entity_type: str, entity_id: int, upload_id: int) -> str:
        """照合用に添付の実体を分割して読み、MIME にかかわらず SHA-256 を返す。"""
        digest = hashlib.sha256()
        with self._req("GET", f"/api/v2/{entity_type}/{entity_id}/uploads/{upload_id}",
                       headers={**self._auth_headers, "Accept": "application/octet-stream"},
                       params={"format": "binary"}, stream=True) as response:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

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

    # ── categories ───────────────────────────────────────────

    def list_items_types(self) -> list[dict]:
        return self._req("GET", "/api/v2/items_types").json()

    def list_experiments_categories(self) -> list[dict]:
        return self._req("GET", "/api/v2/experiments_categories").json()

    def list_categories(self, entity_type: str) -> list[dict]:
        if entity_type == "experiments":
            return self.list_experiments_categories()
        return self.list_items_types()

    def resolve_category_id(self, entity_type: str, category: str | int, current: dict | None = None) -> int:
        """カテゴリ名または ID を ID に解決する。

        current にエンティティのデータを渡すと、そのカテゴリ名が一致する場合は
        一覧を引かずにその ID を使う。読み取り権限のないカテゴリは一覧 API に
        出ないが、エンティティには category_title として返るため。
        """
        try:
            return int(category)
        except (ValueError, TypeError):
            pass
        if current and current.get("category") is not None and current.get("category_title") == category:
            return int(current["category"])
        for cat in self.list_categories(entity_type):
            if cat.get("title") == category:
                return cat["id"]
        raise ValueError(f"カテゴリ「{category}」が見つかりません（API から読めないカテゴリの可能性があります）。"
                         f"同じカテゴリの文書から「esync category show --id <確認元の文書ID> --entity {entity_type}」で"
                         f"カテゴリ ID を確認し、数字で指定してください"
                         f"（設定ファイル: category: 64 / CLI: esync category set 64 --id <変更対象の文書ID> --entity {entity_type}）")

    def resolve_category_name(self, entity_type: str, category_id: int) -> str | None:
        """カテゴリ ID を名前に解決する。見つからなければ None。"""
        for cat in self.list_categories(entity_type):
            if cat.get("id") == category_id:
                return cat.get("title")
        return None

    # ── tags ─────────────────────────────────────────────────

    def get_tags(self, entity_type: str, entity_id: int) -> list[dict]:
        data = self._req("GET", f"/api/v2/{entity_type}/{entity_id}/tags").json()
        # Untagged entities may return JSON null instead of an empty list.
        return [] if data is None else data

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

    # ── links ────────────────────────────────────────────────

    def list_links(self, entity_type: str, entity_id: int, link_type: str) -> list[dict]:
        """エンティティから link_type（experiments / items）へのリンク一覧を返す。"""
        data = self._req("GET", f"/api/v2/{entity_type}/{entity_id}/{link_type}_links").json()
        return [] if data is None else data

    def add_link(self, entity_type: str, entity_id: int, link_type: str, target_id: int) -> None:
        """エンティティから link_type の target_id へのリンクを作成する。"""
        self._req("POST", f"/api/v2/{entity_type}/{entity_id}/{link_type}_links/{target_id}",
                  json={"action": "create"})

    def remove_link(self, entity_type: str, entity_id: int, link_type: str, target_id: int) -> None:
        """エンティティから link_type の target_id へのリンクを削除する（リンク先は削除しない）。"""
        self._req("DELETE", f"/api/v2/{entity_type}/{entity_id}/{link_type}_links/{target_id}")
