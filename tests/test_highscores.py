"""Tests for the highscore storage module."""
from __future__ import annotations

from pathlib import Path

import highscores as hs


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert hs.load(str(tmp_path / "nope.json")) == []


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    f = str(tmp_path / "hs.json")
    hs.save(f, [hs.Entry("ALICE", 30), hs.Entry("BOB", 10)])
    loaded = hs.load(f)
    assert [(e.name, e.score) for e in loaded] == [("ALICE", 30), ("BOB", 10)]


def test_sorted_desc_and_capped_at_ten(tmp_path: Path) -> None:
    entries = [hs.Entry(f"P{i}", i) for i in range(15)]
    top = hs._top(entries)
    assert len(top) == hs.TOP_N
    assert [e.score for e in top] == list(range(14, 4, -1))


def test_corrupt_file_recovers_and_backs_up(tmp_path: Path) -> None:
    f = tmp_path / "hs.json"
    f.write_text("{ this is not json")
    assert hs.load(str(f)) == []
    assert (tmp_path / "hs.json.bak").exists()       # corrupt file preserved
    assert not f.exists()


def test_invalid_entries_are_skipped(tmp_path: Path) -> None:
    f = tmp_path / "hs.json"
    f.write_text(
        '[{"name":"OK","score":5},'
        '{"name":"toolongname!!","score":9},'   # bad name (chars + length)
        '{"name":"NEG","score":-3},'             # negative score
        '{"name":"BOOL","score":true},'          # bool, not int
        '{"score":7},'                           # missing name
        '"garbage"]'                             # not an object
    )
    loaded = hs.load(str(f))
    assert [(e.name, e.score) for e in loaded] == [("OK", 5)]


def test_name_validation() -> None:
    assert hs.valid_name("Player 1")
    assert hs.valid_name("ABC")
    assert not hs.valid_name("")              # empty
    assert not hs.valid_name("waytoolongname")  # > 10
    assert not hs.valid_name("bad_name")      # underscore
    assert not hs.valid_name("emoji😀")


def test_sanitize_name() -> None:
    assert hs.sanitize_name("a_b-c!d e") == "abcd e"
    assert hs.sanitize_name("abcdefghijklmnop") == "abcdefghij"  # capped at 10


def test_add_inserts_and_rejects_invalid() -> None:
    base = [hs.Entry("A", 10)]
    assert [e.score for e in hs.add(base, "B", 20)] == [20, 10]
    assert hs.add(base, "bad!", 99) == hs._top(base)   # invalid name -> no-op
    assert hs.add(base, "C", -1) == hs._top(base)      # invalid score -> no-op


def test_qualifies() -> None:
    full = [hs.Entry(
        f"P{i}",
        (i + 1) * 10
    ) for i in range(hs.TOP_N)]  # 10..100
    assert hs.qualifies(full, 15)        # beats the lowest (10)
    assert not hs.qualifies(full, 10)    # ties the lowest -> no
    assert not hs.qualifies(full, 0)     # zero never qualifies
    assert hs.qualifies([hs.Entry("A", 5)], 1)  # list not full -> any > 0
