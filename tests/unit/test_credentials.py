"""Tests for mthds.config.credentials — load, get, set, resolve_key."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.config.credentials import (
    CredentialSource,
    get_credential_value,
    load_credentials,
    resolve_key,
    set_credential_value,
)


class TestCredentials:
    """Tests for the credentials module public API."""

    @pytest.fixture(autouse=True)
    def _isolate_credentials(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Redirect config I/O to a temporary directory."""
        config_dir = tmp_path / ".mthds"
        config_dir.mkdir()
        credentials_path = config_dir / "config"

        mocker.patch("mthds.config.credentials.CONFIG_DIR", config_dir)
        mocker.patch("mthds.config.credentials.CONFIG_PATH", credentials_path)
        # Hermetic env: a real MTHDS_* var on the dev/CI machine must not leak in.
        # Tests that need env vars layer their own mocker.patch.dict on top of this clean slate.
        mocker.patch.dict("os.environ", clear=True)

    # ── resolve_key ──────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("cli_key", "expected"),
        [
            ("runner", "runner"),
            ("api-url", "api_url"),
            ("api-key", "api_key"),
            ("telemetry", "telemetry"),
        ],
    )
    def test_resolve_key_valid(self, cli_key: str, expected: str) -> None:
        """Known CLI flag names resolve to the correct internal key."""
        assert resolve_key(cli_key) == expected

    def test_resolve_key_unknown_returns_none(self) -> None:
        """An unknown CLI flag returns None."""
        assert resolve_key("nonexistent-key") is None

    # ── load_credentials: defaults / file / env ──────────────────

    def test_load_credentials_returns_defaults_when_no_file(self) -> None:
        """With no credentials file, defaults are returned."""
        creds = load_credentials()
        assert creds["runner"] == "api"
        assert creds["api_url"] == "https://api.pipelex.com"
        assert creds["api_key"] == ""
        assert creds["telemetry"] == "0"

    def test_load_credentials_reads_file(self, tmp_path: Path) -> None:
        """Values written to the credentials file override defaults."""
        creds_path = tmp_path / ".mthds" / "config"
        creds_path.write_text("MTHDS_RUNNER=pipelex\nMTHDS_API_KEY=my-secret\n", encoding="utf-8")

        creds = load_credentials()
        assert creds["runner"] == "pipelex"
        assert creds["api_key"] == "my-secret"
        # Unchanged keys still return defaults
        assert creds["api_url"] == "https://api.pipelex.com"

    def test_load_credentials_env_overrides_file(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Environment variables take precedence over file values."""
        creds_path = tmp_path / ".mthds" / "config"
        creds_path.write_text("MTHDS_RUNNER=pipelex\n", encoding="utf-8")

        mocker.patch.dict("os.environ", {"MTHDS_RUNNER": "api"})

        creds = load_credentials()
        assert creds["runner"] == "api"

    def test_load_credentials_env_overrides_defaults(self, mocker: MockerFixture) -> None:
        """Environment variables take precedence over defaults (no file)."""
        mocker.patch.dict("os.environ", {"MTHDS_API_KEY": "env-key-value"})

        creds = load_credentials()
        assert creds["api_key"] == "env-key-value"

    # ── get_credential_value ─────────────────────────────────────

    def test_get_credential_value_default_source(self) -> None:
        """When no file or env var exists, source is DEFAULT."""
        entry = get_credential_value("runner")
        assert entry.value == "api"
        assert entry.source == CredentialSource.DEFAULT
        assert entry.key == "runner"
        assert entry.cli_key == "runner"

    def test_get_credential_value_file_source(self, tmp_path: Path) -> None:
        """When value comes from file, source is FILE."""
        creds_path = tmp_path / ".mthds" / "config"
        creds_path.write_text("MTHDS_API_KEY=file-key\n", encoding="utf-8")

        entry = get_credential_value("api_key")
        assert entry.value == "file-key"
        assert entry.source == CredentialSource.FILE
        assert entry.cli_key == "api-key"

    def test_get_credential_value_env_source(self, mocker: MockerFixture) -> None:
        """When value comes from env, source is ENV and it wins over file."""
        mocker.patch.dict("os.environ", {"MTHDS_API_URL": "https://custom.url"})

        entry = get_credential_value("api_url")
        assert entry.value == "https://custom.url"
        assert entry.source == CredentialSource.ENV
        assert entry.cli_key == "api-url"

    # ── set_credential_value ─────────────────────────────────────

    def test_set_credential_value_creates_file(self, tmp_path: Path) -> None:
        """Setting a value creates the credentials file with the entry."""
        set_credential_value("runner", "pipelex")

        creds_path = tmp_path / ".mthds" / "config"
        content = creds_path.read_text(encoding="utf-8")
        assert "MTHDS_RUNNER=pipelex" in content

    def test_set_credential_value_uses_new_key(self, tmp_path: Path) -> None:
        """Setting api_url / api_key writes the new MTHDS_ storage keys."""
        set_credential_value("api_url", "https://alt.api.com")
        set_credential_value("api_key", "fresh-key")

        creds_path = tmp_path / ".mthds" / "config"
        content = creds_path.read_text(encoding="utf-8")
        assert "MTHDS_API_URL=https://alt.api.com" in content
        assert "MTHDS_API_KEY=fresh-key" in content

    def test_set_credential_value_preserves_other_keys(self, tmp_path: Path) -> None:
        """Setting one key does not remove other keys from the file."""
        creds_path = tmp_path / ".mthds" / "config"
        creds_path.write_text("MTHDS_API_KEY=existing\n", encoding="utf-8")

        set_credential_value("runner", "pipelex")

        content = creds_path.read_text(encoding="utf-8")
        assert "MTHDS_API_KEY=existing" in content
        assert "MTHDS_RUNNER=pipelex" in content

    def test_set_then_get_round_trip(self) -> None:
        """A value set via set_credential_value is returned by get_credential_value."""
        set_credential_value("api_key", "round-trip-key")

        entry = get_credential_value("api_key")
        assert entry.value == "round-trip-key"
        assert entry.source == CredentialSource.FILE

    # ── credentials file parsing edge cases ──────────────────────

    def test_load_credentials_ignores_comments_and_blanks(self, tmp_path: Path) -> None:
        """Comments and blank lines in the credentials file are ignored."""
        creds_path = tmp_path / ".mthds" / "config"
        creds_path.write_text(
            "# This is a comment\n\nMTHDS_RUNNER=pipelex\n\n# Another comment\n",
            encoding="utf-8",
        )

        creds = load_credentials()
        assert creds["runner"] == "pipelex"
