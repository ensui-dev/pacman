"""Theme tokens and reusable styles

Python-side mirror of the CSS variables in ``assets/theme.css`` so entity
colors and sizes computed in Python stay in sync with the stylesheet.
Geometry is fixed for now;
"""
from __future__ import annotations

# -- Board geometry
# Cell size is responsive: a CSS var --cell, clamped between these bounds and
# fitted to the viewport per maze size. Entities are sized as a % of the cell.
CELL_MIN_PX = 14
CELL_MAX_PX = 42
WALL_PX = 2
PELLET_PCT = "18%"
SUPER_PCT = "42%"
SPRITE_PCT = "82%"


def cell_var(cols: object, rows: object) -> str:
    """CSS ``clamp`` for the cell size given maze ``cols``×``rows``.

    Fits the board into ~70vh tall / ~92vw wide (so wide and tall mazes both
    fit), never smaller than 14px nor larger than 42px.
    """
    return (f"clamp({CELL_MIN_PX}px, "
            f"min(calc(70vh / {rows}), calc(92vw / {cols})), "
            f"{CELL_MAX_PX}px)")


# -- Palette (mirror of assets/theme.css :root)
BG_ROOM = "#0a0a12"
BG_SCREEN = "#04040a"
MAZE_WALL = "#2330d8"
MAZE_WALL_GLOW = "#4250ff"
BLOCK_FILL = "#1b2470"
PAC_YELLOW = "#ffdf00"
PELLET = "#ffe9b3"
FRIGHTENED = "#2b43ff"
FRIGHTENED_END = "#f4f4ff"
UI_TEXT = "#e8e8f0"
UI_DIM = "#8a8aa0"
DANGER = "#ff3b30"

GHOST_COLORS = {
    "red": "#ff3b30",     # Agressor
    "pink": "#ff9ad5",    # Ambusher
    "cyan": "#29e6e6",    # Unpredictable
    "orange": "#ffb24d",  # Wanderer
}

# -- Fonts (self-hosted .woff2 is a later task; fall back to monospace)
FONT_DISPLAY = "'Press Start 2P', 'Courier New', monospace"
FONT_BODY = "'VT323', 'Courier New', monospace"

# -- Wall edge strings
WALL_EDGE = f"{WALL_PX}px solid {MAZE_WALL}"
NO_EDGE = f"{WALL_PX}px solid transparent"   # keeps cell box size stable

# -- Reusable style dicts
BUTTON_STYLE: dict[str, str] = {
    "font_family": FONT_DISPLAY,
    "font_size": "0.8rem",
    "color": PAC_YELLOW,
    "background": "transparent",
    "border": f"2px solid {PAC_YELLOW}",
    "padding": "12px 24px",
    "text_transform": "uppercase",
    "letter_spacing": "0.1em",
    "cursor": "pointer",
}

PANEL_STYLE: dict[str, str] = {
    "background": "rgba(0,0,0,0.72)",
    "border": f"2px solid {MAZE_WALL}",
    "padding": "32px",
    "box_shadow": "0 0 24px rgba(66,80,255,0.25)",
}
