"""Integration tests for mthds.config.credentials — real file operations with temp directories."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.config.credentials import (
    CredentialSource,
    get_credential_value,
    load_credentials,
    set_credential_value,
)


class TestCredentialsIntegration:
    """Integration tests for credentials with real file I/O using tmp_path."""

    @pytest.fixture(autouse=True)
    def _isolate_credentials(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Redirect credentials I/O to a temporary directory and reset migration flag."""
        config_dir = tmp_path / ".mthds"
        config_dir.mkdir()
        credentials_path = config_dir / "credentials"

        mocker.patch("mthds.config.credentials.CONFIG_DIR", config_dir)
        mocker.patch("mthds.config.credentials.CREDENTIALS_PATH", credentials_path)
        mocker.patch("mthds.config.credentials._migrate_if_needed")

    def test_write_and_read_credentials(self, tmp_path: Path) -> None:
        """Writing credentials to a temp file and reading back returns the same values."""
        set_credential_value("runner", "pipelex")
        set_credential_value("api_key", "secret-123")
        set_credential_value("api_url", "https://custom.example.com")

        creds = load_credentials()
        assert creds["runner"] == "pipelex"
        assert creds["api_key"] == "secret-123"
        assert creds["api_url"] == "https://custom.example.com"

        # Verify the file actually exists on disk
        creds_path = tmp_path / ".mthds" / "credentials"
        assert creds_path.is_file()
        content = creds_path.read_text(encoding="utf-8")
        assert "MTHDS_RUNNER=pipelex" in content
        assert "PIPELEX_API_KEY=secret-123" in content
        assert "PIPELEX_API_URL=https://custom.example.com" in content

    def test_env_override_file(self, mocker: MockerFixture) -> None:
        """Environment variables take precedence over values in the credentials file."""
        set_credential_value("runner", "pipelex")

        # Verify file value
        entry_before = get_credential_value("runner")
        assert entry_before.value == "pipelex"
        assert entry_before.source == CredentialSource.FILE

        # Set env var to override
        mocker.patch.dict("os.environ", {"MTHDS_RUNNER": "api"})

        entry_after = get_credential_value("runner")
        assert entry_after.value == "api"
        assert entry_after.source == CredentialSource.ENV

    def test_missing_file_uses_defaults(self) -> None:
        """With no credentials file, default values are returned."""
        creds = load_credentials()

        assert creds["runner"] == "api"
        assert creds["api_url"] == "https://api.pipelex.com"
        assert creds["api_key"] == ""
        assert creds["telemetry"] == "0"

    def test_missing_file_source_is_default(self) -> None:
        """With no credentials file, source is DEFAULT for all keys."""
        for key in ("runner", "api_url", "api_key", "telemetry"):
            entry = get_credential_value(key)
            assert entry.source == CredentialSource.DEFAULT, f"Expected DEFAULT source for {key}, got {entry.source}"

    def test_overwrite_existing_value(self, tmp_path: Path) -> None:
        """Setting a key that already exists in the file overwrites the value."""
        set_credential_value("runner", "pipelex")
        set_credential_value("runner", "api")

        entry = get_credential_value("runner")
        assert entry.value == "api"
        assert entry.source == CredentialSource.FILE

        creds_path = tmp_path / ".mthds" / "credentials"
        content = creds_path.read_text(encoding="utf-8")
        assert content.count("MTHDS_RUNNER=") == 1

    def test_file_content_is_dotenv_format(self, tmp_path: Path) -> None:
        """The credentials file uses KEY=VALUE format with newlines."""
        set_credential_value("api_key", "my-key")
        set_credential_value("runner", "pipelex")

        creds_path = tmp_path / ".mthds" / "credentials"
        content = creds_path.read_text(encoding="utf-8")
        lines = [line for line in content.strip().splitlines() if line.strip()]

        for line in lines:
            assert "=" in line, f"Line does not have KEY=VALUE format: {line}"

    def test_load_after_multiple_set_operations(self) -> None:
        """Multiple set operations followed by load returns all values correctly."""
        set_credential_value("runner", "pipelex")
        set_credential_value("api_key", "key-abc")
        set_credential_value("telemetry", "1")
        set_credential_value("api_url", "https://alt.api.com")

        creds = load_credentials()
        assert creds["runner"] == "pipelex"
        assert creds["api_key"] == "key-abc"
        assert creds["telemetry"] == "1"
        assert creds["api_url"] == "https://alt.api.com"
