"""Structured event schema emitted to the configured ``EventSink``.

All events are JSON-serializable dicts. A light wrapper function guarantees a
stable schema (``type``, ``ts``, ``session_id``, ``payload``) so downstream
consumers (Lambda, Kinesis, DynamoDB) can filter by type without introspection.
"""

from __future__ import annotations

import time
import uuid
from typing import Any


def make_session_id() -> str:
    return str(uuid.uuid4())


def event(type_: str, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": type_,
        "ts": time.time(),
        "session_id": session_id,
        "payload": payload,
    }


# Well-known event types. Centralize strings here so both the game loop and
# downstream consumers can import the same constants.

ROUND_START = "round.start"
ROUND_END = "round.end"

SCAN_OK = "scan.ok"
SCAN_ERROR = "scan.error"

HAND_DEALT = "hand.dealt"
HAND_ACTION = "hand.action"
HAND_RESULT = "hand.result"

DEALER_ACTION = "dealer.action"
DEALER_RESULT = "dealer.result"

RECOMMENDATION = "recommendation"

SHOE_RESHUFFLE = "shoe.reshuffle"
