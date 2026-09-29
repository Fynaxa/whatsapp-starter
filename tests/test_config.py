"""Configuration: loaded from the environment, and never echoed back."""

from __future__ import annotations

from pathlib import Path

import pytest

from whatsapp_starter import ConfigError, Settings, load_dotenv

COMPLETE = {
    "WHATSAPP_TOKEN": "EAAG-secret",
    "PHONE_NUMBER_ID": "1234567890",
    "APP_SECRET": "app-secret",
    "VERIFY_TOKEN": "verify-token",
}


def test_a_complete_environment_produces_settings() -> None:
    settings = Settings.from_env(COMPLETE)
    assert settings.phone_number_id == "1234567890"
    assert settings.messages_url == "https://graph.facebook.com/v21.0/1234567890/messages"


@pytest.mark.parametrize("missing", sorted(COMPLETE))
def test_a_missing_variable_is_named_in_the_error(missing: str) -> None:
    env = {key: value for key, value in COMPLETE.items() if key != missing}
    with pytest.raises(ConfigError, match=missing):
        Settings.from_env(env)


def test_an_empty_string_counts_as_missing() -> None:
    with pytest.raises(ConfigError, match="APP_SECRET"):
        Settings.from_env({**COMPLETE, "APP_SECRET": ""})


def test_optional_overrides_are_honoured() -> None:
    settings = Settings.from_env({**COMPLETE, "GRAPH_API_VERSION": "v23.0", "STATE_DIR": "/srv/s"})
    assert "/v23.0/" in settings.messages_url
    assert settings.state_dir == Path("/srv/s")


def test_credentials_stay_out_of_the_repr() -> None:
    printed = repr(Settings.from_env(COMPLETE))
    assert "EAAG-secret" not in printed
    assert "app-secret" not in printed
    assert "1234567890" in printed


def test_dotenv_never_overrides_a_variable_that_is_already_set(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATSAPP_TOKEN", "from-the-shell")
    monkeypatch.delenv("VERIFY_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nWHATSAPP_TOKEN=from-the-file\nVERIFY_TOKEN='quoted-value'\n", encoding="utf-8"
    )

    load_dotenv(env_file)

    import os

    assert os.environ["WHATSAPP_TOKEN"] == "from-the-shell"
    assert os.environ["VERIFY_TOKEN"] == "quoted-value"


def test_a_missing_dotenv_file_is_not_an_error(tmp_path) -> None:
    load_dotenv(tmp_path / "nope.env")
