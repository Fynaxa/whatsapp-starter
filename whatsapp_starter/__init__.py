"""A small, production-shaped starter for the WhatsApp Business Cloud API."""

from __future__ import annotations

from .client import Response, Transport, UrllibTransport, WhatsAppClient
from .config import ConfigError, Settings, load_dotenv
from .dedup import DedupStore
from .errors import TransportError, WhatsAppError, WindowClosedError, describe
from .events import InboundMessage, StatusUpdate, parse_events
from .signature import sign, verify_signature
from .webhook import WebhookApp
from .window import SendMode, WindowTracker, closes_at, is_open, required_mode

__version__ = "1.0.0"

__all__ = [
    "ConfigError",
    "DedupStore",
    "InboundMessage",
    "Response",
    "SendMode",
    "Settings",
    "StatusUpdate",
    "Transport",
    "TransportError",
    "UrllibTransport",
    "WebhookApp",
    "WhatsAppClient",
    "WhatsAppError",
    "WindowClosedError",
    "WindowTracker",
    "closes_at",
    "describe",
    "is_open",
    "load_dotenv",
    "parse_events",
    "required_mode",
    "sign",
    "verify_signature",
]
