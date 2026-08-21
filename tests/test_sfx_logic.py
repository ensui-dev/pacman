"""Pure-logic tests for the sound wiring (ambient choice, event sounds)."""
from __future__ import annotations

from game.contract import GameEvent
from pacman_web.state import _EVENT_SOUNDS, _ambient_name


def test_silent_when_not_playing() -> None:
    assert _ambient_name(False, True, True, 10, 100) == ""


def test_eyes_beat_fright() -> None:
    assert _ambient_name(True, True, True, 10, 100) == "eyes"


def test_fright_beats_siren() -> None:
    assert _ambient_name(True, False, True, 10, 100) == "fright"


def test_siren_tiers_escalate_as_pellets_deplete() -> None:
    assert _ambient_name(True, False, False, 100, 100) == "siren0"
    assert _ambient_name(True, False, False, 50, 100) == "siren2"
    assert _ambient_name(True, False, False, 1, 100) == "siren4"


def test_siren_tier_capped_and_total_guarded() -> None:
    assert _ambient_name(True, False, False, 0, 100) == "siren4"
    assert _ambient_name(True, False, False, 0, 0) == "siren0"


def test_scoring_events_have_sounds() -> None:
    for ev in (GameEvent.SUPER_PACGUM_EATEN, GameEvent.GHOST_EATEN,
               GameEvent.LIFE_LOST, GameEvent.VICTORY):
        assert ev in _EVENT_SOUNDS
