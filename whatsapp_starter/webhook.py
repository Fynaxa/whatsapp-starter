"""WSGI webhook: verification handshake, signature check, idempotent dispatch."""

from __future__ import annotations

import hmac
import json
import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import parse_qs

from .config import Settings
from .dedup import DedupStore
from .events import Event, InboundMessage, StatusUpdate, parse_events
from .signature import verify_signature
from .window import WindowTracker

LOGGER = logging.getLogger("whatsapp_starter.webhook")
MAX_BODY = 1 << 20  # Webhook payloads are small; anything larger is not from Meta.


@dataclass(slots=True)
class WebhookApp:
    """A plain WSGI application. Run it behind gunicorn, uwsgi or wsgiref."""

    settings: Settings
    dedup: DedupStore
    windows: WindowTracker
    on_message: Callable[[InboundMessage], None] | None = None
    on_status: Callable[[StatusUpdate], None] | None = None

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        if method == "GET":
            return self._verify(environ, start_response)
        if method == "POST":
            return self._receive(environ, start_response)
        return _reply(start_response, 405, "method not allowed")

    def _verify(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        query = parse_qs(environ.get("QUERY_STRING", ""))
        mode = query.get("hub.mode", [""])[0]
        token = query.get("hub.verify_token", [""])[0]
        if mode == "subscribe" and hmac.compare_digest(token, self.settings.verify_token):
            # Meta expects the challenge back verbatim, as plain text.
            return _reply(start_response, 200, query.get("hub.challenge", [""])[0])
        LOGGER.warning("webhook verification rejected")
        return _reply(start_response, 403, "verification failed")

    def _receive(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        if length > MAX_BODY:
            return _reply(start_response, 413, "payload too large")
        body: bytes = environ["wsgi.input"].read(length)
        header = environ.get("HTTP_X_HUB_SIGNATURE_256")
        if not verify_signature(self.settings.app_secret, body, header):
            LOGGER.warning("rejected webhook with invalid signature")
            return _reply(start_response, 403, "invalid signature")
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return _reply(start_response, 400, "invalid json")
        for event in parse_events(payload):
            self.handle(event)
        # Answer 200 for every authentic payload. A 5xx makes Meta redeliver the
        # whole batch, so one bad event would replay every good one with it.
        return _reply(start_response, 200, "EVENT_RECEIVED")

    def handle(self, event: Event) -> bool:
        """Process one event once. False means it was a duplicate delivery."""
        if self.dedup.seen_before(event.dedup_key):
            LOGGER.info("duplicate delivery ignored: %s", event.dedup_key)
            return False
        try:
            if isinstance(event, InboundMessage):
                self.windows.record_inbound(event.wa_id, event.timestamp)
                if self.on_message is not None:
                    self.on_message(event)
            else:
                if event.failed:
                    LOGGER.error("message %s failed: %s", event.id, event.explanation)
                if self.on_status is not None:
                    self.on_status(event)
        except Exception:
            # Hand the key back so the event can be replayed once the bug is fixed.
            self.dedup.release(event.dedup_key)
            LOGGER.exception("handler raised for %s", event.dedup_key)
        return True


def _reply(start_response: Callable, status: int, body: str) -> list[bytes]:
    encoded = body.encode("utf-8")
    start_response(
        f"{status} {HTTPStatus(status).phrase}",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(encoded))),
        ],
    )
    return [encoded]
