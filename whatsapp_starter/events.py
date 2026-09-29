"""Parsing of the webhook envelope into flat, typed events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .errors import describe

@dataclass(frozen=True, slots=True)
class InboundMessage:
    id: str
    wa_id: str
    timestamp: datetime
    type: str
    text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return f"message:{self.id}"


@dataclass(frozen=True, slots=True)
class StatusUpdate:
    id: str
    recipient: str
    status: str
    timestamp: datetime
    error_code: int | None = None
    explanation: str | None = None

    @property
    def dedup_key(self) -> str:
        # The same message id reports sent, delivered and read separately.
        return f"status:{self.id}:{self.status}"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


Event = InboundMessage | StatusUpdate


def parse_events(payload: dict[str, Any]) -> list[Event]:
    """Flatten entry/changes/value into messages and status updates."""
    events: list[Event] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            events.extend(_message(item) for item in value.get("messages") or [])
            events.extend(_status(item) for item in value.get("statuses") or [])
    return events


def _message(body: dict[str, Any]) -> InboundMessage:
    return InboundMessage(
        id=body.get("id", ""),
        wa_id=body.get("from", ""),
        timestamp=_epoch(body.get("timestamp")),
        type=body.get("type", "unknown"),
        text=_text_of(body),
        raw=body,
    )


def _text_of(body: dict[str, Any]) -> str | None:
    """Plain text of a message, whatever shape the customer used to send it."""
    interactive = body.get("interactive") or {}
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    return (
        body.get("text", {}).get("body")
        or body.get("button", {}).get("text")
        or reply.get("title")
    )


def _status(body: dict[str, Any]) -> StatusUpdate:
    errors = body.get("errors") or []
    first = errors[0] if errors else {}
    code = first.get("code")
    code = int(code) if isinstance(code, (int, str)) and str(code).isdigit() else None
    return StatusUpdate(
        id=body.get("id", ""),
        recipient=body.get("recipient_id", ""),
        status=body.get("status", "unknown"),
        timestamp=_epoch(body.get("timestamp")),
        error_code=code,
        explanation=describe(code, str(first.get("title", ""))) if errors else None,
    )


def _epoch(value: Any) -> datetime:
    """Meta sends unix seconds as a string. Missing values fall back to now."""
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
