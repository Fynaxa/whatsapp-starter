"""X-Hub-Signature-256 must accept exactly Meta's payloads and nothing else."""

from __future__ import annotations

import pytest

from whatsapp_starter import sign, verify_signature

SECRET = "test-app-secret"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


def test_valid_signature_is_accepted() -> None:
    assert verify_signature(SECRET, BODY, sign(SECRET, BODY)) is True


def test_tampered_body_is_rejected() -> None:
    assert verify_signature(SECRET, BODY + b" ", sign(SECRET, BODY)) is False


def test_wrong_secret_is_rejected() -> None:
    assert verify_signature(SECRET, BODY, sign("other-secret", BODY)) is False


@pytest.mark.parametrize(
    "header",
    [None, "", "sha1=deadbeef", sign(SECRET, BODY).removeprefix("sha256="), "sha256=zz"],
)
def test_malformed_headers_are_rejected(header: str | None) -> None:
    assert verify_signature(SECRET, BODY, header) is False


def test_whitespace_around_the_header_is_tolerated() -> None:
    assert verify_signature(SECRET, BODY, sign(SECRET, BODY) + "\n") is True


def test_empty_body_still_has_a_defined_signature() -> None:
    assert verify_signature(SECRET, b"", sign(SECRET, b"")) is True
