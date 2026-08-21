"""The HUD bar: score, lives, level, and the level timer."""
from __future__ import annotations

import reflex as rx

from pacman_web import style
from pacman_web.components import as_component
from pacman_web.state import GameState


def _chip(label: str, value: rx.Component, min_w: str = "7ch") -> rx.Component:
    """A labelled HUD cell with a fixed min width so values never reflow."""
    return as_component(rx.vstack(
        rx.text(label, font_size="0.6rem", color=style.UI_DIM,
                letter_spacing="0.1em"),
        value,
        spacing="1",
        align="start",
        min_width=min_w,
    ))


def _life_icon(_: int) -> rx.Component:
    """A small pac icon representing one life."""
    return as_component(rx.box(
        class_name="life-pop",
        width="16px", height="16px",
        background=(
            f"conic-gradient(from 65deg, rgba(0,0,0,0) 0 50deg, "
            f"{style.PAC_YELLOW} 50deg 360deg)"
        ),
        border_radius="9999px",
    ))


def _mute_button() -> rx.Component:
    """Small sound toggle (mouse parity for the 'm' key)."""
    return as_component(rx.el.button(
        rx.cond(GameState.muted, "MUTED", "SOUND"),
        on_click=GameState.toggle_mute,
        title="Toggle sound (m)",
        font_family=style.FONT_DISPLAY,
        font_size="0.55rem",
        color=rx.cond(GameState.muted, style.UI_DIM, style.PAC_YELLOW),
        background="transparent",
        border=f"1px solid {style.UI_DIM}",
        padding="6px 8px",
        cursor="pointer",
    ))


def hud_bar() -> rx.Component:
    """Score / lives / level / time, plus the frightened meter."""
    big = {"font_family": style.FONT_DISPLAY, "font_size": "1rem",
           "color": style.UI_TEXT}
    return as_component(rx.vstack(
        rx.hstack(
            _chip("SCORE", rx.text(GameState.score, **big), min_w="9ch"),
            _chip(
                "LIVES",
                rx.hstack(rx.foreach(GameState.life_icons, _life_icon),
                          spacing="1", min_height="16px"),
                min_w="7ch",
            ),
            _chip("LEVEL", rx.text(GameState.level, **big), min_w="6ch"),
            _chip(
                "TIME",
                rx.text(
                    GameState.time_left,
                    font_family=style.FONT_DISPLAY,
                    font_size="1rem",
                    color=rx.cond(GameState.time_low, style.DANGER,
                                  style.UI_TEXT),
                ),
                min_w="6ch",
            ),
            _mute_button(),
            justify="between",
            width="100%",
            align="end",
        ),
        rx.box(
            width="100%",
            height="4px",
            background_color=style.FRIGHTENED,
            opacity=rx.cond(GameState.frightened, "1", "0"),
            transition="opacity 150ms linear",
        ),
        spacing="2",
        width="100%",
        padding="8px 12px",
        border_bottom=f"2px solid {style.MAZE_WALL}",
    ))
