"""``Game`` API contract - Connects UI with game logic.

This module is the single source of truth for the interface the Reflex UI talks
to. The UI depends only on :class:`GameProtocol`; :class:`~game.fake.FakeGame`
for consistent development, will alter to the real ``Game`` once finished.
Note: Swapping one for the other must require no UI change.
"""
from __future__ import annotations

import enum
from typing import Protocol, TypedDict, runtime_checkable


class GameEvent(enum.Enum):
    """Discrete things that happened during one :meth:`GameProtocol.tick`.

    Returned in occurrence order so the UI can react (sound, score pop, screen
    switch) without ever re-deriving game rules itself.
    """

    PACGUM_EATEN = "pacgum_eaten"
    SUPER_PACGUM_EATEN = "super_pacgum_eaten"
    GHOST_EATEN = "ghost_eaten"
    LIFE_LOST = "life_lost"
    LEVEL_WON = "level_won"
    VICTORY = "victory"          # last level cleared
    GAME_OVER = "game_over"      # lives exhausted


class GhostState(enum.Enum):
    """Per-ghost behaviour/render state exposed in the view."""

    CHASE = "chase"
    FRIGHTENED = "frightened"
    EATEN = "eaten"             # defeated; returning home as eyes


class GhostView(TypedDict):
    """JSON-friendly snapshot of one ghost for the entity overlay."""

    pos: list[int]             # [x, y]
    state: str                 # a GhostState value
    color: str                 # palette token: red | pink | cyan | orange


class GameView(TypedDict):
    """Read-only, JSON-friendly snapshot the UI mirrors after every tick.

    All positions are ``[x, y]``. ``maze`` holds wall bitmasks
    (N=1, E=2, S=4, W=8; ``15`` = solid block) and changes only on level start;
    every other field may change per tick. Designed to mirror the UI's state
    vars one-to-one so copying it out each tick stays trivial.
    """

    maze: list[list[int]]
    pacgums: list[list[int]]
    super_pacgums: list[list[int]]
    player: list[int]
    player_dir: str            # up | down | left | right
    ghosts: list[GhostView]
    score: int
    lives: int
    level: int                 # 1-based, for the HUD
    time_left: int             # whole seconds
    frightened_ticks_left: int


@runtime_checkable
class GameProtocol(Protocol):
    """The Game API. ``FakeGame`` and the real ``Game`` both conform to it.

    The UI calls exactly these members and reads :attr:`view` — nothing else.
    Implementations stay free of any UI import: game logic never depends on the
    presentation layer.
    """

    def tick(self) -> list[GameEvent]:
        """Advance the simulation a step; return events in occurrence order."""
        ...

    def request_direction(self, dx: int, dy: int) -> None:
        """Buffer a desired heading, applied at the next tick where is legal"""
        ...

    def start_level(self, index: int) -> None:
        """(Re)initialise maze and entities for level ``index`` (0-based)."""
        ...

    @property
    def view(self) -> GameView:
        """Current read-only snapshot for the UI."""
        ...

    def set_cheat(self, name: str, on: bool) -> None:
        """Toggle a cheat flag (``invincible`` | ``freeze`` | ``speed``)."""
        ...

    def skip_level(self) -> None:
        """Cheat: instantly clear the current level."""
        ...

    def add_life(self) -> None:
        """Cheat: grant one extra life."""
        ...

    def is_level_won(self) -> bool:
        """True once all pacgums and super-pacgums have been eaten."""
        ...

    def is_over(self) -> bool:
        """True once the game has ended (lives exhausted or final level won)"""
        ...
