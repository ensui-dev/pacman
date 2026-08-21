"""Hidden audio channels: sound as plain state, no custom JavaScript.

Three players driven entirely by ``GameState`` vars:

* **chomp** - the alternating dot-eat samples (the waka): each eaten
  pacgum bumps a sequence number in the URL, remounting a plain HTML
  ``<audio autoPlay>`` that plays **once** and goes silent. No looping,
  the waka rhythm comes from pacgums being eaten in sequence.
* **shot** - every other one-shot (ghost eaten, death, jingles), same
  fire-once element. A separate channel keeps rapid chomping from
  cutting event sounds off.
* **ambient** - the single *deliberately* looping background
  (sirens/fright/eyes) via ``rx.audio`` with ``loop=True``; swaps source
  when ``GameState.ambient`` changes, silent when it is "".

One-shots use raw ``rx.el.audio`` rather than ``rx.audio`` on purpose:
react-player re-syncs ``playing=True`` on every re-render, restarting
ended media each tick (sounds "looping"). A native autoplay element has
exactly the fire-and-forget semantics a one-shot needs. Mute unmounts the
one-shot elements and zeroes the loop volume; ``toggle_mute`` also clears
the transient channels so unmuting doesn't replay a stale sound.
"""
from __future__ import annotations

import reflex as rx

from pacman_web.components import as_component
from pacman_web.state import GameState


def _oneshot(src: rx.Var[str] | str) -> rx.Component:
    """A fire-once channel: plays on mount, never restarts."""
    return as_component(rx.el.audio(src=src, auto_play=True))


def _ambient_loop() -> rx.Component:
    """The looping background channel (volume-muted rather than unmounted
    so the loop position survives a quick mute toggle)."""
    return as_component(rx.audio(
        src=GameState.ambient_src,
        playing=True,
        loop=True,
        volume=rx.cond(GameState.muted, 0.0, 0.35),
        width="0",
        height="0",
    ))


def sfx_channels() -> rx.Component:
    """All sound channels; mounted once at app level (display: none)."""
    return as_component(rx.box(
        rx.cond(
            GameState.muted,
            rx.fragment(),
            rx.fragment(
                rx.cond(GameState.chomp_src != "",
                        _oneshot(GameState.chomp_src)),
                rx.cond(GameState.shot_src != "",
                        _oneshot(GameState.shot_src)),
            ),
        ),
        rx.cond(GameState.ambient_src != "", _ambient_loop()),
        display="none",
    ))
