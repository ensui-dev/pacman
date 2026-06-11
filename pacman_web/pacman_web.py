"""Pac-Man on Reflex: app entry and screen router.

The page is a single route that switches between screens via
``GameState.screen``(keeps game state alive across screen changes, avoids URL
edge cases). One CRT glass overlay sits above everything so the whole
app inherits the arcade feel.
"""
from __future__ import annotations

import reflex as rx

from pacman_web import style
from pacman_web.components.screens import (
    exited_screen,
    game_over_screen,
    game_screen,
    highscores_screen,
    instructions_screen,
    menu_screen,
    victory_screen,
)
from pacman_web.state import GameState, Screen


def _crt_glass() -> rx.Component:
    """The single fixed scanline/vignette overlay (pointer-events: none)."""
    return rx.box(class_name="crt-glass")


def _too_small() -> rx.Component:
    """Friendly guard shown (via CSS media query) on a too-small window."""
    return rx.box(
        rx.text("Window too small — please enlarge to play.",
                font_family=style.FONT_BODY, font_size="1.3rem",
                color=style.UI_TEXT, text_align="center"),
        class_name="too-small",
    )


def index() -> rx.Component:
    """Render the active screen inside the cabinet, under the glass."""
    return rx.box(
        rx.match(
            GameState.screen,
            (Screen.GAME.value, game_screen()),
            (Screen.GAME_OVER.value, game_over_screen()),
            (Screen.VICTORY.value, victory_screen()),
            (Screen.HIGHSCORES.value, highscores_screen()),
            (Screen.INSTRUCTIONS.value, instructions_screen()),
            (Screen.EXITED.value, exited_screen()),
            menu_screen(),
        ),
        _crt_glass(),
        _too_small(),
        background_color=style.BG_ROOM,
        min_height="100vh",
        width="100%",
    )


app = rx.App(
    stylesheets=["/theme.css"],
    style={"fontFamily": style.FONT_BODY},
)
app.add_page(index, title="PAC-MAN - 42", on_load=GameState.load_scores)
