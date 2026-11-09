"""Search items/experiments on eLabFTW with the same filters as the web UI.

Server-side filters (eLabFTW API v2 GET /items, /experiments):
  q         keyword in title, body or elabid
  extended  advanced query, ANDed with q by the server
            (author:"name" date:>=YYYYMMDD category:s:"name" status:s:"name")
  owner     author user id, cat / status: ids, tags[]: entries with all tags
The last-modified date cannot be filtered on the server, so it is filtered
here while paging (stopping early when results are ordered by lastchange desc).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

ENTITY_TYPES = ("items", "experiments")
ORDER_CHOICES = ("date", "lastchange", "title", "id", "cat", "status", "user", "rating", "customid", "comment")
SCOPE_VALUES = {"mine": 1, "team": 2, "all": 3}
PAGE_SIZE = 100
# Characters of the body shown in the text output (--json prints the whole body)
BODY_PREVIEW = 300
# Upper bound of entries scanned per entity when filtering on the client side
MAX_SCAN = 5000

# Field used to merge results of items and experiments in the requested order
_ORDER_FIELDS = {
    "date": "date", "lastchange": "modified_at", "title": "title", "id": "id",
    "cat": "category_title", "status": "status_title", "user": "fullname",
    "rating": "rating", "customid": "custom_id",
}


@dataclass
class SearchQuery:
    keyword: str = ""
    entities: tuple[str, ...] = ENTITY_TYPES
    author: str | None = None
    since: _dt.date | None = None
    until: _dt.date | None = None
    updated_since: _dt.date | None = None
    updated_until: _dt.date | None = None
    tags: list[str] = field(default_factory=list)
    category: str | None = None
    status: str | None = None
    scope: str | None = None
    order: str | None = None
    sort: str | None = None
    limit: int = 20
    offset: int = 0


def parse_date(value: str | None, option: str) -> _dt.date | None:
    if value is None:
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{option} は YYYY-MM-DD 形式で指定してください: {value}") from None


def _quote(value: str, option: str) -> str:
    """Quote a value for the extended query. % and _ are escaped to match literally."""
    if any(c in value for c in "\n\r\f"):
        raise ValueError(f"{option} に改行は使えません")
    escaped = value.replace('"', '\\"').replace("%", "\\%").replace("_", "\\_")
    return f'"{escaped}"'


def _as_id(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def build_params(query: SearchQuery, my_userid: int | None) -> dict:
    """Build request params shared by items and experiments (without limit/offset)."""
    if query.since and query.until and query.since > query.until:
        raise ValueError("--since が --until より後になっています")
    if query.updated_since and query.updated_until and query.updated_since > query.updated_until:
        raise ValueError("--updated-since が --updated-until より後になっています")
    params: dict = {}
    extended: list[str] = []
    owners: list[int] = []
    if query.keyword.strip():
        params["q"] = query.keyword.strip()
    if query.author is not None:
        author = query.author.strip()
        if not author:
            raise ValueError("--author が空です")
        if author == "me":
            owners.append(_require_userid(my_userid))
        elif _as_id(author) is not None:
            owners.append(_as_id(author))
        else:
            # Partial match on "firstname lastname", as in the web UI
            extended.append(f"author:{_quote(author, '--author')}")
    if query.scope == "mine":
        owners.append(_require_userid(my_userid))
    if len(set(owners)) > 1:
        # owner=1,2 would be an OR on the server; both conditions cannot hold
        raise ValueError("--author と --scope mine で別のユーザーを指定しています")
    if owners:
        params["owner"] = str(owners[0])
    if query.scope:
        params["scope"] = SCOPE_VALUES[query.scope]
    if query.since:
        extended.append(f"date:>={query.since:%Y%m%d}")
    if query.until:
        extended.append(f"date:<={query.until:%Y%m%d}")
    if query.tags:
        params["tags[]"] = list(query.tags)
    for option, value, param, keyword in (("--category", query.category, "cat", "category"),
                                          ("--status", query.status, "status", "status")):
        if value is None:
            continue
        if _as_id(value) is not None:
            if len(query.entities) > 1:
                # Category/status ids are defined separately for items and experiments
                raise ValueError(f"{option} を ID で指定するときは --entity items または experiments を指定してください"
                                 f"（名前なら --entity all でも使えます）")
            params[param] = str(_as_id(value))
        else:
            extended.append(f"{keyword}:s:{_quote(value, option)}")
    if extended:
        params["extended"] = " ".join(extended)
    order = query.order
    sort = query.sort
    if order is None and (query.updated_since or query.updated_until or len(query.entities) > 1):
        # Needed to stop paging early on the updated date and to merge entity types
        order = "lastchange"
    if order:
        params["order"] = order
        params["sort"] = sort or "desc"
    elif sort:
        params["sort"] = sort
    return params


def _require_userid(userid: int | None) -> int:
    if not userid:
        raise ValueError("現在のユーザー ID を取得できませんでした（esync whoami で接続を確認してください）")
    return int(userid)


def _modified_date(entity: dict) -> _dt.date | None:
    raw = str(entity.get("modified_at") or "")[:10]
    try:
        return _dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _fetch(client, entity_type: str, params: dict, query: SearchQuery, team_id: int | None, *,
           start: int, need: int, count_pinned: bool) -> tuple[list[dict], bool, bool]:
    """Collect matches in server order, starting at the server offset `start`.

    Stops once `need` matches are found (pinned entries do not count unless
    count_pinned). Returns (matches, more matches exist, scan limit reached).
    """
    client_filter = bool(query.updated_since or query.updated_until or team_id)
    stop_early = query.updated_since is not None and params.get("order") == "lastchange" and params.get("sort") == "desc"
    matches: list[dict] = []
    counted = 0
    scanned = 0
    while True:
        exact = count_pinned and not client_filter
        page_size = min(PAGE_SIZE, need + 1 - counted) if exact else PAGE_SIZE
        page_params = {**params, "limit": page_size}
        if start + scanned:
            page_params["offset"] = start + scanned
        page = client._req("GET", f"/api/v2/{entity_type}", params=page_params).json() or []
        for entity in page:
            pinned = bool(entity.get("is_pinned"))
            modified = _modified_date(entity)
            if stop_early and modified is not None and modified < query.updated_since:
                # Pinned entries come first regardless of the order, so only skip them
                if not pinned:
                    return matches, False, False
                continue
            if query.updated_since and (modified is None or modified < query.updated_since):
                continue
            if query.updated_until and (modified is None or modified > query.updated_until):
                continue
            # Entries whose team cannot be confirmed are left out of --scope team
            if team_id and str(entity.get("team")) != str(team_id):
                continue
            counts = count_pinned or not pinned
            if counts and counted >= need:
                return matches, True, False
            matches.append(entity)
            counted += counts
        scanned += len(page)
        if len(page) < page_size:
            return matches, False, False
        # The server-offset path fetches exactly what is needed, so no limit applies
        if not exact and scanned >= MAX_SCAN:
            return matches, False, True


def _sort_key(entity: dict, order: str):
    value = entity.get(_ORDER_FIELDS[order])
    if order in ("id", "rating", "customid"):
        try:
            return (0, int(value))
        except (TypeError, ValueError):
            return (1, 0)
    return (0 if value not in (None, "") else 1, str(value or "").lower())


def search(client, query: SearchQuery) -> dict:
    """Run the search.

    Returns {"results": [(entity_type, entity), ...], "has_more", "next_offset", "truncated"}.
    truncated means the scan limit was reached, so matching entries may be missing.
    """
    if query.limit < 1:
        raise ValueError("--limit は 1 以上を指定してください")
    if query.offset < 0:
        raise ValueError("--offset は 0 以上を指定してください")
    needs_user = query.author == "me" or query.scope in ("mine", "team")
    user = client.get_user_info() if needs_user else {}
    params = build_params(query, user.get("userid"))
    team_id = None
    if query.scope == "team":
        # eLabFTW only restricts scope=2 to the team when the user's own preference is "team"
        team_id = user.get("team")
        if not team_id:
            raise ValueError("現在のチームを取得できないため --scope team で絞り込めません（esync whoami で確認してください）")
    merge = len(query.entities) > 1
    client_filter = bool(query.updated_since or query.updated_until or team_id)
    # Without merging or client-side filtering, the server offset can be used directly
    server_offset = not merge and not client_filter
    start = query.offset if server_offset else 0
    skip = 0 if server_offset else query.offset
    combined: list[tuple[str, dict]] = []
    has_more = truncated = False
    for entity_type in query.entities:
        # The server lists pinned entries first; when both types are merged and
        # re-sorted they must not use up the quota of entries ranked after them
        found, more, cut = _fetch(client, entity_type, params, query, team_id,
                                  start=start, need=skip + query.limit, count_pinned=not merge)
        combined.extend((entity_type, e) for e in found)
        has_more = has_more or more
        truncated = truncated or cut
    order = params.get("order")
    if merge and order in _ORDER_FIELDS:
        reverse = params.get("sort", "desc") == "desc"
        present = [r for r in combined if _sort_key(r[1], order)[0] == 0]
        missing = [r for r in combined if _sort_key(r[1], order)[0] != 0]
        present.sort(key=lambda r: _sort_key(r[1], order), reverse=reverse)
        combined = present + missing
    page = combined[skip:skip + query.limit]
    has_more = has_more or len(combined) > skip + query.limit
    # A truncated scan may have missed entries, so paging on would not be reliable
    return {"results": page, "has_more": has_more, "truncated": truncated,
            "next_offset": query.offset + len(page) if has_more and not truncated else None}


# ── presentation ────────────────────────────────────────────

_PAGES = {"items": "database", "experiments": "experiments"}


def entity_url(base_url: str, entity_type: str, entity_id) -> str:
    return f"{base_url.rstrip('/')}/{_PAGES[entity_type]}.php?mode=view&id={entity_id}"


def split_tags(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(t.get("tag", "")) if isinstance(t, dict) else str(t) for t in value]
    return [t for t in str(value).split("|") if t]


def body_markdown(entity: dict) -> str:
    """Convert a remote body to Markdown the same way pull does."""
    from .sync import _remote_markdown
    return _remote_markdown(entity, SimpleNamespace(body_format="html"))


def _server_key(url: str) -> tuple[str, str]:
    from urllib.parse import urlparse
    parsed = urlparse(url.strip())
    return (parsed.netloc.lower(), parsed.path.rstrip("/"))


def local_paths(config, project_root: Path, base_url: str) -> dict[tuple[str, int], Path]:
    """Map (entity_type, id) to tracked local files on the same server."""
    from .config import get_client_for_target
    from .sync import EachDocsSyncer
    found: dict[tuple[str, int], Path] = {}
    for target in config.targets:
        url = get_client_for_target(config, target)[0]
        # Different paths on one host can be separate eLabFTW installations
        if _server_key(url) != _server_key(base_url):
            continue
        syncer = EachDocsSyncer(SimpleNamespace(base_url=url), target, project_root)
        try:
            mapping = syncer._load_mapping(migrate=False)
        except (ValueError, OSError):
            continue
        for name, eid in mapping.items():
            try:
                found.setdefault((target.entity, eid), syncer.file_path(name))
            except ValueError:
                continue
    return found


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def pull_command(ids: list, entity_type: str, target: str | None = None) -> str:
    """Suggested pull command. -t keeps the connection the search used."""
    from .sync import _shell_quote
    target_opt = f" -t {_shell_quote(target)}" if target else ""
    return "esync pull " + " ".join(f"--id {i}" for i in ids) + f" --entity {entity_type}{target_opt}"


def to_record(entity_type: str, entity: dict, base_url: str, local: Path | None,
              target: str | None = None) -> dict:
    eid = entity.get("id")
    record = {
        "entity": entity_type,
        "id": eid,
        "title": entity.get("title") or "",
        "author": entity.get("fullname") or " ".join(
            p for p in (entity.get("firstname"), entity.get("lastname")) if p) or None,
        "userid": entity.get("userid"),
        "date": entity.get("date"),
        "created_at": entity.get("created_at"),
        "modified_at": entity.get("modified_at"),
        "category": {"id": entity.get("category"), "title": entity.get("category_title")},
        "status": {"id": entity.get("status"), "title": entity.get("status_title")},
        "tags": split_tags(entity.get("tags")),
        "url": entity_url(base_url, entity_type, eid),
        "local_path": display_path(local) if local else None,
        "pull_command": None if local else pull_command([eid], entity_type, target),
    }
    return record


TRUNCATED_WARNING = (f"  ⚠ 種別ごとに {MAX_SCAN:,} 件まで確認して打ち切りました。"
                     "条件に合う記事が他にもある可能性があります。条件を絞ってください")


def format_text(records: list[dict], has_more: bool, next_offset: int | None,
                truncated: bool = False, target: str | None = None) -> str:
    if not records:
        return "\n".join(["  該当する記事はありません"] + ([TRUNCATED_WARNING] if truncated else []))
    lines = []
    for r in records:
        label = "実験ノート" if r["entity"] == "experiments" else "リソース"
        lines.append(f"  [{label}] #{r['id']}: {r['title'] or '無題'}")
        info = [f"作成者: {r['author'] or '不明'}", f"日付: {r['date'] or '-'}"]
        if r["modified_at"]:
            info.append(f"更新: {str(r['modified_at'])[:16]}")
        lines.append("    " + " / ".join(info))
        meta = []
        if r["category"]["title"]:
            meta.append(f"カテゴリ: {r['category']['title']}")
        if r["status"]["title"]:
            meta.append(f"ステータス: {r['status']['title']}")
        if r["tags"]:
            meta.append(f"タグ: {', '.join(r['tags'])}")
        if meta:
            lines.append("    " + " / ".join(meta))
        if r["local_path"]:
            lines.append(f"    ローカル: {r['local_path']}")
        if r.get("body") is not None:
            body = r["body"].strip()
            preview = body if len(body) <= BODY_PREVIEW else body[:BODY_PREVIEW] + "…（全文は --json --body）"
            lines.extend("    | " + line for line in (preview.splitlines() or [""]))
    lines.append("")
    summary = f"  {len(records)} 件表示"
    if has_more and next_offset is not None:
        summary += f"（続きは --offset {next_offset}）"
    lines.append(summary)
    if truncated:
        lines.append(TRUNCATED_WARNING)
    for entity_type in ENTITY_TYPES:
        ids = [r["id"] for r in records if r["entity"] == entity_type and not r["local_path"]]
        if ids:
            lines.append("  → 取得: " + pull_command(ids, entity_type, target))
    return "\n".join(lines)
