"""Tests for esync search (SRCH-01 ~)."""

import datetime as dt
import json
import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from elab_doc_sync.cli import cmd_search
from elab_doc_sync.search import SearchQuery, build_params, search, split_tags, format_text, to_record


class FakeClient:
    """Serves fixed entity lists with limit/offset and records the request params."""

    base_url = "https://elab.example.com"

    def __init__(self, items=None, experiments=None, user=None, bodies=None):
        self.data = {"items": items or [], "experiments": experiments or []}
        self.user = user or {"userid": 7, "team": 3}
        self.bodies = bodies or {}
        self.requests = []

    def _req(self, method, path, params=None, **kw):
        entity = path.rsplit("/", 1)[-1]
        self.requests.append((entity, dict(params or {})))
        offset = (params or {}).get("offset", 0)
        limit = (params or {}).get("limit", 15)
        return MagicMock(json=MagicMock(return_value=self.data[entity][offset:offset + limit]))

    def get_user_info(self):
        return self.user

    def get_entity(self, entity_type, entity_id):
        return self.bodies[(entity_type, entity_id)]


def _item(i, **kw):
    base = {"id": i, "title": f"T{i}", "fullname": "Taro Yamada", "userid": 7, "date": "2026-01-0%d" % (i % 9 + 1),
            "created_at": "2026-01-01 10:00:00", "modified_at": f"2026-02-{i % 28 + 1:02d} 10:00:00",
            "category": 4, "category_title": "Protocol", "status": 1, "status_title": "Running",
            "tags": "a|b", "team": 3}
    base.update(kw)
    return base


# SRCH-01: 各条件がサーバー側のパラメータに変換される
def test_build_params_maps_filters():
    q = SearchQuery(keyword=" pcr ", entities=("items",), author="Yamada", since=dt.date(2026, 1, 1),
                    until=dt.date(2026, 3, 31), tags=["x", "y"], category="12", status="Done",
                    order="date", sort="asc")
    p = build_params(q, my_userid=7)
    assert p["q"] == "pcr"
    assert p["tags[]"] == ["x", "y"]
    assert p["cat"] == "12"
    assert p["order"] == "date" and p["sort"] == "asc"
    assert p["extended"] == 'author:"Yamada" date:>=20260101 date:<=20260331 status:s:"Done"'
    assert "owner" not in p


# SRCH-02: --author me / ユーザー ID は owner に、--scope mine は自分の ID に
def test_build_params_owner():
    assert build_params(SearchQuery(author="me"), 7)["owner"] == "7"
    assert build_params(SearchQuery(author="42"), 7)["owner"] == "42"
    p = build_params(SearchQuery(scope="mine"), 7)
    assert p["owner"] == "7" and p["scope"] == 1
    with pytest.raises(ValueError, match="別のユーザー"):
        build_params(SearchQuery(author="42", scope="mine"), 7)


# SRCH-03: 詳細検索の値は引用し、LIKE のワイルドカードを無効にする
def test_build_params_quotes_values():
    p = build_params(SearchQuery(author='a"b_c%', category="My Cat"), None)
    assert p["extended"] == 'author:"a\\"b\\_c\\%" category:s:"My Cat"'
    with pytest.raises(ValueError, match="改行"):
        build_params(SearchQuery(author="a\nb"), None)


# SRCH-04: 種別をまたぐ ID 指定は曖昧なので拒否する
def test_build_params_id_needs_single_entity():
    with pytest.raises(ValueError, match="--entity"):
        build_params(SearchQuery(category="5"), None)
    with pytest.raises(ValueError, match="--entity"):
        build_params(SearchQuery(status="2"), None)


# SRCH-05: 日付の前後関係を検証する
def test_build_params_rejects_reversed_dates():
    with pytest.raises(ValueError, match="--since"):
        build_params(SearchQuery(since=dt.date(2026, 2, 1), until=dt.date(2026, 1, 1)), None)
    with pytest.raises(ValueError, match="--updated-since"):
        build_params(SearchQuery(updated_since=dt.date(2026, 2, 1), updated_until=dt.date(2026, 1, 1)), None)


# SRCH-06: limit/offset と続きの有無
def test_search_pagination():
    client = FakeClient(items=[_item(i) for i in range(1, 8)])
    r = search(client, SearchQuery(entities=("items",), limit=3, offset=2))
    assert [e["id"] for _, e in r["results"]] == [3, 4, 5]
    assert r["has_more"] is True and r["next_offset"] == 5
    r = search(client, SearchQuery(entities=("items",), limit=10))
    assert len(r["results"]) == 7 and r["has_more"] is False and r["next_offset"] is None


# SRCH-07: 最終更新日はクライアント側で絞り込み、更新順なら古い記事で打ち切る
def test_search_updated_filter_stops_early():
    items = [_item(i, modified_at=f"2026-03-{30 - i:02d} 09:00:00") for i in range(1, 300)
             if 30 - i >= 1] + [_item(900, modified_at="2025-12-01 00:00:00")] * 250
    client = FakeClient(items=items)
    r = search(client, SearchQuery(entities=("items",), updated_since=dt.date(2026, 3, 20),
                                   updated_until=dt.date(2026, 3, 25), limit=50))
    assert [e["id"] for _, e in r["results"]] == [5, 6, 7, 8, 9, 10]
    assert r["has_more"] is False
    assert client.requests[0][1]["order"] == "lastchange"
    assert len(client.requests) == 1  # 1 ページ目で古い記事に達して終了


# SRCH-08: 固定表示（pinned）の古い記事では打ち切らない
def test_search_updated_filter_skips_pinned():
    items = [_item(1, modified_at="2020-01-01 00:00:00", is_pinned=1), _item(2, modified_at="2026-03-01 00:00:00")]
    r = search(FakeClient(items=items), SearchQuery(entities=("items",), updated_since=dt.date(2026, 1, 1)))
    assert [e["id"] for _, e in r["results"]] == [2]


# SRCH-09: all は両種別を取得し、指定の並び順で統合する
def test_search_all_merges_by_order():
    items = [_item(1, modified_at="2026-03-05 00:00:00"), _item(2, modified_at="2026-03-01 00:00:00")]
    exps = [_item(10, modified_at="2026-03-03 00:00:00")]
    client = FakeClient(items=items, experiments=exps)
    r = search(client, SearchQuery(limit=2))
    assert [(t, e["id"]) for t, e in r["results"]] == [("items", 1), ("experiments", 10)]
    assert r["has_more"] is True and r["next_offset"] == 2
    assert {req[0] for req in client.requests} == {"items", "experiments"}


# SRCH-10: --scope team は現在のチームの記事だけにする
def test_search_scope_team_filters_team():
    items = [_item(1, team=3), _item(2, team=9)]
    r = search(FakeClient(items=items), SearchQuery(entities=("items",), scope="team"))
    assert [e["id"] for _, e in r["results"]] == [1]


def test_split_tags():
    assert split_tags("a|b") == ["a", "b"]
    assert split_tags(None) == []
    assert split_tags([{"tag": "x"}, "y"]) == ["x", "y"]


# SRCH-11: 人向け出力に作成者・日付・タグと pull の案内が出る
def test_format_text_shows_fields_and_pull_hint():
    recs = [to_record("items", _item(1), "https://e", None),
            to_record("experiments", _item(2), "https://e", None)]
    out = format_text(recs, True, 20)
    assert "[リソース] #1: T1" in out and "[実験ノート] #2: T2" in out
    assert "作成者: Taro Yamada" in out and "タグ: a, b" in out and "カテゴリ: Protocol" in out
    assert "続きは --offset 20" in out
    assert "esync pull --id 1 --entity items" in out
    assert "esync pull --id 2 --entity experiments" in out
    assert "該当する記事はありません" in format_text([], False, None)


def _write_config(tmp_path):
    data = {"elabftw": {"url": "https://elab.example.com", "api_key": "key", "verify_ssl": False},
            "targets": [{"title": "T", "docs_dir": "docs/", "pattern": "*.md", "mode": "each", "entity": "items",
                         "id_file": ".elab-sync-ids/default.id"}]}
    cfg = tmp_path / ".elab-sync.yaml"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    return cfg


def _args(cfg, **kw):
    base = dict(config=str(cfg), target=None, keyword=[], entity_type="items", author=None, since=None, until=None,
                updated_since=None, updated_until=None, tag=None, category=None, status=None, scope=None,
                order=None, sort=None, limit=20, offset=0, json=False, body=False)
    base.update(kw)
    return Namespace(**base)


# SRCH-12: --json は機械可読な結果を出し、追跡中の文書はローカルパスを示す
def test_cmd_search_json_with_local_path_and_body(tmp_path, capsys, monkeypatch):
    cfg = _write_config(tmp_path)
    (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / ".elab-sync-ids").mkdir()
    (tmp_path / ".elab-sync-ids" / "mapping.json").write_text(json.dumps({"a.md": 1}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    fake = FakeClient(items=[_item(1), _item(2)],
                      bodies={("items", 1): {"body": "<p>Hello</p>", "content_type": 1},
                              ("items", 2): {"body": "&gt; quote", "content_type": 2}})
    with patch("elab_doc_sync.cli._direct_client", return_value=fake):
        cmd_search(_args(cfg, keyword=["pcr", "buffer"], tag=["a"], json=True, body=True))
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 2 and out["has_more"] is False
    first, second = out["results"]
    assert first["local_path"] == "docs/a.md" and first["pull_command"] is None
    assert second["local_path"] is None and second["pull_command"] == "esync pull --id 2 --entity items"
    assert first["body"] == "Hello" and second["body"] == "> quote"
    assert first["url"] == "https://elab.example.com/database.php?mode=view&id=1"
    assert first["tags"] == ["a", "b"] and first["author"] == "Taro Yamada"
    assert fake.requests[0][1]["q"] == "pcr buffer"


# SRCH-13: 日付形式の誤りは引数エラー
def test_cmd_search_bad_date(tmp_path):
    cfg = _write_config(tmp_path)
    with patch("elab_doc_sync.cli._direct_client", return_value=FakeClient()):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            cmd_search(_args(cfg, since="2026/01/01"))


# SRCH-14: argparse から search が呼べる（共通オプションを前に書いても良い）
def test_main_parses_search(tmp_path, monkeypatch):
    cfg = _write_config(tmp_path)
    seen = {}
    monkeypatch.setattr(sys, "argv", ["esync", "-c", str(cfg), "search", "pcr", "--entity", "resources",
                                      "--author", "me", "--tag", "a", "--tag", "b", "--updated-since", "2026-01-01",
                                      "--json"])
    monkeypatch.setattr("elab_doc_sync.update_check.notify_if_update_available", lambda *a, **k: None)
    with patch("elab_doc_sync.cli.cmd_search", side_effect=lambda a: seen.update(vars(a))):
        import elab_doc_sync.cli as cli
        cli.main()
    assert seen["keyword"] == ["pcr"] and seen["entity_type"] == "resources"
    assert seen["tag"] == ["a", "b"] and seen["updated_since"] == "2026-01-01" and seen["json"] is True


# SRCH-15: -t で検索したときは取得コマンドにも -t を付ける
def test_pull_command_keeps_target():
    rec = to_record("items", _item(1), "https://e", None, target="週報 A")
    assert rec["pull_command"] == "esync pull --id 1 --entity items -t '週報 A'"
    out = format_text([rec], False, None, target="週報 A")
    assert "→ 取得: esync pull --id 1 --entity items -t '週報 A'" in out


# SRCH-16: 走査上限で打ち切ったときは続きを案内せず、警告と truncated を返す
def test_search_scan_limit_is_reported(monkeypatch):
    monkeypatch.setattr("elab_doc_sync.search.MAX_SCAN", 200)
    items = [_item(i, modified_at="2026-01-01 00:00:00") for i in range(1, 400)]
    r = search(FakeClient(items=items),
               SearchQuery(entities=("items",), order="id", updated_since=dt.date(2026, 3, 1)))
    assert r["results"] == [] and r["truncated"] is True
    assert r["has_more"] is False and r["next_offset"] is None
    assert "打ち切りました" in format_text([], False, None, truncated=True)


# SRCH-17: 1 種別・クライアント側の絞り込みなしならサーバーの offset を使う
def test_search_single_entity_uses_server_offset():
    client = FakeClient(items=[_item(i) for i in range(1, 30)])
    r = search(client, SearchQuery(entities=("items",), limit=5, offset=20))
    assert [e["id"] for _, e in r["results"]] == [21, 22, 23, 24, 25]
    assert client.requests == [("items", {"limit": 6, "offset": 20})]
    assert r["next_offset"] == 25


# SRCH-18: 種別をまたぐ検索で、先頭のピン留めが上位の記事の取得枠を使わない
def test_search_all_pinned_do_not_hide_newer_entries():
    items = [_item(1, modified_at="2020-01-01 00:00:00", is_pinned=1),
             _item(2, modified_at="2026-03-05 00:00:00")]
    exps = [_item(10, modified_at="2026-03-03 00:00:00")]
    r = search(FakeClient(items=items, experiments=exps), SearchQuery(limit=1))
    assert [(t, e["id"]) for t, e in r["results"]] == [("items", 2)]
    assert r["has_more"] is True


# SRCH-19: --scope team はチームを確認できない記事を除き、現在のチーム不明ならエラー
def test_search_scope_team_requires_team():
    items = [_item(1, team=3), _item(2, team=None), _item(3)]
    del items[2]["team"]
    r = search(FakeClient(items=items), SearchQuery(entities=("items",), scope="team"))
    assert [e["id"] for _, e in r["results"]] == [1]
    with pytest.raises(ValueError, match="チーム"):
        search(FakeClient(items=items, user={"userid": 7}), SearchQuery(entities=("items",), scope="team"))


# SRCH-20: 同じホストでもパスが異なる接続先の追跡情報は使わない
def test_local_paths_requires_same_base_path(tmp_path):
    from elab_doc_sync.config import load_config
    from elab_doc_sync.search import local_paths
    cfg = _write_config(tmp_path)
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["elabftw"]["url"] = "https://elab.example.com/lab-a/"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / ".elab-sync-ids").mkdir()
    (tmp_path / ".elab-sync-ids" / "mapping.json").write_text(json.dumps({"a.md": 1}), encoding="utf-8")
    config = load_config(cfg)
    assert local_paths(config, tmp_path, "https://elab.example.com/lab-b") == {}
    assert ("items", 1) in local_paths(config, tmp_path, "https://ELAB.example.com/lab-a")
