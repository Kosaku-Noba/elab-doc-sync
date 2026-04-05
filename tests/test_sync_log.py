"""Tests for sync_log.py (L-01 ~ L-11)."""

import json
import os
from pathlib import Path

import pytest

from elab_doc_sync.sync_log import record, read_log, format_log


# L-01
def test_record_normal(tmp_path):
    p = tmp_path / "log.jsonl"
    record(p, action="push", target="t", entity="items", entity_id=1, files=["a.md"])
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "push"
    assert entry["entity_id"] == 1


# L-02
def test_record_multiple(tmp_path):
    p = tmp_path / "log.jsonl"
    record(p, action="push", target="a", entity="items", entity_id=1)
    record(p, action="pull", target="b", entity="experiments", entity_id=2)
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


# L-03
def test_record_creates_dir(tmp_path):
    p = tmp_path / "sub" / "dir" / "log.jsonl"
    record(p, action="push", target="t", entity="items", entity_id=1)
    assert p.exists()


# L-04
def test_record_best_effort(tmp_path):
    p = tmp_path / "readonly" / "log.jsonl"
    p.parent.mkdir()
    p.parent.chmod(0o444)
    try:
        record(p, action="push", target="t", entity="items", entity_id=1)  # should not raise
    finally:
        p.parent.chmod(0o755)


# L-05
def test_read_log_normal(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(5):
        record(p, action="push", target=f"t{i}", entity="items", entity_id=i)
    entries = read_log(p)
    assert len(entries) == 5
    assert entries[-1]["entity_id"] == 4


# L-06
def test_read_log_limit(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(10):
        record(p, action="push", target=f"t{i}", entity="items", entity_id=i)
    entries = read_log(p, limit=3)
    assert len(entries) == 3
    assert entries[0]["entity_id"] == 7  # last 3: 7,8,9


# L-07
def test_read_log_skip_broken(tmp_path):
    p = tmp_path / "log.jsonl"
    record(p, action="push", target="ok", entity="items", entity_id=1)
    with open(p, "a") as f:
        f.write("NOT JSON\n")
    record(p, action="pull", target="ok2", entity="items", entity_id=2)
    entries = read_log(p)
    assert len(entries) == 2
    assert entries[0]["entity_id"] == 1
    assert entries[1]["entity_id"] == 2


# L-08
def test_read_log_no_file(tmp_path):
    entries = read_log(tmp_path / "nonexistent.jsonl")
    assert entries == []


# L-09
def test_read_log_broken_utf8(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_bytes(b'{"action":"push"}\n\xff\xfe\n{"action":"pull"}\n')
    entries = read_log(p)
    assert len(entries) >= 1  # at least the valid lines


# L-10
def test_format_log_normal(tmp_path):
    p = tmp_path / "log.jsonl"
    record(p, action="push", target="Doc", entity="items", entity_id=42, files=["a.md", "b.md"])
    entries = read_log(p)
    output = format_log(entries)
    assert "push" in output
    assert "Doc" in output
    assert "#42" in output
    assert "2件" in output


# L-11
def test_format_log_empty():
    output = format_log([])
    assert "まだありません" in output
