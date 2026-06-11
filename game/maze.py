"""Maze loader - calls the mazegenerator.

This loader raises the recursion limit before generating and
catches any failure, turning it into a clean:class:`MazeGenerationError`
instead of letting a traceback escape.
"""
from __future__ import annotations

import sys


class MazeGenerationError(Exception):
    """Raised when a maze could not be generated, with a readable message."""


def build_maze(width: int, height: int, seed: int) -> list[list[int]]:
    """Generate a maze as ``maze[y][x]`` wall bitmasks (N=1, E=2, S=4, W=8).

    ``seed > 0`` is reproducible; ``seed <= 0`` uses system entropy. Walls are
    cell edges; a value of ``15`` marks a solid block. Raises
    :class:`MazeGenerationError` on any underlying failure.
    """
    from mazegenerator import MazeGenerator

    try:
        sys.setrecursionlimit(max(1000, width * height + 100))
        gen = MazeGenerator(size=(width, height), perfect=False, seed=seed)
        # the wheel ships no py.typed, so gen.maze is Any to mypy
        maze: list[list[int]] = gen.maze
    except RecursionError as exc:
        raise MazeGenerationError(
            f"maze {width}x{height} is too large to generate"
        ) from exc
    except Exception as exc:
        raise MazeGenerationError(f"maze generation failed: {exc}") from exc

    if not maze or not maze[0]:
        raise MazeGenerationError("generator returned an empty maze")
    return maze
