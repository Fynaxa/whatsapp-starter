"""Shared fixtures. Every test runs offline: no socket is ever opened."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from whatsapp_starter import (
    DedupStore,
    InboundMessage,
    Response,
    Settings,
    StatusUpdate,
    WindowTracker,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
CUSTOMER = "4915112345678"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        token="test-token",
        phone_number_id="1234567890",
        app_secret="test-app-secret",
        verify_token="test-verify-token",
        state_dir=tmp_path,
    )


@pytest.fixture
def windows(tmp_path: Path) -> WindowTracker:
    return WindowTracker(tmp_path / "windows.json")


@pytest.fixture
def dedup(tmp_path: Path) -> DedupStore:
    return DedupStore(tmp_path / "seen")


@dataclass
class Recorder:
    """Collects what the webhook handed to the application callbacks."""

    messages: list[InboundMessage] = field(default_factory=list)
    statuses: list[StatusUpdate] = field(default_factory=list)


@dataclass
class FakeTransport:
    """Replays canned Graph API answers and records what was sent."""

    responses: list[Response]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> Response:
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def accepted(message_id: str = "wamid.OUT1") -> Response:
    return Response(200, {}, {"messages": [{"id": message_id}]})


def refused(status: int, code: int, headers: dict[str, str] | None = None) -> Response:
    return Response(
        status,
        headers or {},
        {"error": {"code": code, "message": "graph said no", "fbtrace_id": "A1"}},
    )


def call_wsgi(
    app: Callable,
    *,
    method: str = "POST",
    query: str = "",
    body: bytes = b"",
    signature: str | None = None,
) -> tuple[int, str]:
    """Drive a WSGI app in-process and return (status code, body)."""
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    if signature is not None:
        environ["HTTP_X_HUB_SIGNATURE_256"] = signature
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = int(status.split(" ", 1)[0])

    chunks = app(environ, start_response)
    return captured["status"], b"".join(chunks).decode("utf-8")


def inbound_payload(message_id: str = "wamid.IN1", text: str = "Hallo") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": CUSTOMER,
                                    "timestamp": str(int(NOW.timestamp())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def status_payload(status: str, code: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "wamid.OUT1",
        "recipient_id": CUSTOMER,
        "status": status,
        "timestamp": str(int(NOW.timestamp())),
    }
    if code is not None:
        entry["errors"] = [{"code": code, "title": "Message undeliverable"}]
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {"statuses": [entry]}}]}],
    }
