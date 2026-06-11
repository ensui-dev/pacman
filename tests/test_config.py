"""Tests for config loading (path-based wrapper over the engine parser)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from game.config import DEFAULT_CONFIG, load_config, runtime_config

_GOOD = """{
    # a comment line is allowed
    "lives": 5,
    "pacgum": 70,
    "levels": [{"width": 19, "height": 19}]
}
"""


def test_load_strips_comments_and_validates(tmp_path: Path) -> None:
    f = tmp_path / "config.json"
    f.write_text(_GOOD)
    cfg = load_config(str(f))
    assert cfg["lives"] == 5 and cfg["pacgum"] == 70
    assert cfg["levels"] == [{"width": 19, "height": 19}]


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        load_config(str(tmp_path / "nope.json"))


def test_runtime_config_uses_env(tmp_path: Path) -> None:
    f = tmp_path / "config.json"
    f.write_text(_GOOD)
    os.environ["PACMAN_CONFIG"] = str(f)
    try:
        assert runtime_config()["lives"] == 5
    finally:
        del os.environ["PACMAN_CONFIG"]


def test_runtime_config_defaults_without_env() -> None:
    os.environ.pop("PACMAN_CONFIG", None)
    assert runtime_config()["lives"] == DEFAULT_CONFIG["lives"]


def test_runtime_config_bad_path_falls_back(tmp_path: Path) -> None:
    os.environ["PACMAN_CONFIG"] = str(tmp_path / "missing.json")
    try:
        assert runtime_config() == dict(DEFAULT_CONFIG)   # never raises
    finally:
        del os.environ["PACMAN_CONFIG"]
