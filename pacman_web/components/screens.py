"""Top-level screens: menu, game (with overlays), game-over, victory.

The menu and end screens are intentionally minimal here, the full menu,
highscores and name entry land in a later phase. This phase focuses on the
game screen playing end-to-end against the stub.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import reflex as rx

from pacman_web import style
from pacman_web.components import as_component
from pacman_web.components.board import maze_board
from pacman_web.components.cheats import cheat_button, cheat_panel, cheats_tag
from pacman_web.components.hud import hud_bar
from pacman_web.state import CONFIG, GameState, HighRow

if TYPE_CHECKING:
    from reflex.event import EventNamespace


def _arcade_button(label: str, on_click: EventNamespace,
                   full: bool = False) -> rx.Component:
    """A primary arcade-style button (``full`` stretches to its container)."""
    btn_style = dict(style.BUTTON_STYLE)
    if full:
        btn_style["width"] = "100%"
    return as_component(
        rx.el.button(label, on_click=on_click, style=btn_style))


def _high_row(row: HighRow) -> rx.Component:
    """One rank/name/score row in a highscore table."""
    return as_component(rx.hstack(
        rx.text(row.rank, color=style.UI_DIM, width="3ch"),
        rx.text(row.name, color=style.UI_TEXT, flex="1",
                font_family=style.FONT_BODY),
        rx.text(row.score, color=style.PAC_YELLOW, width="9ch",
                text_align="right"),
        width="100%",
    ))


def _high_table() -> rx.Component:
    """The top-10 list, or a friendly empty state."""
    return as_component(rx.cond(
        GameState.has_scores,
        rx.vstack(rx.foreach(GameState.high_rows, _high_row),
                  width="100%", spacing="1"),
        rx.text("No scores yet, be the first!", color=style.UI_DIM,
                font_family=style.FONT_BODY),
    ))


def _info_line(label: str, value: str) -> rx.Component:
    """A label/value row for the instructions panel."""
    return as_component(rx.hstack(
        rx.text(label, color=style.UI_DIM, font_family=style.FONT_BODY,
                flex="1"),
        rx.text(value, color=style.UI_TEXT, font_family=style.FONT_BODY),
        width="100%",
    ))


def _key_catcher() -> rx.Component:
    """Auto-focused, click-through input so menus/end screens receive keys.

    The game screen has its own catcher inside the board; this one keeps SPACE/
    ENTER/ESC working on every other screen.
    """
    return as_component(rx.el.input(
        on_key_down=GameState.on_key,
        auto_focus=True,
        position="fixed",
        inset="0",
        width="100%",
        height="100%",
        opacity="0",
        border="none",
        pointer_events="none",       # never blocks button clicks
        style={"caretColor": "transparent"},
    ))


def _title(text: str, color: str = style.PAC_YELLOW) -> rx.Component:
    return as_component(rx.heading(
        text,
        font_family=style.FONT_DISPLAY,
        font_size="clamp(1.1rem, 3.2vw, 1.9rem)",
        color=color,
        text_shadow=f"0 0 12px {color}99",
        letter_spacing="0.05em",
        word_spacing="-0.5em",       # Press Start 2P's space is full-width
        text_align="center",
        white_space="nowrap",
        width="100%",
    ))


def _ready_banner() -> rx.Component:
    """READY!/LEVEL over the board."""
    return as_component(rx.cond(
        GameState.ready,
        rx.box(
            _title(GameState.ready_text),
            position="absolute",
            inset="0",
            display="flex",
            align_items="center",
            justify_content="center",
            background="rgba(0,0,0,0.45)",
            z_index="20",
        ),
    ))


def _pause_overlay() -> rx.Component:
    """Dim layer + panel shown while paused."""
    return as_component(rx.cond(
        GameState.paused,
        rx.box(
            rx.vstack(
                _title("PAUSED"),
                _arcade_button("Resume", GameState.toggle_pause, full=True),
                _arcade_button("Main menu", GameState.ask_quit, full=True),
                spacing="4",
                align="center",
                style=style.PANEL_STYLE,
                width="260px",
            ),
            position="absolute",
            inset="0",
            display="flex",
            align_items="center",
            justify_content="center",
            background="rgba(0,0,0,0.6)",
            z_index="25",
        ),
    ))


def _confirm_quit() -> rx.Component:
    """Confirmation before abandoning a game to the menu (progress is lost)."""
    return as_component(rx.cond(
        GameState.confirm_quit,
        rx.box(
            rx.vstack(
                _title("QUIT?"),
                rx.text("Progress will be lost.", color=style.UI_DIM,
                        font_family=style.FONT_BODY, font_size="1.1rem"),
                rx.hstack(
                    _arcade_button("Quit", GameState.to_menu),
                    _arcade_button("Cancel", GameState.cancel_quit),
                    spacing="3",
                ),
                spacing="4",
                align="center",
                style=style.PANEL_STYLE,
            ),
            position="absolute",
            inset="0",
            display="flex",
            align_items="center",
            justify_content="center",
            background="rgba(0,0,0,0.78)",
            z_index="28",
        ),
    ))


def menu_screen() -> rx.Component:
    """Main menu: title, actions, and the top scores."""
    return as_component(rx.center(
        rx.vstack(
            _title("PAC-MAN"),
            rx.text("Ghosts! More ghosts!", color=style.UI_DIM,
                    font_family=style.FONT_BODY, font_size="1.25rem"),
            rx.vstack(
                _arcade_button("Start game", GameState.new_game, full=True),
                _arcade_button("Highscores", GameState.show_highscores,
                               full=True),
                _arcade_button("Instructions", GameState.show_instructions,
                               full=True),
                _arcade_button("Exit", GameState.exit_game, full=True),
                spacing="3",
                width="260px",
            ),
            rx.box(
                rx.text("TOP SCORES", color=style.UI_DIM,
                        font_family=style.FONT_DISPLAY, font_size="0.6rem",
                        margin_bottom="12px"),
                _high_table(),
                style=style.PANEL_STYLE,
                width="320px",
            ),
            rx.text("Push SPACE to play", color=style.UI_DIM,
                    font_family=style.FONT_BODY),
            spacing="5",
            align="center",
        ),
        _key_catcher(),
        min_height="85vh",
        padding_y="32px",
    ))


def game_screen() -> rx.Component:
    """HUD + board with the ready/pause overlays and the cheat panel."""
    return as_component(rx.center(
        rx.vstack(
            rx.hstack(
                hud_bar(),
                cheats_tag(),
                width="100%",
                align="center",
                spacing="3",
            ),
            rx.box(
                maze_board(),
                _ready_banner(),
                _pause_overlay(),
                _confirm_quit(),
                position="relative",
            ),
            rx.hstack(
                rx.text("⟵⟶ move · SPACE/ESC pause", color=style.UI_DIM,
                        font_family=style.FONT_BODY),
                rx.spacer(),
                cheat_button(),
                width="100%",
                align="center",
            ),
            spacing="4",
            align="center",
            width="100%",
            max_width=GameState.board_width,
            style={"--cell": GameState.cell_css},
        ),
        cheat_panel(),
        min_height="85vh",
    ))


def _name_entry() -> rx.Component:
    """Highscore name input: live-filtered, 10-char cap, Enter to save."""
    return as_component(rx.vstack(
        rx.text("NEW HIGHSCORE!", color=style.PAC_YELLOW,
                font_family=style.FONT_DISPLAY, font_size="0.75rem"),
        rx.el.input(
            value=GameState.name_input,
            on_change=GameState.set_name,
            on_key_down=GameState.name_key,
            auto_focus=True,
            max_length=10,
            placeholder="YOUR NAME",
            style={
                "fontFamily": style.FONT_DISPLAY,
                "fontSize": "0.9rem",
                "color": style.PAC_YELLOW,
                "background": "transparent",
                "border": f"2px solid {style.MAZE_WALL}",
                "padding": "10px 12px",
                "textAlign": "center",
                "textTransform": "uppercase",
                "width": "100%",
            },
        ),
        rx.text(GameState.name_remaining, " characters left",
                color=style.UI_DIM, font_size="0.7rem"),
        _arcade_button("Save", GameState.submit_name, full=True),
        spacing="3",
        align="center",
        width="100%",
    ))


def _end_screen(title: str, color: str) -> rx.Component:
    """Shared game-over / victory layout (with highscore name entry)."""
    return as_component(rx.center(
        rx.vstack(
            _title(title, color),
            rx.text("SCORE", color=style.UI_DIM, font_family=style.FONT_BODY),
            rx.text(GameState.score, font_family=style.FONT_DISPLAY,
                    font_size="2rem", color=style.PAC_YELLOW),
            rx.cond(
                GameState.awaiting_name,
                _name_entry(),
                rx.fragment(
                    _arcade_button("Main menu", GameState.to_menu, full=True),
                    _key_catcher(),
                ),
            ),
            spacing="4",
            align="center",
            style=style.PANEL_STYLE,
            width="360px",
        ),
        min_height="85vh",
    ))


def highscores_screen() -> rx.Component:
    """The full top-10 table."""
    return as_component(rx.center(
        rx.vstack(
            _title("HIGHSCORES"),
            rx.box(_high_table(), style=style.PANEL_STYLE, width="380px"),
            _arcade_button("Back", GameState.to_menu, full=True),
            _key_catcher(),
            spacing="5",
            align="center",
            width="380px",
        ),
        min_height="85vh",
    ))


def instructions_screen() -> rx.Component:
    """Controls, scoring and rules, values read live from the config."""
    cfg = CONFIG
    return as_component(rx.center(
        rx.vstack(
            _title("INSTRUCTIONS"),
            rx.box(
                rx.vstack(
                    _info_line("Move", "Arrow keys / WASD"),
                    _info_line("Pause", "SPACE or ESC"),
                    _info_line("Cheats", "C"),
                    rx.divider(margin_y="8px"),
                    _info_line("Pacgum", f"{cfg['points_per_pacgum']} pts"),
                    _info_line("Super pacgum",
                               f"{cfg['points_per_super_pacgum']} pts"),
                    _info_line("Eat ghost", f"{cfg['points_per_ghost']} pts"),
                    _info_line("Lives", f"{cfg['lives']}"),
                    _info_line("Time / level", f"{cfg['level_max_time']} s"),
                    spacing="2",
                    width="100%",
                ),
                style=style.PANEL_STYLE,
                width="420px",
            ),
            _arcade_button("Back", GameState.to_menu, full=True),
            _key_catcher(),
            spacing="5",
            align="center",
            width="420px",
        ),
        min_height="85vh",
    ))


def game_over_screen() -> rx.Component:
    """Shown when lives run out."""
    return _end_screen("GAME OVER", style.DANGER)


def victory_screen() -> rx.Component:
    """Shown when the final level is cleared."""
    return _end_screen("VICTORY!", style.PAC_YELLOW)


def exited_screen() -> rx.Component:
    """Final screen after Exit shuts the server down."""
    return as_component(rx.center(
        rx.vstack(
            _title("GOODBYE"),
            rx.text("The game has shut down. You can close this tab.",
                    color=style.UI_DIM, font_family=style.FONT_BODY,
                    font_size="1.1rem", text_align="center"),
            spacing="5",
            align="center",
        ),
        min_height="85vh",
    ))
