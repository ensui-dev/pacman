"""Cheat panel: a slide-in side panel of labelled toggles and buttons.

Cheats only ease evaluation; they wire straight to the Game's cheat hooks.
Using any cheat flags the run via ``GameState.cheats_used``, surfaced as a
persistent "CHEATS ACTIVE" tag so the defense stays honest.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import reflex as rx

from pacman_web import style
from pacman_web.components import as_component
from pacman_web.state import GameState

if TYPE_CHECKING:
    from reflex.event import EventNamespace

_SECONDARY_BUTTON: dict[str, str] = {
    "font_family": style.FONT_DISPLAY,
    "font_size": "0.65rem",
    "color": style.PAC_YELLOW,
    "background": "transparent",
    "border": f"2px solid {style.PAC_YELLOW}",
    "padding": "8px 12px",
    "text_transform": "uppercase",
    "cursor": "pointer",
}


def _toggle(label: str, desc: str, checked: bool,
            on_change: EventNamespace) -> rx.Component:
    """One labelled cheat toggle row."""
    return as_component(rx.hstack(
        rx.vstack(
            rx.text(label, color=style.UI_TEXT, font_family=style.FONT_BODY,
                    font_size="1.1rem"),
            rx.text(desc, color=style.UI_DIM, font_size="0.78rem"),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.switch(checked=checked, on_change=on_change),
        width="100%",
        align="center",
    ))


def cheat_button() -> rx.Component:
    """The discoverable button that opens the panel (mouse parity for 'c')."""
    return as_component(rx.el.button(
        "Cheats (c)", on_click=GameState.toggle_cheats,
        style=_SECONDARY_BUTTON))


def cheats_tag() -> rx.Component:
    """Persistent 'CHEATS ACTIVE' marker once any cheat is used."""
    return as_component(rx.cond(
        GameState.cheats_used,
        rx.box(
            rx.text("CHEATS ACTIVE", font_family=style.FONT_DISPLAY,
                    font_size="0.5rem", color=style.DANGER),
            border=f"1px solid {style.DANGER}",
            padding="2px 6px",
        ),
    ))


def cheat_panel() -> rx.Component:
    """The slide-in cheat panel (always mounted; slides off-screen)."""
    return as_component(rx.box(
        rx.vstack(
            rx.hstack(
                rx.heading("CHEATS", font_family=style.FONT_DISPLAY,
                           font_size="1rem", color=style.PAC_YELLOW),
                rx.spacer(),
                rx.el.button("✕", on_click=GameState.toggle_cheats,
                             style={
                                    "color": style.UI_TEXT,
                                    "cursor": "pointer",
                                    "background": "transparent",
                                    "fontSize": "1.2rem"}),
                width="100%",
                align="center",
            ),
            _toggle("Invincibility", "No life loss",
                    GameState.cheat_invincible, GameState.set_invincible),
            _toggle("Ghost freeze", "Ghosts stop moving",
                    GameState.cheat_freeze, GameState.set_freeze),
            _toggle("Speed boost", "Move two cells per tick",
                    GameState.cheat_speed, GameState.set_speed),
            rx.divider(margin_y="8px"),
            rx.el.button("Skip level", on_click=GameState.cheat_skip_level,
                         style=_SECONDARY_BUTTON),
            rx.el.button("+1 life", on_click=GameState.cheat_add_life,
                         style=_SECONDARY_BUTTON),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        position="fixed",
        top="0",
        right="0",
        height="100vh",
        width="min(92vw, 340px)",
        padding="24px",
        background="rgba(4,4,10,0.96)",
        border_left=f"2px solid {style.MAZE_WALL}",
        box_shadow="0 0 40px rgba(0,0,0,.7)",
        transform=rx.cond(GameState.cheat_open, "translateX(0)",
                          "translateX(110%)"),
        transition="transform 200ms ease-out",
        pointer_events=rx.cond(GameState.cheat_open, "auto", "none"),
        z_index="40",
    ))
