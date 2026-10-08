"""行単位の 3-way マージと競合マーカー。"""

import pytest

from elab_doc_sync.merge import merge_text, has_conflict_markers

BASE = "a\nb\nc\nd\ne"


@pytest.mark.parametrize('local,remote,expected', [
    ("a\nB\nc\nd\ne", "a\nb\nc\nD\ne", "a\nB\nc\nD\ne"),          # 別の行
    ("a\nB\nc\nd\ne", "a\nB\nc\nd\ne", "a\nB\nc\nd\ne"),          # 同じ変更
    (BASE, "a\nb\nc\nd\ne\nf", "a\nb\nc\nd\ne\nf"),               # リモートだけ追記
    ("x\n" + BASE, BASE + "\ny", "x\n" + BASE + "\ny"),           # 両端に追記
    ("a\nc\nd\ne", "a\nb\nc\nd", "a\nc\nd"),                      # 別の行を削除
])
def test_clean_merge(local, remote, expected):
    assert merge_text(BASE, local, remote) == (expected, 0)


def test_overlapping_edits_are_marked():
    text, conflicts = merge_text(BASE, "a\nL\nc\nd\ne", "a\nR\nc\nd\nE", remote_label="#7")
    assert conflicts == 1
    assert text == "a\n<<<<<<< ローカル\nL\n=======\nR\n>>>>>>> eLabFTW #7\nc\nd\nE"
    assert has_conflict_markers(text)


def test_unknown_base_marks_every_difference():
    text, conflicts = merge_text(None, "a\nL\nc", "a\nR\nc\nd")
    assert conflicts == 2
    assert text.startswith("a\n<<<<<<< ローカル\nL\n=======\nR\n>>>>>>> eLabFTW\nc\n")


@pytest.mark.parametrize('text', [
    "Title\n=======\nbody",
    "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> main",
    "<<<<<<< ローカル\nonly opening",
])
def test_other_marker_like_lines_are_not_conflicts(text):
    assert not has_conflict_markers(text)
