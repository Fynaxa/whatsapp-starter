"""The receiver: handshake, authenticity, and one delivery processed once."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from whatsapp_starter import InboundMessage, Settings, WebhookApp, sign

from .conftest import CUSTOMER, NOW, Recorder, call_wsgi, inbound_payload, status_payload


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def app(settings: Settings, dedup, windows, recorder: Recorder) -> WebhookApp:
    return WebhookApp(
        settings=settings,
        dedup=dedup,
        windows=windows,
        on_message=recorder.messages.append,
        on_status=recorder.statuses.append,
    )


def post(app: WebhookApp, payload: dict, secret: str = "test-app-secret") -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    return call_wsgi(app, body=body, signature=sign(secret, body))


def test_the_verification_handshake_returns_the_challenge(app: WebhookApp) -> None:
    status, body = call_wsgi(
        app,
        method="GET",
        query="hub.mode=subscribe&hub.verify_token=test-verify-token&hub.challenge=1158201444",
    )
    assert (status, body) == (200, "1158201444")


@pytest.mark.parametrize(
    "query",
    [
        "hub.mode=subscribe&hub.verify_token=guessed&hub.challenge=1",
        "hub.mode=unsubscribe&hub.verify_token=test-verify-token&hub.challenge=1",
        "",
    ],
)
def test_a_failed_handshake_never_echoes_the_challenge(app: WebhookApp, query: str) -> None:
    status, body = call_wsgi(app, method="GET", query=query)
    assert status == 403
    assert "1" not in body


def test_an_unsigned_payload_is_rejected(app: WebhookApp, recorder: Recorder) -> None:
    body = json.dumps(inbound_payload()).encode("utf-8")
    assert call_wsgi(app, body=body)[0] == 403
    assert recorder.messages == []


def test_a_payload_signed_with_the_wrong_secret_is_rejected(
    app: WebhookApp, recorder: Recorder
) -> None:
    assert post(app, inbound_payload(), secret="stolen-but-wrong")[0] == 403
    assert recorder.messages == []


def test_a_signed_payload_is_accepted_and_dispatched(
    app: WebhookApp, recorder: Recorder
) -> None:
    status, body = post(app, inbound_payload(text="Habt ihr Montag frei?"))
    assert (status, body) == (200, "EVENT_RECEIVED")
    assert [(m.wa_id, m.text) for m in recorder.messages] == [(CUSTOMER, "Habt ihr Montag frei?")]


def test_a_redelivered_message_is_processed_exactly_once(
    app: WebhookApp, recorder: Recorder
) -> None:
    payload = inbound_payload(message_id="wamid.REPEAT")
    for _ in range(3):
        assert post(app, payload)[0] == 200
    assert len(recorder.messages) == 1


def test_an_inbound_message_opens_the_window(app: WebhookApp) -> None:
    post(app, inbound_payload())
    assert app.windows.is_open(CUSTOMER, NOW + timedelta(hours=1)) is True
    assert app.windows.is_open(CUSTOMER, NOW + timedelta(hours=25)) is False


def test_every_delivery_state_of_one_message_is_its_own_event(
    app: WebhookApp, recorder: Recorder
) -> None:
    for state in ("sent", "delivered", "read"):
        post(app, status_payload(state))
    post(app, status_payload("delivered"))
    assert [s.status for s in recorder.statuses] == ["sent", "delivered", "read"]


def test_a_failed_status_carries_a_readable_reason(
    app: WebhookApp, recorder: Recorder
) -> None:
    post(app, status_payload("failed", code=131026))
    failure = recorder.statuses[0]
    assert failure.failed is True
    assert failure.error_code == 131026
    assert "not on WhatsApp" in (failure.explanation or "")


def test_a_broken_handler_answers_200_and_leaves_the_event_replayable(app: WebhookApp) -> None:
    attempts: list[str] = []

    def flaky(message: InboundMessage) -> None:
        attempts.append(message.id)
        if len(attempts) == 1:
            raise RuntimeError("database down")

    app.on_message = flaky
    payload = inbound_payload(message_id="wamid.FLAKY")
    assert post(app, payload)[0] == 200
    assert post(app, payload)[0] == 200
    assert attempts == ["wamid.FLAKY", "wamid.FLAKY"]


def test_authentic_but_unparsable_json_is_a_bad_request(app: WebhookApp) -> None:
    body = b"{not json"
    assert call_wsgi(app, body=body, signature=sign("test-app-secret", body))[0] == 400


def test_other_http_methods_are_not_allowed(app: WebhookApp) -> None:
    assert call_wsgi(app, method="DELETE")[0] == 405
