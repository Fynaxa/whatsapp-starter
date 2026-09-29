"""Configuration loaded from the environment. No secret ever lives in the code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_VARS = ("WHATSAPP_TOKEN", "PHONE_NUMBER_ID", "APP_SECRET", "VERIFY_TOKEN")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the client and the webhook need to run."""

    # Credentials are kept out of repr(): dataclass reprs end up in tracebacks and logs.
    token: str = field(repr=False)
    phone_number_id: str
    app_secret: str = field(repr=False)
    verify_token: str = field(repr=False)
    api_version: str = "v21.0"
    base_url: str = "https://graph.facebook.com"
    state_dir: Path = Path(".state")

    @property
    def messages_url(self) -> str:
        return f"{self.base_url}/{self.api_version}/{self.phone_number_id}/messages"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        missing = [name for name in REQUIRED_VARS if not source.get(name)]
        if missing:
            raise ConfigError(
                "Missing environment variables: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill it in."
            )
        return cls(
            token=source["WHATSAPP_TOKEN"],
            phone_number_id=source["PHONE_NUMBER_ID"],
            app_secret=source["APP_SECRET"],
            verify_token=source["VERIFY_TOKEN"],
            api_version=source.get("GRAPH_API_VERSION", "v21.0"),
            base_url=source.get("GRAPH_BASE_URL", "https://graph.facebook.com"),
            state_dir=Path(source.get("STATE_DIR", ".state")),
        )


def load_dotenv(path: Path = Path(".env")) -> None:
    """Populate os.environ from a .env file. Existing variables always win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
