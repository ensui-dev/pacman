"""Tests for the FakeGame stub.

Run from the repo root: ``python -m pytest tests/``.
"""
from __future__ import annotations

from game.contract import GameEvent, GameProtocol, GhostState
from game.fake import _CENTER_BLOCK, _HEIGHT, _SOLID, _WIDTH, FakeGame

CONFIG: dict[str, object] = {
    "lives": 3,
    "points_per_pacgum": 15,
    "points_per_super_pacgum": 50,
    "points_per_ghost": 200,
    "level_max_time": 90,
    "levels": [1, 2, 3],
}


def _new(**overrides: object) -> FakeGame:
    cfg = dict(CONFIG)
    cfg.update(overrides)
    return FakeGame(cfg)


def test_conforms_to_protocol() -> None:
    assert isinstance(_new(), GameProtocol)


def test_initial_view_shape() -> None:
    v = _new().view
    assert len(v["maze"]) == _HEIGHT and len(v["maze"][0]) == _WIDTH
    assert v["maze"][_CENTER_BLOCK[1]][_CENTER_BLOCK[0]] == _SOLID
    assert v["lives"] == 3 and v["level"] == 1 and v["score"] == 0
    assert v["time_left"] == 90
    assert len(v["ghosts"]) == 4
    # Player must never spawn on the solid central block.
    assert v["player"] != list(_CENTER_BLOCK)
    assert tuple(v["player"]) not in {tuple(p) for p in v["super_pacgums"]}


def test_hostile_config_falls_back_to_defaults() -> None:
    # bool-as-int, negative, and wrong-type values must not corrupt the game.
    g = _new(lives=True, points_per_pacgum=-5, level_max_time="lots")
    v = g.view
    assert v["lives"] == 3          # True rejected -> default
    assert v["time_left"] == 90     # str rejected -> default
    g.request_direction(1, 0)
    before = g.view["score"]
    g.tick()
    assert g.view["score"] >= before  # negative points clamped to >= 0


def test_walls_block_movement_off_grid() -> None:
    g = _new()
    start = tuple(g.view["player"])
    # The player starts mid-arena; drive into the top wall many times and
    # assert it can never leave the grid.
    g.request_direction(0, -1)
    for _ in range(20):
        g.tick()
        x, y = g.view["player"]
        assert 0 <= x < _WIDTH and 0 <= y < _HEIGHT
    assert start != (-1, -1)


def test_skip_level_then_tick_wins() -> None:
    g = _new()
    g.skip_level()
    events = g.tick()
    assert GameEvent.LEVEL_WON in events
    assert g.is_level_won()


def test_final_level_skip_is_victory() -> None:
    g = _new()
    g.start_level(2)  # last of three levels (0-based)
    g.skip_level()
    events = g.tick()
    assert GameEvent.VICTORY in events
    assert g.is_over()


def test_super_pacgum_frightens_ghosts() -> None:
    g = _new()
    # Walk the player onto a corner super-pacgum by forcing it there.
    g._player = (0, 0)
    g._eat([])
    assert g.view["frightened_ticks_left"] > 0
    assert any(gh["state"] == GhostState.FRIGHTENED.value
               for gh in g.view["ghosts"])


def test_invincible_cheat_prevents_life_loss() -> None:
    g = _new()
    g.set_cheat("invincible", True)
    # Drop a chasing ghost directly on the player and resolve.
    g._ghosts[0].pos = g._player
    g._ghosts[0].state = GhostState.CHASE
    g._resolve_collisions(
        g._player,
        [
            (9, 9),
            (9, 9),
            (9, 9),
            (9, 9)
        ],
        []
    )
    assert g.view["lives"] == 3


def test_timeout_costs_a_life() -> None:
    g = _new(level_max_time=1)
    lives0 = g.view["lives"]
    # 1 second == _TICKS_PER_SECOND ticks; run a couple of seconds' worth.
    for _ in range(12):
        g.tick()
        if g.view["lives"] < lives0:
            break
    assert g.view["lives"] < lives0
