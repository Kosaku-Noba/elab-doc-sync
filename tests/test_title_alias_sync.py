"""All-path title consistency + backward-compat property tests.

Feature: dedup-upload-and-title-alias
Property 6: タイトル入力は全同期経路で Resolved_Title に統一される
Property 5: 別名なしファイルは従来どおり File_Stem で変化しない
"""

from pathlib import Path

from hypothesis import given, settings, strategies as st

from elab_doc_sync.config import TargetConfig
from elab_doc_sync.sync import EachDocsSyncer, resolve_title


def _syncer(tmp, mock_client, title_map=None):
    docs = tmp / "docs"
    docs.mkdir(exist_ok=True)
    target = TargetConfig(
        title="", docs_dir="docs/", id_file=str(tmp / ".ids" / "default.id"),
        mode="each", title_map=title_map or {},
    )
    return EachDocsSyncer(mock_client, target, tmp), docs, target


def _mock_client():
    from unittest.mock import MagicMock
    c = MagicMock()
    c.base_url = "https://elab.example.com"
    c.list_uploads.return_value = []
    return c


_stem = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_-"),
    min_size=1, max_size=12,
).filter(lambda s: bool(s.strip()))

_title = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs"), blacklist_characters="\n\r#:\""),
    min_size=1, max_size=25,
).map(str.strip).filter(bool)


# Property 6: dry_run の title は resolve_title と一致する（全ソース）
@settings(max_examples=150, deadline=None)
@given(
    stem=_stem,
    source=st.sampled_from(["fm", "marker", "map", "none"]),
    value=_title,
    data=st.data(),
)
def test_dry_run_title_matches_resolver(tmp_path_factory, stem, source, value, data):
    tmp = tmp_path_factory.mktemp("alias")
    fname = f"{stem}.md"

    if source == "fm":
        body = f'---\ntitle: "{value}"\n---\n\n本文'
        title_map = {}
    elif source == "marker":
        body = f"# title: {value}\n\n本文"
        title_map = {}
    elif source == "map":
        body = "本文のみ（見出しなし）"
        title_map = {fname: value}
    else:
        body = "本文のみ（見出しなし）"
        title_map = {}

    client = _mock_client()
    syncer, docs, target = _syncer(tmp, client, title_map)
    (docs / fname).write_text(body, encoding="utf-8")

    rows = syncer.dry_run()
    row = next(r for r in rows if r["filename"] == fname)
    expected = resolve_title(body.strip(), fname, target)
    assert row["title"] == expected
    if source == "none":
        assert row["title"] == stem  # 後方互換: 素のファイルは File_Stem


# Property 6: メタハッシュの保存側と判定側が同一 Resolved_Title を使い、
# 別名ファイルで誤変更検知が起きない
@settings(max_examples=120, deadline=None)
@given(stem=_stem, marker=_title)
def test_meta_hash_symmetric_for_alias(tmp_path_factory, stem, marker):
    tmp = tmp_path_factory.mktemp("meta")
    fname = f"{stem}.md"
    body = f"# title: {marker}\n\n本文"

    client = _mock_client()
    syncer, docs, target = _syncer(tmp, client, {})
    (docs / fname).write_text(body, encoding="utf-8")

    resolved = resolve_title(body, fname, target)
    # 保存側と同じ Resolved_Title を使えば「メタ変更なし」と判定される
    syncer._save_meta_hash(fname, resolved, target.category, target.tags)
    assert syncer._has_meta_changed(fname, resolved, target.category, target.tags) is False


# Property 5: 別名なしファイルは Resolved_Title == File_Stem（後方互換）
@settings(max_examples=150, deadline=None)
@given(
    stem=_stem,
    body=st.text(max_size=50).filter(lambda s: not s.lstrip().startswith("#") and "---" not in s),
)
def test_alias_free_file_uses_stem(tmp_path_factory, stem, body):
    tmp = tmp_path_factory.mktemp("compat")
    fname = f"{stem}.md"
    client = _mock_client()
    syncer, docs, target = _syncer(tmp, client, {})
    (docs / fname).write_text(body, encoding="utf-8")

    rows = syncer.dry_run()
    row = next(r for r in rows if r["filename"] == fname)
    assert row["title"] == stem
