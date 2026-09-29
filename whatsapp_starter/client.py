"""Outbound messaging: window-aware sends, retries, readable failures.

The transport is injected, so the whole retry and window logic is testable
without a network. The default transport is urllib from the standard library;
swap in a requests-based one if the rest of your stack already uses it.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .config import Settings
from .errors import TransportError, WhatsAppError, WindowClosedError
from .window import SendMode, WindowTracker, required_mode

RETRY_AFTER_CAP = 300.0


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def retryable(self) -> bool:
        if self.ok:
            return False
        return WhatsAppError.from_payload(self.status, self.body).retryable


class Transport(Protocol):
    def post_json(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> Response: ...


@dataclass(frozen=True, slots=True)
class UrllibTransport:
    timeout: float = 15.0

    def post_json(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> Response:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as raw:
                return Response(raw.status, dict(raw.headers), _decode(raw.read()))
        except urllib.error.HTTPError as exc:
            # Graph returns the error detail in the body, so read it rather than raise.
            return Response(exc.code, dict(exc.headers or {}), _decode(exc.read()))
        except urllib.error.URLError as exc:
            raise TransportError(f"request to {url} failed: {exc.reason}") from exc


def _decode(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def backoff_delay(
    response: Response,
    attempt: int,
    base: float,
    cap: float,
    jitter: Callable[[], float],
) -> float:
    """Honour Retry-After when Meta sends one, otherwise exponential backoff."""
    header = response.header("Retry-After")
    if header:
        try:
            return min(float(header), RETRY_AFTER_CAP)
        except ValueError:
            pass
    delay = min(cap, base * (2 ** (attempt - 1)))
    return delay * (1 + 0.25 * jitter())


@dataclass(slots=True)
class WhatsAppClient:
    settings: Settings
    transport: Transport = field(default_factory=UrllibTransport)
    windows: WindowTracker | None = None
    max_attempts: int = 4
    backoff_base: float = 0.5
    backoff_cap: float = 30.0
    sleep: Callable[[float], None] = time.sleep
    jitter: Callable[[], float] = random.random

    def send_text(self, to: str, body: str, *, now: datetime | None = None) -> str:
        """Free-form message. Refused outside the 24 hour window before it leaves the box.

        Meta would answer 131047 anyway; failing locally keeps the failure
        readable and saves a round trip against the throughput budget.
        """
        if self.windows is not None:
            moment = now or datetime.now(timezone.utc)
            last = self.windows.last_inbound(to)
            if required_mode(last, moment) is SendMode.TEMPLATE:
                raise WindowClosedError(
                    f"The 24 hour window for {to} is closed "
                    f"(last inbound: {last.isoformat() if last else 'never'}). "
                    "Open the conversation with send_template()."
                )
        return self._send(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body},
            }
        )

    def send_template(
        self,
        to: str,
        name: str,
        language: str = "de",
        parameters: list[str] | None = None,
    ) -> str:
        """Approved template. The only way to reopen a closed conversation."""
        template: dict[str, Any] = {"name": name, "language": {"code": language}}
        if parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in parameters],
                }
            ]
        return self._send(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": template,
            }
        )

    def _send(self, payload: dict[str, Any]) -> str:
        """Return the wamid Meta assigned to the accepted message."""
        response = self._post_with_retry(payload)
        messages = response.body.get("messages") or [{}]
        return str(messages[0].get("id", ""))

    def _post_with_retry(self, payload: dict[str, Any]) -> Response:
        headers = {"Authorization": f"Bearer {self.settings.token}"}
        last: Response | None = None
        for attempt in range(1, self.max_attempts + 1):
            last = self.transport.post_json(self.settings.messages_url, headers, payload)
            if last.ok:
                return last
            if attempt == self.max_attempts or not last.retryable:
                break
            self.sleep(
                backoff_delay(last, attempt, self.backoff_base, self.backoff_cap, self.jitter)
            )
        assert last is not None  # max_attempts is always >= 1
        raise WhatsAppError.from_payload(last.status, last.body)
