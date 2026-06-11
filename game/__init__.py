"""Game orchestration layer

Exposes the API contract and the ``FakeGame`` stub the UI builds against until
the real ``Game`` is done.
"""
from game.contract import (
    GameEvent,
    GameProtocol,
    GameView,
    GhostState,
    GhostView,
)
from game.fake import FakeGame

__all__ = [
    "GameEvent",
    "GameProtocol",
    "GameView",
    "GhostState",
    "GhostView",
    "FakeGame",
]
