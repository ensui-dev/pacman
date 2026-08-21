"""``FakeGame`` - UI stub

Implements :class:`game.contract.GameProtocol` with a small, deterministic,
canned world so the Reflex UI can be built and exercised before the real
``Game`` exists. It is intentionally simple: an open map with one central
block (a stand-in for the generator's "42" pattern), four corner ghosts,
super-pacgums in the corners, and greedy ghost chasing. The real maze,
AI, and rules replace it later with no UI change
(both conform to the same protocol).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from game.contract import GameEvent, GameView, GhostState, GhostView

# Wall bits, matching the generator encoding (N=1, E=2, S=4, W=8).
_WALL_N, _WALL_E, _WALL_S, _WALL_W = 1, 2, 4, 8
_SOLID = 15
# (dx, dy) for each side, paired with the bit blocking movement that way.
_STEPS: tuple[tuple[int, int, int], ...] = (
    (0, -1, _WALL_N),
    (1, 0, _WALL_E),
    (0, 1, _WALL_S),
    (-1, 0, _WALL_W),
)
_DIR_NAME = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}

_WIDTH, _HEIGHT = 9, 7
_CENTER_BLOCK = (4, 3)                       # the lone solid "42" stand-in
_GHOST_COLORS = ("red", "pink", "cyan", "orange")
_TICKS_PER_SECOND = 5                        # matches the UI tick loop
_FRIGHTENED_TICKS = 6 * _TICKS_PER_SECOND    # ~6s of edible ghosts
_SPAWN_PROTECT_TICKS = 2 * _TICKS_PER_SECOND  # brief respawn invulnerability

Pos = tuple[int, int]


@dataclass
class _Ghost:
    """Mutable internal ghost record; the view exposes a JSON dict instead."""

    pos: Pos
    home: Pos
    color: str
    state: GhostState
    last: Pos = (0, 0)      # last step taken (no reversing while fleeing)


def _to_int(config: dict[str, object], key: str, default: int,
            lo: int, hi: int) -> int:
    """Read ``key`` as an int, clamped to ``[lo, hi]``, never trusts config.

    Bools and out-of-range or wrong-type values fall back to ``default`` rather
    than corrupting the game (the config is editable and may be hostile).
    """
    val = config.get(key, default)
    if isinstance(val, bool) or not isinstance(val, int):
        return default
    return max(lo, min(hi, val))


def _level_count(config: dict[str, object]) -> int:
    """Best-effort number of levels from the config; at least 1."""
    levels = config.get("levels")
    if isinstance(levels, list) and levels:
        return len(levels)
    return 10


class FakeGame:
    """A deterministic, self-contained implementation of ``GameProtocol``."""

    def __init__(self, config: dict[str, object]) -> None:
        """Read scoring/lives/timer from ``config`` (defensively) and begin."""
        self._pts_pacgum = _to_int(config, "points_per_pacgum", 10, 0, 10_000)
        self._pts_super = _to_int(
            config,
            "points_per_super_pacgum",
            50,
            0,
            10_000
        )
        self._pts_ghost = _to_int(config, "points_per_ghost", 200, 0, 10_000)
        self._max_time = _to_int(config, "level_max_time", 90, 1, 3_600)
        self._start_lives = _to_int(config, "lives", 3, 1, 99)
        self._level_count = _level_count(config)
        # classic_pacgums: read defensively (default off). The stub fills the
        # arena either way; the flag is recorded so the real Game/Map can honor
        # it (fill every corridor like arcade Pac-Man instead of a percentage).
        self._classic_pacgums = config.get("classic_pacgums") is True

        self._maze: list[list[int]] = _build_maze()
        self._score = 0
        self._lives = self._start_lives
        self._game_over = False
        self._won_game = False
        self._cheats: dict[str, bool] = {}
        self._rng = random.Random(20240611)   # deterministic wander
        self.start_level(0)

    # -- setup
    def start_level(self, index: int) -> None:
        """
        (Re)initialise entities and pellets for level ``index``
        (0-based).
        """
        self._level = index
        self._level_won = False
        self._frightened_ticks = 0
        self._protect_ticks = 0
        self._tick_in_second = 0
        self._time_left = self._max_time
        self._requested: Optional[Pos] = None
        self._player_dir: Pos = (-1, 0)

        corners: list[Pos] = [(0, 0), (_WIDTH - 1, 0), (0, _HEIGHT - 1),
                              (_WIDTH - 1, _HEIGHT - 1)]
        self._super_pacgums: set[Pos] = set(corners)
        self._pacgums: set[Pos] = {
            (x, y)
            for y in range(_HEIGHT) for x in range(_WIDTH)
            if (x, y) != _CENTER_BLOCK and (x, y) not in self._super_pacgums
        }
        self._player: Pos = self._nearest_open((_WIDTH // 2, _HEIGHT // 2))
        self._pacgums.discard(self._player)
        self._ghosts: list[_Ghost] = [
            _Ghost(pos=home, home=home, color=color, state=GhostState.CHASE)
            for home, color in zip(corners, _GHOST_COLORS)
        ]

    # -- input
    def request_direction(self, dx: int, dy: int) -> None:
        """Buffer a heading; applied next tick it is legal (classic feel)."""
        if (dx, dy) in _DIR_NAME:
            self._requested = (dx, dy)

    # -- step
    def tick(self) -> list[GameEvent]:
        """Advance one step and return the events that occurred, in order."""
        if self._game_over or self._level_won:
            return []
        events: list[GameEvent] = []

        self._advance_timers(events)
        if self._game_over:
            return events

        prev_player = self._player
        self._move_player(events)
        prev_ghosts = [g.pos for g in self._ghosts]
        if not self.cheats_frozen:
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
                    if g.state == GhostState.FRIGHTENED:
                        g.state = GhostState.CHASE
        if self._protect_ticks > 0:
            self._protect_ticks -= 1

        self._tick_in_second += 1
        if self._tick_in_second >= _TICKS_PER_SECOND:
            self._tick_in_second = 0
            self._time_left -= 1
            if self._time_left <= 0:
                # Running out of time costs a life and restarts the timer.
                self._lose_life(events)
                self._time_left = self._max_time

    def _move_player(self, events: list[GameEvent]) -> None:
        """Move the player one cell, honoring the buffered turn, then eat."""
        if self._requested and self._can_move(self._player, self._requested):
            self._player_dir = self._requested
            self._requested = None
        steps = 2 if self.cheats_speed else 1
        for _ in range(steps):
            if self._can_move(self._player, self._player_dir):
                self._player = _add(self._player, self._player_dir)
                self._eat(events)

    def _eat(self, events: list[GameEvent]) -> None:
        """Consume any pellet under the player and score it."""
        if self._player in self._pacgums:
            self._pacgums.discard(self._player)
            self._score += self._pts_pacgum
            events.append(GameEvent.PACGUM_EATEN)
        elif self._player in self._super_pacgums:
            self._super_pacgums.discard(self._player)
            self._score += self._pts_super
            self._frightened_ticks = _FRIGHTENED_TICKS
            for g in self._ghosts:
                if g.state == GhostState.CHASE:
                    g.state = GhostState.FRIGHTENED
            events.append(GameEvent.SUPER_PACGUM_EATEN)

    def _chase_target(self, g: _Ghost) -> Pos:
        """A distinct target per ghost so they don't all share one path.

        A loose echo of the four arcade personalities (the real engine owns the
        authoritative versions); here it mainly keeps the four ghosts visually
        separated on the open arena instead of stacking on one cell.
        """
        px, py = self._player
        dx, dy = self._player_dir
        if g.color == "red":            # Agressor: straight at the player
            return (px, py)
        if g.color == "pink":           # Ambusher: a few cells ahead
            return (px + 2 * dx, py + 2 * dy)
        if g.color == "cyan":           # Unpredictable: ahead, mirrored
            return (px - 2 * dx, py - 2 * dy)
        # orange (Wanderer): chase from afar, scatter home when close
        if abs(px - g.pos[0]) + abs(py - g.pos[1]) <= 4:
            return g.home
        return (px, py)

    def _move_ghosts(self) -> None:
        """Greedy one-cell step per ghost;
        flee when frightened, home when eaten."""
        for g in self._ghosts:
            if g.state == GhostState.EATEN:
                if g.pos == g.home:
                    g.state = GhostState.CHASE
                    continue
                g.pos = self._greedy_step(g.pos, g.home, flee=False)
            elif g.state == GhostState.FRIGHTENED:
                # Wander randomly while edible: keeps the four moving and
                # apart, unlike a shared flee target (they'd merge) or a
                # fixed corner (pile-up). Close to arcade frightened motion.
                g.pos = self._wander_step(g)
            else:
                g.pos = self._greedy_step(
                    g.pos, self._chase_target(g), flee=False)

    def _resolve_collisions(self, prev_player: Pos, prev_ghosts: list[Pos],
                            events: list[GameEvent]) -> None:
        """Handle player/ghost contact,
        including swapping cells in one tick."""
        for g, prev in zip(self._ghosts, prev_ghosts):
            same_cell = g.pos == self._player
            swapped = g.pos == prev_player and prev == self._player
            if not (same_cell or swapped):
                continue
            if g.state == GhostState.FRIGHTENED:
                g.state = GhostState.EATEN
                self._score += self._pts_ghost
                events.append(GameEvent.GHOST_EATEN)
            elif g.state == GhostState.CHASE:
                if self.cheats_invincible or self._protect_ticks > 0:
                    continue
                self._lose_life(events)
                return  # positions reset; stop checking this tick

    def _lose_life(self, events: list[GameEvent]) -> None:
        """Lose one life; respawn or end the game."""
        self._lives -= 1
        events.append(GameEvent.LIFE_LOST)
        if self._lives <= 0:
            self._lives = 0
            self._game_over = True
            events.append(GameEvent.GAME_OVER)
            return
        self._player = self._nearest_open((_WIDTH // 2, _HEIGHT // 2))
        self._player_dir = (-1, 0)
        self._requested = None
        self._protect_ticks = _SPAWN_PROTECT_TICKS
        for g in self._ghosts:
            g.pos = g.home
            if g.state != GhostState.EATEN:
                g.state = GhostState.CHASE
        self._frightened_ticks = 0

    def _check_win(self, events: list[GameEvent]) -> None:
        """Emit LEVEL_WON / VICTORY once every pellet is gone."""
        if self._pacgums or self._super_pacgums:
            return
        self._level_won = True
        events.append(GameEvent.LEVEL_WON)
        if self._level >= self._level_count - 1:
            self._won_game = True
            self._game_over = True
            events.append(GameEvent.VICTORY)

    # -- cheats
    def set_cheat(self, name: str, on: bool) -> None:
        """
        Toggle ``invincible`` | ``freeze`` | ``speed``;
        unknown names ignored.
        """
        if name in ("invincible", "freeze", "speed"):
            self._cheats[name] = on

    @property
    def cheats_invincible(self) -> bool:
        """Whether life loss is disabled."""
        return self._cheats.get("invincible", False)

    @property
    def cheats_frozen(self) -> bool:
        """Whether ghosts are frozen in place."""
        return self._cheats.get("freeze", False)

    @property
    def cheats_speed(self) -> bool:
        """Whether the player moves two cells per tick."""
        return self._cheats.get("speed", False)

    def skip_level(self) -> None:
        """Cheat: clear all pellets so the next tick wins the level."""
        self._pacgums.clear()
        self._super_pacgums.clear()

    def add_life(self) -> None:
        """Cheat: grant one extra life."""
        self._lives += 1
        if self._game_over and self._lives > 0:
            self._game_over = False

    # -- status
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
            {"pos": list(g.pos), "state": g.state.value, "color": g.color}
            for g in self._ghosts
        ]
        return {
            "maze": self._maze,
            "pacgums": [list(p) for p in sorted(self._pacgums)],
            "super_pacgums": [list(p) for p in sorted(self._super_pacgums)],
            "player": list(self._player),
            "player_dir": _DIR_NAME[self._player_dir],
            "ghosts": ghosts,
            "score": self._score,
            "lives": self._lives,
            "level": self._level + 1,
            "time_left": max(0, self._time_left),
            "frightened_ticks_left": self._frightened_ticks,
        }

    # -- helpers
    def _can_move(self, pos: Pos, step: Pos) -> bool:
        """True if the wall bitmask permits moving ``step`` from ``pos``."""
        bit = next(b for dx, dy, b in _STEPS if (dx, dy) == step)
        x, y = pos
        return (self._maze[y][x] & bit) == 0

    def _greedy_step(self, pos: Pos, target: Pos, flee: bool) -> Pos:
        """Step toward (or away from) ``target`` among legal neighbors."""
        best, best_score = pos, None
        for dx, dy, bit in _STEPS:
            x, y = pos
            if self._maze[y][x] & bit:
                continue
            nxt = (x + dx, y + dy)
            dist = abs(nxt[0] - target[0]) + abs(nxt[1] - target[1])
            score = -dist if flee else dist
            if best_score is None or score < best_score:
                best, best_score = nxt, score
        return best

    def _wander_step(self, g: _Ghost) -> Pos:
        """Pick a random legal neighbor, preferring not to reverse."""
        x, y = g.pos
        moves = [(dx, dy) for dx, dy, bit in _STEPS
                 if not (self._maze[y][x] & bit)]
        if not moves:
            return g.pos
        reverse = (-g.last[0], -g.last[1])
        forward = [m for m in moves if m != reverse]
        step = self._rng.choice(forward or moves)
        g.last = step
        return (x + step[0], y + step[1])

    def _nearest_open(self, target: Pos) -> Pos:
        """Nearest non-solid cell to ``target`` (BFS ring), used for spawning.

        The arena center is a solid block, so the player can't spawn there;
        this finds the closest walkable cell instead.
        """
        seen = {target}
        queue = [target]
        while queue:
            cur = queue.pop(0)
            cx, cy = cur
            if self._maze[cy][cx] != _SOLID:
                return cur
            for dx, dy, _ in _STEPS:
                nxt = (cx + dx, cy + dy)
                if (0 <= nxt[0] < _WIDTH and 0 <= nxt[1] < _HEIGHT
                        and nxt not in seen):
                    seen.add(nxt)
                    queue.append(nxt)
        return target  # unreachable for our canned maze


def _add(pos: Pos, step: Pos) -> Pos:
    """Vector add a (dx, dy) step to a position."""
    return (pos[0] + step[0], pos[1] + step[1])


def _build_maze() -> list[list[int]]:
    """Build the map: every cell walkable except one central block.

    Walls are computed as *edges*: a side is walled when the neighbor on that
    side is out of bounds or the solid block. This matches the generator's
    encoding exactly, so the UI's border-per-bit renderer is exercised the same
    way it will be by real mazes.
    """
    maze: list[list[int]] = []
    for y in range(_HEIGHT):
        row: list[int] = []
        for x in range(_WIDTH):
            if (x, y) == _CENTER_BLOCK:
                row.append(_SOLID)
                continue
            bits = 0
            for dx, dy, bit in _STEPS:
                nx, ny = x + dx, y + dy
                out = not (0 <= nx < _WIDTH and 0 <= ny < _HEIGHT)
                if out or (nx, ny) == _CENTER_BLOCK:
                    bits |= bit
            row.append(bits)
        maze.append(row)
    return maze
