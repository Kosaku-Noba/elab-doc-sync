"""Property tests for the Title_Resolver (resolve_title).

Feature: dedup-upload-and-title-alias
Covers the marker-heading spec: タイトルは front matter の title →
本文先頭の `# title: ...` マーカー見出し → title_map → File_Stem の順で解決する。
素の見出し（`# 通常の見出し`）はタイトルに採用しない。
"""

from pathlib import Path
from types import SimpleNamespace

import yaml
from hypothesis import given, settings, strategies as st

from elab_doc_sync.sync import resolve_title


def _target(title_map=None):
    # resolve_title は target.title_map のみ参照する純関数なので最小構成でよい。
    return SimpleNamespace(title_map=title_map or {})


# 制御文字・改行・コロンを避けた安全なタイトル/値の文字列
_safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs"), blacklist_characters="\n\r#:\""),
    min_size=1,
    max_size=40,
).map(lambda s: s.strip()).filter(lambda s: bool(s))

_stems = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
).filter(lambda s: bool(s.strip()))


# ---------------------------------------------------------------------------
# Property 3: Resolved_Title は固定優先順位に従う
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(
    fm=st.one_of(st.none(), _safe_text),
    marker=st.one_of(st.none(), _safe_text),
    mapped=st.one_of(st.none(), _safe_text),
    stem=_stems,
    data=st.data(),
)
def test_priority_order(fm, marker, mapped, stem, data):
    """存在する最上位ソースの値が返る: front matter > marker heading > title_map > stem。"""
    parts = []
    if fm is not None:
        parts.append('---\n' + yaml.dump({'title': fm}, allow_unicode=True) + '---')
    if marker is not None:
        parts.append(f"# title: {marker}")
    parts.append("本文テキスト")
    text = "\n".join(parts)

    filename = f"{stem}.md"
    title_map = {filename: mapped} if mapped is not None else {}
    target = _target(title_map)

    expected = fm or marker or mapped or stem
    assert resolve_title(text, filename, target) == expected


# ---------------------------------------------------------------------------
# Property 3 (補強): 素の見出しは採用されない
# Validates: Requirement 3.2 (marker 限定), 6.1 (後方互換)
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(heading=_safe_text, stem=_stems)
def test_plain_heading_is_not_adopted(heading, stem):
    """`# title:` でない素の見出しはタイトルに採用されず File_Stem になる。"""
    text = f"# {heading}\n\n本文"
    filename = f"{stem}.md"
    assert resolve_title(text, filename, _target()) == stem


@settings(max_examples=100)
@given(marker=_safe_text, stem=_stems)
def test_marker_not_at_leading_line_is_ignored(marker, stem):
    """先頭でない（前に通常テキストがある）`# title:` は採用しない。"""
    text = f"intro text\n\n# title: {marker}"
    filename = f"{stem}.md"
    assert resolve_title(text, filename, _target()) == stem


@settings(max_examples=100)
@given(marker=_safe_text, stem=_stems)
def test_marker_case_insensitive(marker, stem):
    """`# TITLE:` など大文字小文字を問わずマーカーとして認識する。"""
    text = f"# TiTlE: {marker}\n\n本文"
    filename = f"{stem}.md"
    assert resolve_title(text, filename, _target()) == marker


# ---------------------------------------------------------------------------
# Property 4: Resolved_Title は決定的（参照透過）である
# Validates: Requirement 3.6
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(
    fm=st.one_of(st.none(), _safe_text),
    marker=st.one_of(st.none(), _safe_text),
    mapped=st.one_of(st.none(), _safe_text),
    stem=_stems,
)
def test_deterministic(fm, marker, mapped, stem):
    parts = []
    if fm is not None:
        parts.append('---\n' + yaml.dump({'title': fm}, allow_unicode=True) + '---')
    if marker is not None:
        parts.append(f"# title: {marker}")
    parts.append("本文")
    text = "\n".join(parts)
    filename = f"{stem}.md"
    target = _target({filename: mapped} if mapped is not None else {})

    first = resolve_title(text, filename, target)
    for _ in range(5):
        assert resolve_title(text, filename, target) == first


# ---------------------------------------------------------------------------
# Property 5: タイトルソース未指定なら Resolved_Title は File_Stem に等しい（後方互換）
# Validates: Requirements 3.6, 5.5, 6.1
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(stem=_stems, body=st.text(max_size=60).filter(lambda s: not s.lstrip().startswith("#") and "---" not in s))
def test_no_source_falls_back_to_stem(stem, body):
    filename = f"{stem}.md"
    assert resolve_title(body, filename, _target()) == stem
