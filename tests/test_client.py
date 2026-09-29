"""Sending: window gate, retry policy, and failures that read like sentences."""

from __future__ import annotations

from datetime import timedelta

import pytest

from whatsapp_starter import Settings, WhatsAppClient, WhatsAppError, WindowClosedError
from whatsapp_starter.client import Response, backoff_delay

from .conftest import CUSTOMER, NOW, FakeTransport, accepted, refused


def build(settings: Settings, responses: list[Response], windows=None):
    """A client whose clock and randomness are frozen, so delays are assertable."""
    transport = FakeTransport(responses)
    slept: list[float] = []
    client = WhatsAppClient(
        settings=settings,
        transport=transport,
        windows=windows,
        sleep=slept.append,
        jitter=lambda: 0.0,
    )
    return client, transport, slept


def test_a_successful_send_returns_the_message_id(settings: Settings) -> None:
    client, transport, slept = build(settings, [accepted("wamid.XYZ")])
    assert client.send_text(CUSTOMER, "Moin") == "wamid.XYZ"
    assert slept == []
    assert transport.calls[0]["url"].endswith("/1234567890/messages")
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer test-token"


def test_rate_limiting_triggers_exponential_backoff(settings: Settings) -> None:
    client, transport, slept = build(
        settings, [refused(429, 130429), refused(429, 130429), accepted()]
    )
    client.send_text(CUSTOMER, "Moin")
    assert len(transport.calls) == 3
    assert slept == [0.5, 1.0]


def test_a_retry_after_header_overrides_the_backoff_curve(settings: Settings) -> None:
    client, _, slept = build(settings, [refused(429, 130429, {"Retry-After": "7"}), accepted()])
    client.send_text(CUSTOMER, "Moin")
    assert slept == [7.0]


def test_server_errors_are_retried(settings: Settings) -> None:
    client, transport, slept = build(settings, [Response(503, {}, {}), accepted()])
    client.send_text(CUSTOMER, "Moin")
    assert len(transport.calls) == 2
    assert slept == [0.5]


def test_a_client_mistake_is_not_retried(settings: Settings) -> None:
    client, transport, slept = build(settings, [refused(400, 132000)])
    with pytest.raises(WhatsAppError) as raised:
        client.send_template(CUSTOMER, "termin_erinnerung", parameters=["Montag"])
    assert len(transport.calls) == 1
    assert slept == []
    assert "parameter count" in raised.value.explanation


def test_retries_stop_at_max_attempts(settings: Settings) -> None:
    client, transport, slept = build(settings, [refused(429, 130429)])
    with pytest.raises(WhatsAppError) as raised:
        client.send_text(CUSTOMER, "Moin")
    assert len(transport.calls) == client.max_attempts
    assert slept == [0.5, 1.0, 2.0]
    assert raised.value.retryable is True


def test_the_backoff_is_capped(settings: Settings) -> None:
    capped = backoff_delay(Response(429, {}, {}), attempt=12, base=0.5, cap=30.0, jitter=lambda: 0.0)
    assert capped == 30.0


def test_free_form_text_is_refused_once_the_window_closed(settings: Settings, windows) -> None:
    windows.record_inbound(CUSTOMER, NOW - timedelta(hours=25))
    client, transport, _ = build(settings, [accepted()], windows=windows)
    with pytest.raises(WindowClosedError, match="send_template"):
        client.send_text(CUSTOMER, "Moin", now=NOW)
    assert transport.calls == []


def test_free_form_text_passes_inside_the_window(settings: Settings, windows) -> None:
    windows.record_inbound(CUSTOMER, NOW - timedelta(hours=23))
    client, transport, _ = build(settings, [accepted()], windows=windows)
    client.send_text(CUSTOMER, "Moin", now=NOW)
    assert transport.calls[0]["payload"]["type"] == "text"


def test_a_template_reopens_a_closed_conversation(settings: Settings, windows) -> None:
    windows.record_inbound(CUSTOMER, NOW - timedelta(days=4))
    client, transport, _ = build(settings, [accepted()], windows=windows)
    client.send_template(CUSTOMER, "termin_erinnerung", "de", ["Montag 10:00"])
    payload = transport.calls[0]["payload"]
    assert payload["type"] == "template"
    assert payload["template"]["language"] == {"code": "de"}
    assert payload["template"]["components"][0]["parameters"][0]["text"] == "Montag 10:00"


def test_the_re_engagement_error_explains_itself(settings: Settings) -> None:
    client, _, _ = build(settings, [refused(400, 131047)])
    with pytest.raises(WhatsAppError) as raised:
        client.send_text(CUSTOMER, "Moin")
    assert "approved template" in raised.value.explanation
    assert raised.value.retryable is False
