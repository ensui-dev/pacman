"""Tests for the real engine-backed Game orchestrator.

These need the ``mazegenerator`` wheel installed and the engine on the path
(``game.game`` adds ``pacman-core/`` itself). Run from the repo root.
"""
from __future__ import annotations

from game.contract import GameEvent, GameProtocol
from game.game import Game  # noqa: F401  (also puts pacman-core on the path)

from engine.ghost import State  # noqa: E402  (resolved via the import above)

CONFIG: dict[str, object] = {
    "lives": 3,
    "pacgum": 42,
    "points_per_pacgum": 15,
    "points_per_super_pacgum": 50,
    "points_per_ghost": 200,
    "seed": 42,
    "level_max_time": 90,
    "levels": [{"width": 21, "height": 21}, {"width": 15, "height": 15}],
}


def _new(**overrides: object) -> Game:
    cfg = dict(CONFIG)
    cfg.update(overrides)
    return Game(cfg)


def test_conforms_to_protocol() -> None:
    assert isinstance(_new(), GameProtocol)


def test_initial_view_shape() -> None:
    v = _new().view
    assert len(v["maze"]) == 21 and len(v["maze"][0]) == 21
    assert v["lives"] == 3 and v["level"] == 1 and v["score"] == 0
    assert len(v["super_pacgums"]) == 4
    assert len(v["ghosts"]) == 4
    assert {g["color"] for g in v["ghosts"]} == {
        "red",
        "pink",
        "cyan",
        "orange"
    }
    px, py = v["player"]
    assert v["maze"][py][px] != 15           # never spawns on a solid block


def test_density_fewer_than_classic() -> None:
    pct = len(_new(pacgum=30).view["pacgums"])
    classic = len(_new(classic_pacgums=True).view["pacgums"])
    assert 0 < pct < classic


def test_hostile_config_falls_back() -> None:
    g = _new(lives=True, points_per_pacgum=-5, level_max_time="lots")
    v = g.view
    assert v["lives"] == 3
    assert v["time_left"] == 90


def test_skip_level_then_tick_wins() -> None:
    g = _new()
    g.skip_level()
    assert GameEvent.LEVEL_WON in g.tick()
    assert g.is_level_won()


def test_final_level_skip_is_victory() -> None:
    g = _new()
    g.start_level(1)              # last of two levels (0-based)
    g.skip_level()
    assert GameEvent.VICTORY in g.tick()
    assert g.is_over()


def test_super_pacgum_frightens_ghosts() -> None:
    g = _new()
    sp = next(iter(g._superpacgums))
    g._player.set_position(*sp, g._map)
    g._eat([])
    assert g.view["frightened_ticks_left"] > 0
    assert all(gh.get_state() == State.FRIGHTENED
               for gh in g._ghosts)


def test_eaten_ghost_walks_home_and_revives() -> None:
    # Ambusher (offset target) is the case the engine gets wrong;
    g = _new()
    ghost = g._ghosts[1]
    for _ in range(20):
        g._move_ghosts()
    ghost.change_state(State.EATEN)
    for _ in range(600):
        g._move_ghosts()
        if ghost.get_state() == State.CHASE:
            break
    assert ghost.get_state() == State.CHASE          # revived, not stuck


def test_invincible_prevents_life_loss() -> None:
    g = _new()
    g.set_cheat("invincible", True)
    gpos = g._ghosts[0].get_position()
    g._player.set_position(*gpos, g._map)
    player = g._player.get_position()
    ghosts = [gh.get_position() for gh in g._ghosts]
    g._resolve_collisions(player, ghosts, [])
    assert g.view["lives"] == 3


def test_invincible_frightens_ghosts() -> None:
    g = _new()
    g.set_cheat("invincible", True)
    assert all(gh.get_state() == State.FRIGHTENED
               for gh in g._ghosts)
    g.tick()                                          # stays edible while on
    assert g.view["frightened_ticks_left"] > 0


def test_frightened_ghost_moves_at_half_speed() -> None:
    g = _new()
    ghost = g._ghosts[0]
    ghost.change_state(State.FRIGHTENED)
    moves = 0
    for _ in range(10):
        before = ghost.get_position()
        g._move_ghosts()
        if ghost.get_position() != before:
            moves += 1
    assert moves < 10                            # not every tick -> catchable


def test_chase_ghost_slightly_slower_than_player() -> None:
    g = _new()
    ghost = g._ghosts[0]                         # Agressor: always pathing
    moves = 0
    for _ in range(10):
        before = ghost.get_position()
        g._move_ghosts()
        if ghost.get_position() != before:
            moves += 1
    assert moves == 8                            # skips 1 tick in 5 (~80%)


def test_timeout_costs_a_life() -> None:
    g = _new(level_max_time=1)                    # player stays put (no input)
    lives0 = g.view["lives"]
    for _ in range(12):
        g.tick()
        if g.view["lives"] < lives0:
            break
    assert g.view["lives"] < lives0
