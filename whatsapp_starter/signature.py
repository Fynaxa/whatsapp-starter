"""Payload authentication for inbound webhooks (X-Hub-Signature-256)."""

from __future__ import annotations

import hashlib
import hmac

HEADER = "X-Hub-Signature-256"
_PREFIX = "sha256="


def sign(app_secret: str, body: bytes) -> str:
    """Return the header value Meta would send for this exact body."""
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return _PREFIX + digest


def verify_signature(app_secret: str, body: bytes, header_value: str | None) -> bool:
    """Constant-time check of the raw request body against the app secret.

    The signature covers the bytes exactly as they arrived. Re-serialising the
    parsed JSON and hashing that will not match, which is the usual reason a
    correct implementation still rejects every request.
    """
    if not header_value or not header_value.startswith(_PREFIX):
        return False
    expected = sign(app_secret, body)
    return hmac.compare_digest(expected, header_value.strip())
