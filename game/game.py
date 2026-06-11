"""Real ``Game`` orchestrator — implements ``GameProtocol`` on the core engine.

This is the seam the UI was built against via ``FakeGame``; swapping to this
class needs no UI change. It owns the rules the engine doesn't: collisions,
scoring, the frightened/level timers, pacgum density, level progression and
win/lose. Movement, pathing and ghost AI come from the colleague's engine
(``Map`` / ``Player`` / ``Ghost`` / strategies).

A few engine quirks are worked around here rather than in the engine (which we
consume as-is) and are filed as change requests:
  * ``Player`` has no direction buffering and hardcodes lives → buffering and
    lives live here.
  * ``Ghost.move`` mutates the passed ``game_state`` and, when EATEN, steers by
    the strategy's offset target (so Ambusher/Unpredictable may miss home) → we
    pass a fresh dict per ghost and, for EATEN ghosts, neutralise the offset
    (``player_dir=(0,0)``, ``blinky_pos=home``) so every ghost walks home.
"""
from __future__ import annotations

import os
import random
import sys
from typing import Optional

from game.contract import GameEvent, GameView, GhostView
from game.maze import MazeGenerationError, build_maze

# engine/ and parser/ live in the pacman-core git submodule (the colleague's
# repo). Append it to the path — appending (not inserting) keeps site-packages
# ahead, so the installed mazegenerator *wheel* wins over the submodule's
# vendored copy (avoiding the import-shadowing trap), while engine/parser,
# which exist only here, still resolve.
_CORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pacman-core")
if _CORE not in sys.path:
    sys.path.append(_CORE)

from engine import Map                                    # noqa: E402
from engine.ghost import Ghost, State, Strategy           # noqa: E402
from engine.player import Player                          # noqa: E402

Pos = tuple[int, int]

_TICKS_PER_SECOND = 5
_FRIGHTENED_TICKS = 6 * _TICKS_PER_SECOND
_SPAWN_PROTECT_TICKS = 2 * _TICKS_PER_SECOND
_MIN_SIZE, _MAX_SIZE, _DEFAULT_SIZE = 15, 61, 21

_DIR_NAME = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}
_STRATEGIES = (Strategy.AGRESSOR, Strategy.AMBUSHER,
               Strategy.UNPREDICTABLE, Strategy.WANDERER)
_STRATEGY_COLOR = {
    Strategy.AGRESSOR: "red",
    Strategy.AMBUSHER: "pink",
    Strategy.UNPREDICTABLE: "cyan",
    Strategy.WANDERER: "orange",
}
_STATE_NAME = {
    State.CHASE: "chase",
    State.SCATTER: "chase",
    State.FRIGHTENED: "frightened",
    State.EATEN: "eaten",
}


def _to_int(config: dict[str, object], key: str, default: int,
            lo: int, hi: int) -> int:
    """Read ``key`` as an int clamped to ``[lo, hi]``; never trusts config."""
    val = config.get(key, default)
    if isinstance(val, bool) or not isinstance(val, int):
        return default
    return max(lo, min(hi, val))


class Game:
    """Engine-backed implementation of the frozen ``GameProtocol``."""

    def __init__(self, config: dict[str, object]) -> None:
        """Read config defensively and start on level 0."""
        self._config = config
        self._pts_pacgum = _to_int(config, "points_per_pacgum", 10, 0, 10_000)
        self._pts_super = _to_int(
            config, "points_per_super_pacgum", 50, 0, 10_000)
        self._pts_ghost = _to_int(config, "points_per_ghost", 200, 0, 10_000)
        self._max_time = _to_int(config, "level_max_time", 90, 1, 3_600)
        self._start_lives = _to_int(config, "lives", 3, 1, 99)
        self._pacgum_pct = _to_int(config, "pacgum", 42, 0, 100)
        self._seed = _to_int(config, "seed", 42, 0, 2_000_000_000)
        self._classic = config.get("classic_pacgums") is True
        levels = config.get("levels")
        self._levels = levels if isinstance(levels, list) and levels else []
        self._level_count = len(self._levels) if self._levels else 10

        self._score = 0
        self._lives = self._start_lives
        self._game_over = False
        self._won_game = False
        self._cheats: dict[str, bool] = {}
        self.start_level(0)

    # ------------------------------------------------------------------ setup
    def _level_size(self, index: int) -> tuple[int, int]:
        """Maze size for a level, from config, clamped to a safe range."""
        width = height = _DEFAULT_SIZE
        if 0 <= index < len(self._levels):
            entry = self._levels[index]
            if isinstance(entry, dict):
                width = _to_int(entry, "width", _DEFAULT_SIZE,
                                _MIN_SIZE, _MAX_SIZE)
                height = _to_int(entry, "height", _DEFAULT_SIZE,
                                 _MIN_SIZE, _MAX_SIZE)
        return width, height

    def _make_maze(self, width: int, height: int,
                   seed: int) -> list[list[int]]:
        """Generate a maze, falling back to a safe default if it fails."""
        try:
            return build_maze(width, height, seed)
        except MazeGenerationError:
            return build_maze(_DEFAULT_SIZE, _DEFAULT_SIZE, seed)

    def start_level(self, index: int) -> None:
        """(Re)initialise the maze, pellets, player and ghosts for a level."""
        self._level = index
        self._level_won = False
        self._frightened_ticks = 0
        self._protect_ticks = 0
        self._tick_in_second = 0
        self._time_left = self._max_time
        self._requested: Optional[Pos] = None
        self._facing = "left"
        self._fright_skip = False        # frightened ghosts move at half speed

        width, height = self._level_size(index)
        seed = self._seed if index == 0 else 0     # level 1 fixed, rest random
        self._maze = self._make_maze(width, height, seed)
        self._map = Map(self._maze)
        self._w, self._h = self._map.get_width(), self._map.get_height()

        self._build_pellets(index)
        spawn = self._nearest_open((self._w // 2, self._h // 2))
        self._player = Player(spawn, self._map)
        self._player.set_direction(None)
        self._pacgums.discard(spawn)
        self._spawn_ghosts()

    def _build_pellets(self, index: int) -> None:
        """Pellets: a seeded percentage of corridors (all in classic mode)."""
        corridors = sorted(self._map.get_pacgums())
        self._superpacgums: set[Pos] = set(self._map.get_superpacgums())
        if self._classic or self._pacgum_pct >= 100:
            self._pacgums = set(corridors)
            return
        rng = random.Random(self._seed * 100_000 + index)
        keep = round(len(corridors) * self._pacgum_pct / 100)
        keep = min(len(corridors), max(1, keep)) if corridors else 0
        self._pacgums = set(rng.sample(corridors, keep))

    def _spawn_ghosts(self) -> None:
        """Place the four personalities at the (nearest-open) corners."""
        corners = [(0, 0), (self._w - 1, 0), (0, self._h - 1),
                   (self._w - 1, self._h - 1)]
        self._homes = [self._nearest_open(c) for c in corners]
        self._ghosts = [
            Ghost(strategy, home, self._map)
            for strategy, home in zip(_STRATEGIES, self._homes)
        ]

    # ------------------------------------------------------------------ input
    def request_direction(self, dx: int, dy: int) -> None:
        """Buffer a heading; applied at the next tick where it is legal."""
        if (dx, dy) in _DIR_NAME:
            self._requested = (dx, dy)

    # ------------------------------------------------------------------- step
    def tick(self) -> list[GameEvent]:
        """Advance one step; return events in occurrence order."""
        if self._game_over or self._level_won:
            return []
        events: list[GameEvent] = []

        self._advance_timers(events)
        if self._game_over:
            return events
        if self._cheats.get("invincible"):
            self._frighten_all()          # cheat: ghosts stay edible

        prev_player = self._player.get_position()
        self._move_player(events)
        prev_ghosts = [g.get_position() for g in self._ghosts]
        if not self._cheats.get("freeze"):
            self._move_ghosts()

        self._resolve_collisions(prev_player, prev_ghosts, events)
        self._check_win(events)
        return events

    def _advance_timers(self, events: list[GameEvent]) -> None:
        """Tick the frightened, spawn-protection and level-timeout clocks."""
        if self._frightened_ticks > 0:
            self._frightened_ticks -= 1
            if self._frightened_ticks == 0:
                for g in self._ghosts:
                    if g.get_state() == State.FRIGHTENED:
                        g.change_state(State.CHASE)
        if self._protect_ticks > 0:
            self._protect_ticks -= 1

        self._tick_in_second += 1
        if self._tick_in_second >= _TICKS_PER_SECOND:
            self._tick_in_second = 0
            self._time_left -= 1
            if self._time_left <= 0:
                self._lose_life(events)   # frozen: timeout costs a life
                self._time_left = self._max_time

    def _move_player(self, events: list[GameEvent]) -> None:
        """Apply the buffered turn, then step (twice with speed cheat)."""
        steps = 2 if self._cheats.get("speed") else 1
        for _ in range(steps):
            self._apply_direction()
            self._player.move()
            d = self._player.get_direction()
            if d is not None:
                self._facing = _DIR_NAME[d]
            self._eat(events)

    def _apply_direction(self) -> None:
        """Turn to the buffered heading if the next cell is open."""
        if self._requested is None:
            return
        pos = self._player.get_position()
        target = (pos[0] + self._requested[0], pos[1] + self._requested[1])
        if target in self._map.neighbors(pos):
            self._player.set_direction(self._requested)
            self._requested = None

    def _frighten_all(self) -> None:
        """Make every live ghost edible (drives the invincibility cheat)."""
        for g in self._ghosts:
            if g.get_state() in (State.CHASE, State.SCATTER):
                g.change_state(State.FRIGHTENED)
        self._frightened_ticks = max(self._frightened_ticks, _FRIGHTENED_TICKS)

    def _eat(self, events: list[GameEvent]) -> None:
        """Consume any pellet under the player and score it."""
        pos = self._player.get_position()
        if pos in self._pacgums:
            self._pacgums.discard(pos)
            self._score += self._pts_pacgum
            events.append(GameEvent.PACGUM_EATEN)
        elif pos in self._superpacgums:
            self._superpacgums.discard(pos)
            self._score += self._pts_super
            self._frightened_ticks = _FRIGHTENED_TICKS
            for g in self._ghosts:
                if g.get_state() in (State.CHASE, State.SCATTER):
                    g.change_state(State.FRIGHTENED)
            events.append(GameEvent.SUPER_PACGUM_EATEN)

    def _move_ghosts(self) -> None:
        """Move each ghost via the engine, with per-ghost state injected."""
        player_pos = self._player.get_position()
        player_dir = self._player.get_direction() or (0, 0)
        blinky = self._ghosts[0].get_position()      # Agressor == Blinky
        self._fright_skip = not self._fright_skip
        for ghost, home in zip(self._ghosts, self._homes):
            state_ = ghost.get_state()
            if state_ == State.FRIGHTENED and self._fright_skip:
                continue                             # half speed -> catchable
            if state_ == State.EATEN:
                # Neutralise the strategy's offset so eaten ghosts reach home.
                gs = {"pos": ghost.get_position(), "player_pos": player_pos,
                      "player_dir": (0, 0), "blinky_pos": home}
            else:
                gs = {"pos": ghost.get_position(), "player_pos": player_pos,
                      "player_dir": player_dir, "blinky_pos": blinky}
            ghost.move(gs)

    def _resolve_collisions(self, prev_player: Pos, prev_ghosts: list[Pos],
                            events: list[GameEvent]) -> None:
        """Handle contact (incl. swap-through); eat or die per ghost state."""
        player = self._player.get_position()
        for ghost, prev in zip(self._ghosts, prev_ghosts):
            gp = ghost.get_position()
            if not (gp == player or (gp == prev_player and prev == player)):
                continue
            state = ghost.get_state()
            if state == State.FRIGHTENED:
                ghost.change_state(State.EATEN)
                self._score += self._pts_ghost
                events.append(GameEvent.GHOST_EATEN)
            elif state in (State.CHASE, State.SCATTER):
                if self._cheats.get("invincible") or self._protect_ticks > 0:
                    continue
                self._lose_life(events)
                return

    def _lose_life(self, events: list[GameEvent]) -> None:
        """Lose a life; respawn the player and ghosts, or end the game."""
        self._lives -= 1
        events.append(GameEvent.LIFE_LOST)
        if self._lives <= 0:
            self._lives = 0
            self._game_over = True
            events.append(GameEvent.GAME_OVER)
            return
        spawn = self._nearest_open((self._w // 2, self._h // 2))
        self._player.set_position(*spawn, self._map)
        self._player.set_direction(None)
        self._requested = None
        self._protect_ticks = _SPAWN_PROTECT_TICKS
        self._frightened_ticks = 0
        self._spawn_ghosts()                         # reset ghosts to corners

    def _check_win(self, events: list[GameEvent]) -> None:
        """Emit LEVEL_WON / VICTORY once every pellet is gone."""
        if self._pacgums or self._superpacgums:
            return
        self._level_won = True
        events.append(GameEvent.LEVEL_WON)
        if self._level >= self._level_count - 1:
            self._won_game = True
            self._game_over = True
            events.append(GameEvent.VICTORY)

    # ------------------------------------------------------------------ cheats
    def set_cheat(self, name: str, on: bool) -> None:
        """Toggle ``invincible``/``freeze``/``speed``; unknown ignored."""
        if name in ("invincible", "freeze", "speed"):
            self._cheats[name] = on
            if name == "invincible" and on:
                self._frighten_all()        # invincibility makes ghosts edible

    def skip_level(self) -> None:
        """Cheat: clear all pellets so the next tick wins the level."""
        self._pacgums.clear()
        self._superpacgums.clear()

    def add_life(self) -> None:
        """Cheat: grant one extra life."""
        self._lives += 1
        if self._game_over and self._lives > 0 and not self._won_game:
            self._game_over = False

    # ------------------------------------------------------------------ status
    def is_level_won(self) -> bool:
        """True once all pellets are eaten (cleared by ``start_level``)."""
        return self._level_won

    def is_over(self) -> bool:
        """True once the game has ended (lives out or final level won)."""
        return self._game_over

    @property
    def view(self) -> GameView:
        """A fresh JSON-friendly snapshot for the UI."""
        ghosts: list[GhostView] = [
            {"pos": list(g.get_position()),
             "state": _STATE_NAME.get(g.get_state(), "chase"),
             "color": _STRATEGY_COLOR[strategy]}
            for g, strategy in zip(self._ghosts, _STRATEGIES)
        ]
        return {
            "maze": self._maze,
            "pacgums": [list(p) for p in sorted(self._pacgums)],
            "super_pacgums": [list(p) for p in sorted(self._superpacgums)],
            "player": list(self._player.get_position()),
            "player_dir": self._facing,
            "ghosts": ghosts,
            "score": self._score,
            "lives": self._lives,
            "level": self._level + 1,
            "time_left": max(0, self._time_left),
            "frightened_ticks_left": self._frightened_ticks,
        }

    # --------------------------------------------------------------- helpers
    def _nearest_open(self, target: Pos) -> Pos:
        """Nearest non-solid cell to ``target`` by BFS ring (spawn helper)."""
        from collections import deque
        seen = {target}
        queue: deque[Pos] = deque([target])
        while queue:
            x, y = queue.popleft()
            if self._maze[y][x] != 15:
                return (x, y)
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                nxt = (x + dx, y + dy)
                if (0 <= nxt[0] < self._w and 0 <= nxt[1] < self._h
                        and nxt not in seen):
                    seen.add(nxt)
                    queue.append(nxt)
        return target
