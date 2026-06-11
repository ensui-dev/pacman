"""Reusable UI components for the Pac-Man app."""
from __future__ import annotations

from typing import cast

import reflex as rx


def as_component(component: object) -> rx.Component:
    """Typed pass-through for Reflex's lazily-loaded factories.

    ``rx.box``/``rx.vstack``/... resolve through Reflex's lazy loader,
    which mypy can only see as ``Any``. Funnelling component returns
    through this cast keeps builder functions honestly annotated under
    ``--warn-return-any`` without sprinkling per-line ignores.
    """
    return cast("rx.Component", component)
