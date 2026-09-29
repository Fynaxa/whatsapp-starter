"""Meta error codes translated into sentences an operator can act on."""

from __future__ import annotations

from typing import Any

# Codes worth retrying: throughput ceilings and transient platform faults.
# Everything else is a client mistake that a retry only repeats.
RETRYABLE_CODES = frozenset({4, 80007, 130429, 131000, 131016, 131048, 131056})

ERROR_CATALOG: dict[int, str] = {
    0: "Authentication failed. The access token is missing, wrong or revoked.",
    4: "Too many API calls for this app. Slow down and retry with backoff.",
    100: "Invalid parameter. The request body does not match the Graph schema.",
    190: "Access token expired. Issue a new system user token.",
    368: "Temporarily blocked for policy violations. Do not retry; fix the policy issue.",
    80007: "Business account rate limit reached. Retry with backoff.",
    130429: "Cloud API throughput limit reached. Retry with backoff.",
    131000: "Unspecified platform error. Safe to retry once with backoff.",
    131008: "A required parameter is missing from the request.",
    131016: "Cloud API service is temporarily unavailable. Retry with backoff.",
    131026: "Undeliverable: the number is not on WhatsApp, or no template was used "
    "outside the 24 hour window.",
    131042: "Billing problem on the business account. Payment method must be fixed first.",
    131047: "Re-engagement required: more than 24 hours since the last customer message. "
    "Send an approved template instead of free-form text.",
    131048: "Spam rate limit hit. The number is sending faster than its quality tier allows.",
    131049: "Held back for ecosystem health: this user already received too much marketing.",
    131051: "Unsupported message type for this endpoint.",
    131056: "Pair rate limit hit: too many messages between this business and this user.",
    132000: "Template parameter count does not match the approved template.",
    132001: "Template does not exist in this language, or is not approved yet.",
    132012: "Template parameter format does not match the approved sample.",
    132015: "Template is paused because of poor quality feedback.",
    133010: "Phone number is not registered with the Cloud API.",
}


def describe(code: int | None, fallback: str = "") -> str:
    """Human readable meaning of a Meta error code."""
    if code is None:
        return fallback or "Unknown error: Meta returned no error code."
    known = ERROR_CATALOG.get(code)
    if known:
        return known
    return fallback or f"Unmapped Meta error code {code}. Check the Cloud API error reference."


class TransportError(RuntimeError):
    """The request never reached Meta: DNS, TLS, timeout, connection reset."""


class WindowClosedError(RuntimeError):
    """Free-form send attempted outside the 24 hour customer service window."""


class WhatsAppError(RuntimeError):
    """Meta answered, and the answer was a refusal."""

    def __init__(
        self,
        status: int,
        code: int | None = None,
        subcode: int | None = None,
        detail: str = "",
        fbtrace_id: str | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.subcode = subcode
        self.detail = detail
        self.fbtrace_id = fbtrace_id
        self.explanation = describe(code, detail)
        super().__init__(f"HTTP {status} (code {code}): {self.explanation}")

    @property
    def retryable(self) -> bool:
        return self.status == 429 or self.status >= 500 or self.code in RETRYABLE_CODES

    @classmethod
    def from_payload(cls, status: int, payload: dict[str, Any]) -> WhatsAppError:
        error = payload.get("error") or {}
        data = error.get("error_data") or {}
        return cls(
            status=status,
            code=_as_int(error.get("code")),
            subcode=_as_int(error.get("error_subcode")),
            detail=str(data.get("details") or error.get("message") or ""),
            fbtrace_id=error.get("fbtrace_id"),
        )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
