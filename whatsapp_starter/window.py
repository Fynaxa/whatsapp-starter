"""The 24 hour customer service window.

WhatsApp allows free-form messages only within 24 hours of the customer's last
inbound message. Outside that window, only an approved template may open the
conversation again. Meta enforces this server side with error 131047, so the
rule belongs in the code path, not only in the documentation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

WINDOW = timedelta(hours=24)


class SendMode(str, Enum):
    FREEFORM = "freeform"
    TEMPLATE = "template"


def ensure_utc(moment: datetime) -> datetime:
    """Reject naive datetimes. A window that silently uses local time is a bug."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone aware; use datetime.now(timezone.utc)")
    return moment.astimezone(timezone.utc)


def closes_at(last_inbound: datetime) -> datetime:
    """The exact instant the window shuts."""
    return ensure_utc(last_inbound) + WINDOW


def is_open(last_inbound: datetime | None, now: datetime) -> bool:
    """Open strictly before the boundary. At exactly 24 hours it is closed."""
    if last_inbound is None:
        return False
    return ensure_utc(now) < closes_at(last_inbound)


def required_mode(last_inbound: datetime | None, now: datetime) -> SendMode:
    return SendMode.FREEFORM if is_open(last_inbound, now) else SendMode.TEMPLATE


@dataclass(slots=True)
class WindowTracker:
    """Remembers the last inbound message per contact, persisted as JSON.

    A single file is enough for one phone number and a few thousand contacts.
    Swap this class for Redis or Postgres when several workers share the state.
    """

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def record_inbound(self, wa_id: str, moment: datetime) -> None:
        """Only ever move the boundary forward; webhooks can arrive out of order."""
        state = self._read()
        moment = ensure_utc(moment)
        previous = state.get(wa_id)
        if previous and datetime.fromisoformat(previous) >= moment:
            return
        state[wa_id] = moment.isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=0, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def last_inbound(self, wa_id: str) -> datetime | None:
        value = self._read().get(wa_id)
        return datetime.fromisoformat(value) if value else None

    def is_open(self, wa_id: str, now: datetime | None = None) -> bool:
        return is_open(self.last_inbound(wa_id), now or datetime.now(timezone.utc))
