"""The Reflex state: a thin mirror over the engine-backed ``Game``.

``GameState`` owns one game object in a backend field and copies its read-only
``view`` into flat, serialized vars after every tick via :meth:`_sync`. The UI
reads only those vars; it never implements a single game rule.
"""
from __future__ import annotations

import asyncio
import dataclasses
import enum
import os
import signal

import reflex as rx

import highscores
from game.config import runtime_config
from game.contract import GameEvent
from game.game import Game
from pacman_web import style

# Which event scores, and the config key holding its point value.
_EVENT_POINTS: dict[GameEvent, tuple[str, int]] = {
    GameEvent.PACGUM_EATEN: ("points_per_pacgum", 10),
    GameEvent.SUPER_PACGUM_EATEN: ("points_per_super_pacgum", 50),
    GameEvent.GHOST_EATEN: ("points_per_ghost", 200),
}

TICK_MS = 180
READY_MS = 1000
POPUP_TICKS = 2                     # how many ticks a score popup lingers
FRIGHTENED_BLINK_TICKS = 10        # blink ghosts for ending ~2s of frightened
MOVE_TRANSITION = f"left {TICK_MS}ms linear, top {TICK_MS}ms linear"

# Direction name -> rotation for buffered-direction triangle (points up at 0).
_ARROW_ROT = {"up": 0, "right": 90, "down": 180, "left": 270}

# Active config: from $PACMAN_CONFIG (set by pac-man.py) or safe defaults.
CONFIG = runtime_config()
HIGHSCORE_PATH = str(CONFIG.get("highscore_filename", "highscores.json"))

_KEYS = {
    "arrowup": (0, -1), "w": (0, -1),
    "arrowdown": (0, 1), "s": (0, 1),
    "arrowleft": (-1, 0), "a": (-1, 0),
    "arrowright": (1, 0), "d": (1, 0),
}
_ROTATION = {"right": 0, "down": 90, "left": 180, "up": 270}
_VEC_NAME = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}


class Screen(str, enum.Enum):
    """Which top-level screen is showing."""

    MENU = "menu"
    GAME = "game"
    GAME_OVER = "game_over"
    VICTORY = "victory"
    HIGHSCORES = "highscores"
    INSTRUCTIONS = "instructions"
    EXITED = "exited"


def _shutdown_server() -> None:
    """Terminate the whole app process tree (backend, frontend, launcher).

    The app runs as one process group (the ``pac-man.py`` launcher → ``reflex
    run`` → backend/frontend), so a SIGTERM to the group stops everything.
    Falls back to terminating just this process if the group signal is
    unavailable.
    """
    try:
        os.killpg(os.getpgrp(), signal.SIGTERM)
    except (OSError, PermissionError):
        os.kill(os.getpid(), signal.SIGTERM)


@dataclasses.dataclass
class HighRow:
    """One highscore row for display (rank + name + score)."""

    rank: int
    name: str
    score: int


# All overlays carry grid indices (gx, gy); pixel layout is done in CSS from
# the responsive --cell variable, so the board scales without re-syncing.
@dataclasses.dataclass
class WallCell:
    """A static wall cell: grid position, per-side edges, solid flag."""

    gx: int
    gy: int
    solid: bool
    bt: str
    br: str
    bb: str
    bl: str


@dataclasses.dataclass
class Dot:
    """A pellet or super-pellet overlay at a grid cell."""

    gx: int
    gy: int


@dataclasses.dataclass
class Sprite:
    """A ghost overlay: grid position, displayed fill, and state flags."""

    gx: int
    gy: int
    fill: str
    frightened: bool
    eaten: bool
    blinking: bool


@dataclasses.dataclass
class Popup:
    """A floating score popup (e.g. ``+200``) that fades after a moment."""

    key: int
    gx: int
    gy: int
    text: str


class GameState(rx.State):
    """Root state mirroring the game's view for the UI."""

    screen: str = Screen.MENU.value
    score: int = 0
    lives: int = 0
    level: int = 1
    time_left: int = 0
    frightened_ticks_left: int = 0

    walls: list[WallCell] = []
    pellets: list[Dot] = []
    supers: list[Dot] = []
    ghosts: list[Sprite] = []
    player_x: int = 0
    player_y: int = 0
    player_dir: str = "left"
    requested_dir: str = ""
    popups: list[Popup] = []

    board_cols: int = 0
    board_rows: int = 0
    paused: bool = False
    confirm_quit: bool = False
    running: bool = False
    ready: bool = False
    ready_text: str = ""

    cheat_open: bool = False
    cheat_invincible: bool = False
    cheat_freeze: bool = False
    cheat_speed: bool = False
    cheats_used: bool = False

    high_rows: list[HighRow] = []
    awaiting_name: bool = False
    name_input: str = ""
    _scores: list[highscores.Entry] = []
    _last_name: str = ""

    _game: Game | None = None
    _loop_token: int = 0
    _ready_ticks: int = 0
    _popup_seq: int = 0
    _popup_ttls: dict[int, int] = {}

    # -- computed vars
    @rx.var
    def cell_css(self) -> str:
        """The responsive ``--cell`` size for the current maze dimensions."""
        return style.cell_var(self.board_cols, self.board_rows)

    @rx.var
    def board_width(self) -> str:
        """Board width in CSS units (cols × cell)."""
        return f"calc(var(--cell) * {self.board_cols})"

    @rx.var
    def board_height(self) -> str:
        """Board height in CSS units (rows × cell)."""
        return f"calc(var(--cell) * {self.board_rows})"

    @rx.var
    def player_left(self) -> str:
        """CSS x of the player slot (grid column × cell)."""
        return f"calc(var(--cell) * {self.player_x})"

    @rx.var
    def player_top(self) -> str:
        """CSS y of the player slot (grid row × cell)."""
        return f"calc(var(--cell) * {self.player_y})"

    @rx.var
    def player_transform(self) -> str:
        """Rotate the mouth toward the heading."""
        return f"rotate({_ROTATION.get(self.player_dir, 180)}deg)"

    @rx.var
    def show_arrow(self) -> bool:
        """Whether to show the buffered-direction indicator."""
        return self.requested_dir != "" and not self.ready and not self.paused

    @rx.var
    def arrow_transform(self) -> str:
        """
        Rotate the buffered-direction triangle toward the requested heading.
        """
        return f"rotate({_ARROW_ROT.get(self.requested_dir, 0)}deg)"

    @rx.var
    def frightened(self) -> bool:
        """Whether ghosts are currently edible (drives the HUD meter)."""
        return self.frightened_ticks_left > 0

    @rx.var
    def time_low(self) -> bool:
        """Whether the level timer is in its warning zone."""
        return 0 < self.time_left <= 10

    @rx.var
    def life_icons(self) -> list[int]:
        """One entry per remaining life, for rendering pac icons."""
        return list(range(self.lives))

    @rx.var
    def name_valid(self) -> bool:
        """Whether the typed highscore name is acceptable."""
        return highscores.valid_name(self.name_input)

    @rx.var
    def name_remaining(self) -> int:
        """Characters left for the highscore name."""
        return highscores.MAX_NAME - len(self.name_input)

    @rx.var
    def has_scores(self) -> bool:
        """Whether any highscores exist (for empty-state handling)."""
        return len(self.high_rows) > 0

    # -- highscores / navigation
    @rx.event
    def load_scores(self) -> None:
        """Load the highscore file into state (runs on page load)."""
        self._scores = highscores.load(HIGHSCORE_PATH)
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        """Mirror the backend score list into display rows."""
        self.high_rows = [
            HighRow(rank=i + 1, name=e.name, score=e.score)
            for i, e in enumerate(self._scores)
        ]

    @rx.event
    def show_highscores(self) -> None:
        """Open the highscores screen."""
        self.screen = Screen.HIGHSCORES.value

    @rx.event
    def show_instructions(self) -> None:
        """Open the instructions screen."""
        self.screen = Screen.INSTRUCTIONS.value

    @rx.event
    def set_name(self, value: str) -> None:
        """Live-filter the highscore name to allowed characters."""
        self.name_input = highscores.sanitize_name(value)

    @rx.event
    def submit_name(self):
        """Save a qualifying score under entered name, then show the board."""
        if not self.awaiting_name or not highscores.valid_name(
            self.name_input
        ):
            return None
        self._last_name = self.name_input
        self._scores = highscores.add(
            self._scores,
            self.name_input,
            self.score
        )
        highscores.save(HIGHSCORE_PATH, self._scores)
        self._refresh_rows()
        self.awaiting_name = False
        self.screen = Screen.HIGHSCORES.value
        return None

    @rx.event
    def name_key(self, key: str):
        """Enter submits the name; Escape abandons to the menu."""
        k = key.lower()
        if k == "enter":
            return GameState.submit_name
        if k == "escape":
            return GameState.to_menu
        return None

    @rx.event(background=True)
    async def exit_game(self):
        """Shut the whole app down: show a goodbye screen, then stop server."""
        async with self:
            self.running = False
            self.screen = Screen.EXITED.value
        await asyncio.sleep(0.4)        # let the goodbye screen reach
        _shutdown_server()

    # -- lifecycle
    @rx.event
    def new_game(self):
        """Start a fresh game on level 1 and run the tick loop."""
        self._game = Game(CONFIG)
        self.popups = []
        self._popup_ttls = {}
        self.requested_dir = ""
        self.confirm_quit = False
        self.cheat_open = False
        self.cheat_invincible = False
        self.cheat_freeze = False
        self.cheat_speed = False
        self.cheats_used = False
        self._build_walls()
        self._sync()
        self.screen = Screen.GAME.value
        self.paused = False
        self._begin_ready("READY!")
        self.running = True
        self._loop_token += 1
        return GameState.run_loop

    @rx.event
    def to_menu(self) -> None:
        """Abort the current game and return to the menu (no highscore)."""
        self.running = False
        self.paused = False
        self.confirm_quit = False
        self.screen = Screen.MENU.value

    @rx.event
    def ask_quit(self) -> None:
        """Show the 'quit to menu?' confirmation over the pause overlay."""
        self.confirm_quit = True

    @rx.event
    def cancel_quit(self):
        """Dismiss the quit confirmation, staying paused."""
        self.confirm_quit = False
        return GameState.refocus

    @rx.event
    def toggle_pause(self):
        """Pause or resume; only meaningful on the game screen."""
        if self.screen == Screen.GAME.value and not self.ready:
            self.paused = not self.paused
            if not self.paused:
                return GameState.refocus
        return None

    @rx.event
    def refocus(self):
        """Return focus to the board's key catcher after a dialog/panel."""
        return rx.call_script(
            "document.getElementById('keycatcher')?.focus()")

    # -- cheats
    @rx.event
    def toggle_cheats(self):
        """Open/close the cheat panel."""
        self.cheat_open = not self.cheat_open
        if not self.cheat_open:
            return GameState.refocus
        return None

    @rx.event
    def set_invincible(self, value: bool) -> None:
        """Toggle the invincibility cheat."""
        self.cheat_invincible = value
        self._apply_cheat("invincible", value)

    @rx.event
    def set_freeze(self, value: bool) -> None:
        """Toggle the ghost-freeze cheat."""
        self.cheat_freeze = value
        self._apply_cheat("freeze", value)

    @rx.event
    def set_speed(self, value: bool) -> None:
        """Toggle the speed-boost cheat."""
        self.cheat_speed = value
        self._apply_cheat("speed", value)

    @rx.event
    def cheat_skip_level(self) -> None:
        """Instantly clear the current level."""
        if self._game is not None:
            self._game.skip_level()
            self.cheats_used = True

    @rx.event
    def cheat_add_life(self) -> None:
        """Grant one extra life."""
        if self._game is not None:
            self._game.add_life()
            self._sync()
            self.cheats_used = True

    def _apply_cheat(self, name: str, value: bool) -> None:
        """Forward a cheat flag to the game and flag the run as cheated."""
        if self._game is not None:
            self._game.set_cheat(name, value)
        self.cheats_used = True

    @rx.event(background=True)
    async def run_loop(self):
        """Server-side clock: advance the game one tick at a time."""
        async with self:
            token = self._loop_token
        while True:
            async with self:
                if not self.running or token != self._loop_token:
                    return
                if not self.paused:
                    self._step()
                    if not self.running:
                        return
            await asyncio.sleep(TICK_MS / 1000)

    # -- input
    def on_key(self, key: str):
        """Route a keypress by screen (menu start, pause, movement)."""
        k = key.lower()
        if self.screen == Screen.MENU.value:
            if k in (" ", "enter"):
                return GameState.new_game
            return None
        if self.screen in (Screen.GAME_OVER.value, Screen.VICTORY.value):
            if k in (" ", "enter", "escape"):
                self.screen = Screen.MENU.value
            return None
        if self.screen in (Screen.HIGHSCORES.value, Screen.INSTRUCTIONS.value):
            if k in (" ", "enter", "escape"):
                self.screen = Screen.MENU.value
            return None
        # game screen
        if self.confirm_quit:
            return None              # confirmation dialog is click-driven
        if k == "c":
            return GameState.toggle_cheats
        if k in ("escape", "p", " "):
            return GameState.toggle_pause
        move = _KEYS.get(k)
        if move is not None and self._game is not None \
                and not self.paused and not self.ready and not self.cheat_open:
            self._game.request_direction(*move)
            self.requested_dir = _VEC_NAME[move]
        return None

    # -- internals
    def _begin_ready(self, text: str) -> None:
        """Show the READY/LEVEL interstitial for ``READY_MS``."""
        self.ready = True
        self.ready_text = text
        self._ready_ticks = max(1, READY_MS // TICK_MS)

    def _step(self) -> None:
        """One loop iteration: hold during READY, else tick + sync + events."""
        if self._game is None:
            return
        if self._ready_ticks > 0:
            self._ready_ticks -= 1
            if self._ready_ticks == 0:
                self.ready = False
            return
        events = self._game.tick()
        self._sync()
        self._expire_popups()
        self._spawn_popups(events)
        self._handle_events(events)

    def _expire_popups(self) -> None:
        """Age out score popups whose lifetime has elapsed."""
        if not self._popup_ttls:
            return
        for k in list(self._popup_ttls):
            self._popup_ttls[k] -= 1
            if self._popup_ttls[k] <= 0:
                del self._popup_ttls[k]
        self.popups = [p for p in self.popups if p.key in self._popup_ttls]

    def _spawn_popups(self, events: list[GameEvent]) -> None:
        """Add a floating ``+N`` popup at the player for each scoring event."""
        for ev in events:
            spec = _EVENT_POINTS.get(ev)
            if spec is None:
                continue
            key, default = spec
            pts = CONFIG.get(key, default)
            self._popup_seq += 1
            self._popup_ttls[self._popup_seq] = POPUP_TICKS
            self.popups = self.popups + [Popup(
                key=self._popup_seq,
                gx=self.player_x,
                gy=self.player_y,
                text=f"+{pts}",
            )]

    def _handle_events(self, events: list[GameEvent]) -> None:
        """React to terminal/level events from the last tick."""
        if GameEvent.VICTORY in events:
            self.screen = Screen.VICTORY.value
            self.running = False
            self._end_game()
        elif GameEvent.GAME_OVER in events:
            self.screen = Screen.GAME_OVER.value
            self.running = False
            self._end_game()
        elif GameEvent.LEVEL_WON in events and self._game is not None:
            self._game.start_level(self.level)   # 1-based level == next index
            self._build_walls()
            self._sync()
            self._begin_ready(f"LEVEL {self.level}")

    def _end_game(self) -> None:
        """On game end, decide whether to prompt for a highscore name."""
        self.awaiting_name = highscores.qualifies(self._scores, self.score)
        self.name_input = self._last_name if self.awaiting_name else ""

    def _build_walls(self) -> None:
        """Rebuild the static wall layer from the current maze."""
        assert self._game is not None
        maze = self._game.view["maze"]
        self.board_cols = len(maze[0])
        self.board_rows = len(maze)
        cells: list[WallCell] = []
        for y, row in enumerate(maze):
            for x, v in enumerate(row):
                cells.append(WallCell(
                    gx=x, gy=y, solid=v == 15,
                    bt=style.WALL_EDGE if v & 1 else style.NO_EDGE,
                    br=style.WALL_EDGE if v & 2 else style.NO_EDGE,
                    bb=style.WALL_EDGE if v & 4 else style.NO_EDGE,
                    bl=style.WALL_EDGE if v & 8 else style.NO_EDGE,
                ))
        self.walls = cells

    def _sync(self) -> None:
        """Copy the game's view into the mirrored, serialized vars."""
        assert self._game is not None
        v = self._game.view
        self.score = v["score"]
        self.lives = v["lives"]
        self.level = v["level"]
        self.time_left = v["time_left"]
        self.frightened_ticks_left = v["frightened_ticks_left"]
        self.player_x, self.player_y = v["player"]
        self.player_dir = v["player_dir"]
        self.pellets = [Dot(gx=x, gy=y) for x, y in v["pacgums"]]
        self.supers = [Dot(gx=x, gy=y) for x, y in v["super_pacgums"]]
        ending = 0 < self.frightened_ticks_left <= FRIGHTENED_BLINK_TICKS
        self.ghosts = [
            Sprite(
                gx=g["pos"][0],
                gy=g["pos"][1],
                fill=style.GHOST_COLORS.get(g["color"], style.UI_TEXT),
                frightened=g["state"] == "frightened",
                eaten=g["state"] == "eaten",
                blinking=g["state"] == "frightened" and ending,
            )
            for g in v["ghosts"]
        ]
