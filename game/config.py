"""Config loading — wraps the engine's parser with a path-based interface.

The engine parser reads ``sys.argv`` directly; until it accepts a path argument
(request 03 §2.1) this wraps it by setting argv temporarily, so we reuse its
comment stripping, validation and clamping instead of duplicating them. Used by
``pac-man.py`` (fail fast on a bad config) and by the Reflex app (which reads the
resolved path from ``$PACMAN_CONFIG``).
"""
from __future__ import annotations

import os
import sys

# Temporary: put the engine/parser on the path until the repo restructure moves
# them to the root and this shim (and game.game's) can be dropped.
_CORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pacman-core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

# Safe defaults used when no config is provided (dev) or one fails to load.
DEFAULT_CONFIG: dict[str, object] = {
    "lives": 3,
    "pacgum": 42,
    "points_per_pacgum": 15,
    "points_per_super_pacgum": 50,
    "points_per_ghost": 200,
    "seed": 42,
    "level_max_time": 90,
    "levels": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "highscore_filename": "highscores.json",
}


def load_config(path: str) -> dict[str, object]:
    """Parse and validate a config file; raises ``ParserError`` on failure."""
    from parser.parser import parser as _parser
    saved = sys.argv
    try:
        sys.argv = ["pac-man.py", path]
        return _parser()
    finally:
        sys.argv = saved


def runtime_config() -> dict[str, object]:
    """Config for the running app: from ``$PACMAN_CONFIG`` if set, else default.

    Never raises — a missing/broken config falls back to the defaults so the UI
    process can't crash at import (the launcher validates and reports errors).
    """
    path = os.environ.get("PACMAN_CONFIG")
    if not path:
        return dict(DEFAULT_CONFIG)
    try:
        return load_config(path)
    except Exception:
        return dict(DEFAULT_CONFIG)
