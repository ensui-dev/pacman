"""Highscore storage: a plain, UI-agnostic module with defensive I/O.

The scores file is user-editable, so every value is validated on load *and*
save: names must be 1-10 chars of letters/digits/spaces, scores non-negative
ints, and only the top 10 are kept. Reads tolerate missing file (start empty)
and corrupt file (back it up, start empty); writes are atomic (temp + replace)
so a crash mid-write never corrupts the existing file.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

TOP_N = 10
MAX_NAME = 10
_NAME_RE = re.compile(r"^[A-Za-z0-9 ]{1,10}$")


@dataclass
class Entry:
    """One highscore row."""

    name: str
    score: int


def valid_name(name: str) -> bool:
    """True if ``name`` is 1-10 chars of letters, digits or spaces."""
    return bool(_NAME_RE.fullmatch(name))


def sanitize_name(name: str) -> str:
    """Strip disallowed characters and cap at 10 — for live input filtering."""
    return "".join(c for c in name if c.isalnum() or c == " ")[:MAX_NAME]


def _coerce(item: object) -> Entry | None:
    """Turn one raw JSON item into a valid :class:`Entry`, or ``None``."""
    if not isinstance(item, dict):
        return None
    name, score = item.get("name"), item.get("score")
    if not isinstance(name, str) or not valid_name(name):
        return None
    if isinstance(score, bool) or not isinstance(score, int) or score < 0:
        return None
    return Entry(name=name, score=score)


def _top(entries: list[Entry]) -> list[Entry]:
    """Sort by score descending (stable) and keep the top ``TOP_N``."""
    return sorted(entries, key=lambda e: e.score, reverse=True)[:TOP_N]


def load(path: str) -> list[Entry]:
    """Load and validate the top scores; never raises.

    Missing file → empty. Corrupt/unreadable file → back it up as ``*.bak`` and
    return empty. Invalid individual entries are skipped.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        try:
            p.replace(p.with_name(p.name + ".bak"))
        except OSError:
            pass
        return []
    if not isinstance(raw, list):
        return []
    return _top([e for e in (_coerce(i) for i in raw) if e is not None])


def save(path: str, entries: list[Entry]) -> None:
    """Write the top entries (temp file + replace)."""
    top = _top(entries)
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    payload = [{"name": e.name, "score": e.score} for e in top]
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(p)  # atomic on the same filesystem


def add(entries: list[Entry], name: str, score: int) -> list[Entry]:
    """Return a new top list with ``(name, score)`` inserted if valid."""
    if not valid_name(name) or isinstance(score, bool) \
            or not isinstance(score, int) or score < 0:
        return _top(entries)
    return _top([*entries, Entry(name=name, score=score)])


def qualifies(entries: list[Entry], score: int) -> bool:
    """True if ``score`` (> 0) would make the top-10 list."""
    if score <= 0:
        return False
    top = _top(entries)
    return len(top) < TOP_N or score > top[-1].score
