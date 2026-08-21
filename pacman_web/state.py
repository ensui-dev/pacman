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
from typing import TYPE_CHECKING, cast

import reflex as rx

if TYPE_CHECKING:
    # mypy resolves these from the stubs; chained-handler returns type as
    # EventNamespace there.
    from reflex.event import EventNamespace, EventSpec
else:
    # Reflex resolves handler annotations at runtime when transforming each
    # event payload (get_type_hints), so both names must really exist here.
    # The lazy loader can't import EventNamespace by name, but ``rx.event``
    # *is* the EventNamespace class at runtime.
    from reflex.event import EventSpec
    EventNamespace = rx.event

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
START_MS = 2200                    # first READY holds under the start jingle
DEATH_MS = 1500                    # board freezes under the death spiral
POPUP_TICKS = 2                     # how many ticks a score popup lingers
FRIGHTENED_BLINK_TICKS = 10        # blink ghosts for ending ~2s of frightened

# Sound set: "/sfx" (arcade originals, keep out of public builds) or
# "/sfx_generated" (our own set from tools/generate_sfx.py). One knob.
SFX_DIR = "/sfx"

# Game events that fire a one-shot sound (pacgums get the waka treatment
# separately so the two chomp samples can alternate).
_EVENT_SOUNDS: dict[GameEvent, str] = {
    GameEvent.SUPER_PACGUM_EATEN: "eat_fruit",
    GameEvent.GHOST_EATEN: "eat_ghost",
    GameEvent.LIFE_LOST: "death_0",
    GameEvent.VICTORY: "intermission",
}


def _ambient_name(playing: bool, any_eaten: bool, frightened: bool,
                  pellets_left: int, pellets_total: int) -> str:
    """Pick the single background loop for the current situation.

    Priority: eyes > fright > siren tier (escalating as pellets deplete,
    like the arcade) > silence ("" when not actively playing).
    """
    if not playing:
        return ""
    if any_eaten:
        return "eyes"
    if frightened:
        return "fright"
    if pellets_total <= 0:
        return "siren0"
    eaten_frac = 1 - pellets_left / pellets_total
    tier = min(4, int(eaten_frac * 5))
    return f"siren{tier}"


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


def _walls_svg(maze: list[list[int]]) -> str:
    """Render the whole wall layer as one SVG string (a single DOM node).

    Coordinates are in cell units (``viewBox`` = cols×rows); the stroke is
    kept at ``WALL_PX`` device pixels via ``non-scaling-stroke`` so the look
    matches the old per-cell borders at any board size. Built once per level,
    large mazes would otherwise mean thousands of wall divs in the DOM.
    """
    rows, cols = len(maze), len(maze[0])
    blocks: list[str] = []
    edges: list[str] = []
    for y, row in enumerate(maze):
        for x, v in enumerate(row):
            if v == 15:
                blocks.append(f"M{x} {y}h1v1h-1z")
            if v & 1:
                edges.append(f"M{x} {y}h1")
            if v & 2:
                edges.append(f"M{x + 1} {y}v1")
            if v & 4:
                edges.append(f"M{x} {y + 1}h1")
            if v & 8:
                edges.append(f"M{x} {y}v1")
    return (
        f'<svg viewBox="0 0 {cols} {rows}" width="100%" height="100%" '
        f'preserveAspectRatio="none" style="display:block">'
        f'<path d="{"".join(blocks)}" fill="{style.BLOCK_FILL}"/>'
        f'<path d="{"".join(edges)}" fill="none" stroke="{style.MAZE_WALL}" '
        f'stroke-width="{style.WALL_PX}" vector-effect="non-scaling-stroke" '
        f'stroke-linecap="square"/></svg>'
    )


def _pellets_svg(pellets: list[list[int]], cols: int, rows: int) -> str:
    """Render all pacgum dots as one SVG string (a single DOM node).

    Rebuilt only on ticks where the pellet count changed; swapping one
    string is far cheaper (server, wire and React) than re-diffing one
    component per pellet every tick on large mazes. Each dot is a
    near-zero-length path segment rendered as a disc by the round line
    cap, one ``<path>`` for the whole layer keeps the string a third
    the size of per-``<circle>`` markup.
    """
    dots = "".join(f"M{x}.5 {y}.5h.01" for x, y in pellets)
    return (
        f'<svg viewBox="0 0 {cols} {rows}" width="100%" height="100%" '
        f'preserveAspectRatio="none" style="display:block">'
        f'<path d="{dots}" fill="none" stroke="{style.PELLET}" '
        f'stroke-width="0.18" stroke-linecap="round"/></svg>'
    )


# Overlays carry grid indices (gx, gy); pixel layout is done in CSS from
# the responsive --cell variable, so the board scales without re-syncing.
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

    walls_svg: str = ""
    pellets_svg: str = ""
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

    # -- sound channels (see components.audio): a URL change (seq bump)
    # makes the player reload and autoplay; ambient is a steady loop var.
    muted: bool = False
    ambient: str = ""
    shot_file: str = ""
    shot_seq: int = 0
    chomp_file: str = ""
    chomp_seq: int = 0

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
    # Counts mirrored last sync; -1 forces a rebuild of the derived layer.
    _pellet_count: int = -1
    _super_count: int = -1
    _pellet_total: int = 0
    _chomp_flip: bool = False

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
    def ambient_src(self) -> str:
        """URL of the active background loop file."""
        return f"{SFX_DIR}/{self.ambient}.wav" if self.ambient else ""

    @rx.var
    def shot_src(self) -> str:
        """URL of the last one-shot; the seq makes repeats re-play."""
        if not self.shot_file:
            return ""
        return f"{SFX_DIR}/{self.shot_file}.wav?n={self.shot_seq}"

    @rx.var
    def chomp_src(self) -> str:
        """URL of the alternating dot-chomp channel."""
        if not self.chomp_file:
            return ""
        return f"{SFX_DIR}/{self.chomp_file}.wav?n={self.chomp_seq}"

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
    def submit_name(self) -> None:
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
    def name_key(self, key: str) -> EventNamespace | None:
        """Enter submits the name; Escape abandons to the menu."""
        k = key.lower()
        if k == "enter":
            return GameState.submit_name
        if k == "escape":
            return GameState.to_menu
        return None

    # The stubs type `rx.event` calls without kwargs; runtime accepts them.
    @rx.event(background=True)  # type: ignore[operator]
    async def exit_game(self) -> None:
        """Shut the whole app down: show a goodbye screen, then stop server."""
        async with self:
            self.running = False
            self.screen = Screen.EXITED.value
        await asyncio.sleep(0.4)        # let the goodbye screen reach
        _shutdown_server()

    # -- lifecycle
    @rx.event
    def new_game(self) -> EventNamespace:
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
        self._begin_ready("READY!", START_MS)
        self._play("start")
        self.ambient = ""
        self.running = True
        self._loop_token += 1
        # run_loop is Any to mypy (its decorator call is type-ignored above)
        return cast("EventNamespace", GameState.run_loop)

    @rx.event
    def to_menu(self) -> None:
        """Abort the current game and return to the menu (no highscore)."""
        self.running = False
        self.paused = False
        self.confirm_quit = False
        self.screen = Screen.MENU.value
        self.ambient = ""

    @rx.event
    def ask_quit(self) -> None:
        """Show the 'quit to menu?' confirmation over the pause overlay."""
        self.confirm_quit = True

    @rx.event
    def cancel_quit(self) -> EventNamespace:
        """Dismiss the quit confirmation, staying paused."""
        self.confirm_quit = False
        return GameState.refocus

    @rx.event
    def toggle_pause(self) -> EventNamespace | None:
        """Pause or resume; only meaningful on the game screen."""
        if self.screen == Screen.GAME.value and not self.ready:
            self.paused = not self.paused
            self._update_ambient()
            if not self.paused:
                return GameState.refocus
        return None

    @rx.event
    def refocus(self) -> EventSpec:
        """Return focus to the board's key catcher after a dialog/panel."""
        return rx.call_script(
            "document.getElementById('keycatcher')?.focus()")

    # -- cheats
    @rx.event
    def toggle_cheats(self) -> EventNamespace | None:
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
        """Grant one extra life (with the classic extra-life jingle)."""
        if self._game is not None:
            self._game.add_life()
            self._sync()
            self.cheats_used = True
            self._play("extend")

    @rx.event
    def toggle_mute(self) -> None:
        """Flip sound on/off (the audio channels read the flag live)."""
        self.muted = not self.muted
        # clear transient channels so unmuting can't replay a stale shot
        self.shot_file = ""
        self.chomp_file = ""

    def _apply_cheat(self, name: str, value: bool) -> None:
        """Forward a cheat flag to the game and flag the run as cheated."""
        if self._game is not None:
            self._game.set_cheat(name, value)
        self.cheats_used = True

    # The stubs type `rx.event` calls without kwargs; runtime accepts them.
    @rx.event(background=True)  # type: ignore[operator]
    async def run_loop(self) -> None:
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
    @rx.event
    def on_key(self, key: str) -> EventNamespace | None:
        """Route a keypress by screen (menu start, pause, movement)."""
        k = key.lower()
        if k == "m" and not self.awaiting_name:
            return GameState.toggle_mute
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
    def _begin_ready(self, text: str, hold_ms: int = READY_MS) -> None:
        """Freeze the board under an interstitial for ``hold_ms``."""
        self.ready = True
        self.ready_text = text
        self._ready_ticks = max(1, hold_ms // TICK_MS)

    def _play(self, name: str) -> None:
        """Fire a one-shot sound on the event channel."""
        self.shot_file = name
        self.shot_seq += 1

    def _chomp(self) -> None:
        """Fire the dot chomp, alternating the two samples (the waka)."""
        self._chomp_flip = not self._chomp_flip
        self.chomp_file = f"eat_dot_{int(self._chomp_flip)}"
        self.chomp_seq += 1

    def _update_ambient(self) -> None:
        """Re-derive the background loop; assigns only on change."""
        playing = (self.running and not self.paused and not self.ready
                   and self.screen == Screen.GAME.value)
        name = _ambient_name(
            playing,
            any(g.eaten for g in self.ghosts),
            self.frightened_ticks_left > 0,
            self._pellet_count,
            self._pellet_total,
        )
        if name != self.ambient:
            self.ambient = name

    def _step(self) -> None:
        """One loop iteration: hold during READY, else tick + sync + events."""
        if self._game is None:
            return
        if self._ready_ticks > 0:
            self._ready_ticks -= 1
            if self._ready_ticks == 0:
                self.ready = False
                self._update_ambient()
            return
        events = self._game.tick()
        self._sync()
        self._expire_popups()
        self._spawn_popups(events)
        self._handle_events(events)
        for ev in events:
            if ev == GameEvent.PACGUM_EATEN:
                self._chomp()
            elif ev in _EVENT_SOUNDS:
                self._play(_EVENT_SOUNDS[ev])
        if (GameEvent.LIFE_LOST in events
                and GameEvent.GAME_OVER not in events):
            # classic death pause: dim + freeze under the death spiral
            self._begin_ready("", DEATH_MS)
        self._update_ambient()

    def _expire_popups(self) -> None:
        """Age out score popups whose lifetime has elapsed."""
        if not self._popup_ttls:
            return
        for k in list(self._popup_ttls):
            self._popup_ttls[k] -= 1
            if self._popup_ttls[k] <= 0:
                del self._popup_ttls[k]
        remaining = [p for p in self.popups if p.key in self._popup_ttls]
        if len(remaining) != len(self.popups):
            self.popups = remaining

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
        """Rebuild the static wall SVG and board dims from the current maze."""
        assert self._game is not None
        maze = self._game.view["maze"]
        self.board_cols = len(maze[0])
        self.board_rows = len(maze)
        self.walls_svg = _walls_svg(maze)
        self._pellet_count = -1     # force pellet/super layer rebuilds
        self._super_count = -1

    def _sync(self) -> None:
        """Mirror the game's view into the serialized vars, changes only.

        Reflex marks a var dirty on *assignment* (it never compares values),
        and every dirty var is resent in full over the websocket each tick.
        So each mirror below is guarded: unchanged values are not assigned,
        and the pellet layer is rebuilt only when the count moved (within a
        level pellets only ever shrink). This is what keeps large maps from
        lagging, without the guards every tick reships the whole board.
        """
        assert self._game is not None
        v = self._game.view
        if self.score != v["score"]:
            self.score = v["score"]
        if self.lives != v["lives"]:
            self.lives = v["lives"]
        if self.level != v["level"]:
            self.level = v["level"]
        if self.time_left != v["time_left"]:
            self.time_left = v["time_left"]
        if self.frightened_ticks_left != v["frightened_ticks_left"]:
            self.frightened_ticks_left = v["frightened_ticks_left"]
        px, py = v["player"]
        if self.player_x != px:
            self.player_x = px
        if self.player_y != py:
            self.player_y = py
        if self.player_dir != v["player_dir"]:
            self.player_dir = v["player_dir"]

        if len(v["pacgums"]) != self._pellet_count:
            if self._pellet_count == -1:       # level start: capture total
                self._pellet_total = len(v["pacgums"])
            self._pellet_count = len(v["pacgums"])
            self.pellets_svg = _pellets_svg(
                v["pacgums"], self.board_cols, self.board_rows)
        if len(v["super_pacgums"]) != self._super_count:
            self._super_count = len(v["super_pacgums"])
            self.supers = [Dot(gx=x, gy=y) for x, y in v["super_pacgums"]]

        # Ghosts move nearly every tick; 4 sprites are a tiny payload, so
        # resending them beats comparing proxied dataclass lists.
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
