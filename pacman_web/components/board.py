"""The maze board: static SVG layers + the per-tick entity overlay.

Everything is positioned on a CSS grid driven by the ``--cell`` custom property
(set on the game screen, inherited here), so the board scales to the viewport
without re-syncing. Walls and pellets are each a single server-built SVG
(one DOM node apiece, walls rebuilt per level, pellets only on eating ticks);
sprites are absolutely-positioned overlays. Player and ghosts glide via a CSS
transition tied to the tick rate, so a delayed update becomes a catch-up
glide, not snap.
"""
from __future__ import annotations

import reflex as rx

from pacman_web import style
from pacman_web.components import as_component
from pacman_web.state import (
    Dot,
    GameState,
    MOVE_TRANSITION,
    Popup,
    Sprite,
)

# Pac-Man mouth: a transparent wedge cut from a yellow disc, pointing right;
# GameState.player_transform rotates it toward the heading.
_PLAYER_BG = (
    f"conic-gradient(from 65deg at 50% 50%, "
    f"rgba(0,0,0,0) 0deg 50deg, {style.PAC_YELLOW} 50deg 360deg)"
)


def _at(gx: int, gy: int, *children: rx.Component,
        **props: object) -> rx.Component:
    """
    A cell-sized slot positioned at grid (gx, gy), centering its children.
    """
    return as_component(rx.box(
        *children,
        position="absolute",
        left=f"calc(var(--cell) * {gx})",
        top=f"calc(var(--cell) * {gy})",
        width="var(--cell)",
        height="var(--cell)",
        display="flex",
        align_items="center",
        justify_content="center",
        **props,
    ))


def _static_layer(svg: str) -> rx.Component:
    """A board-filling layer rendering one server-built SVG string.

    One DOM node regardless of maze size, the whole point of the SVG
    layers; see ``state._walls_svg`` / ``state._pellets_svg``.
    """
    return as_component(rx.html(
        svg,
        position="absolute",
        inset="0",
        width="100%",
        height="100%",
        pointer_events="none",
    ))


def _super(dot: Dot) -> rx.Component:
    """A pulsing super-pacgum."""
    return _at(
        dot.gx, dot.gy,
        rx.box(class_name="super-pulse", width=style.SUPER_PCT,
               height=style.SUPER_PCT, background_color=style.PELLET,
               border_radius="9999px",
               box_shadow=f"0 0 8px {style.PELLET}"),
    )


def _eye() -> rx.Component:
    """A single white ghost eye (sized off the cell so it never collapses)."""
    return as_component(rx.box(
        width="calc(var(--cell) * 0.18)",
        height="calc(var(--cell) * 0.18)",
        background_color="#fff",
        border_radius="9999px",
    ))


def _eyes() -> rx.Component:
    """The white eyes, on every ghost, the only thing left when eaten."""
    return as_component(rx.hstack(
        _eye(), _eye(),
        spacing="1",
        justify="center",
        width="100%",
        position="absolute",
        top="22%",
    ))


def _ghost(sprite: Sprite) -> rx.Component:
    """A ghost: colored/blue domed body with eyes; just eyes when eaten."""
    body = rx.cond(
        sprite.eaten,
        "transparent",
        rx.cond(sprite.frightened, style.FRIGHTENED, sprite.fill),
    )
    return _at(
        sprite.gx, sprite.gy,
        rx.box(
            _eyes(),
            class_name=rx.cond(sprite.blinking, "frightened-blink", ""),
            width=style.SPRITE_PCT,
            height=style.SPRITE_PCT,
            background_color=body,
            border_radius="50% 50% 0 0",
            position="relative",
        ),
        transition=MOVE_TRANSITION,
        z_index="9",
    )


def _player() -> rx.Component:
    """The single player overlay (yellow disc with a directional mouth)."""
    return as_component(rx.box(
        rx.box(
            width=style.SPRITE_PCT,
            height=style.SPRITE_PCT,
            background=_PLAYER_BG,
            border_radius="9999px",
            transform=GameState.player_transform,
            filter=f"drop-shadow(0 0 4px {style.PAC_YELLOW})",
        ),
        position="absolute",
        left=GameState.player_left,
        top=GameState.player_top,
        width="var(--cell)",
        height="var(--cell)",
        display="flex",
        align_items="center",
        justify_content="center",
        transition=MOVE_TRANSITION,
        z_index="10",
    ))


def _arrow() -> rx.Component:
    """A small triangle showing the buffered turn (the 'feels-native' cue)."""
    triangle = rx.box(
        width="0",
        height="0",
        border_left="5px solid transparent",
        border_right="5px solid transparent",
        border_bottom=f"8px solid {style.PAC_YELLOW}",
        position="absolute",
        top="-9px",
        left="50%",
        transform="translateX(-50%)",
        filter=f"drop-shadow(0 0 3px {style.PAC_YELLOW})",
    )
    return as_component(rx.cond(
        GameState.show_arrow,
        rx.box(
            rx.box(triangle, width="100%", height="100%", position="relative",
                   transform=GameState.arrow_transform),
            position="absolute",
            left=GameState.player_left,
            top=GameState.player_top,
            width="var(--cell)",
            height="var(--cell)",
            transition=MOVE_TRANSITION,
            pointer_events="none",
            z_index="11",
        ),
    ))


def _popup(popup: Popup) -> rx.Component:
    """A floating ``+N`` score popup that drifts up and fades."""
    return _at(
        popup.gx, popup.gy,
        rx.text(popup.text, class_name="score-pop", color=style.PAC_YELLOW,
                font_family=style.FONT_DISPLAY,
                font_size="clamp(0.5rem, calc(var(--cell) * 0.45), 0.9rem)",
                white_space="nowrap"),
        pointer_events="none",
        z_index="12",
    )


def _focus_catcher() -> rx.Component:
    """Transparent input that captures keystrokes for the board."""
    return as_component(rx.el.input(
        id="keycatcher",
        on_key_down=GameState.on_key,
        auto_focus=True,
        position="absolute",
        top="0",
        left="0",
        width="100%",
        height="100%",
        opacity="0",
        cursor="pointer",
        # Above the board entities (so clicking the board focuses it) but BELOW
        # the ready/pause overlays, otherwise this invisible input eats their
        # clicks and Resume/Main-menu stop working.
        z_index="15",
        style={"caretColor": "transparent"},
    ))


def maze_board() -> rx.Component:
    """Assemble the board: walls, pellets, sprites, player, key catcher."""
    return as_component(rx.box(
        _static_layer(GameState.walls_svg),
        _static_layer(GameState.pellets_svg),
        rx.foreach(GameState.supers, _super),
        rx.foreach(GameState.ghosts, _ghost),
        _player(),
        _arrow(),
        rx.foreach(GameState.popups, _popup),
        _focus_catcher(),
        position="relative",
        width=GameState.board_width,
        height=GameState.board_height,
        background_color=style.BG_SCREEN,
        border="4px solid #1b1b2e",
        border_radius="12px",
        box_shadow="inset 0 0 40px rgba(0,0,0,.8)",
    ))
