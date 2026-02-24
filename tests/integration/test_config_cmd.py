"""Integration tests for mthds.cli.commands.config_cmd — set, get, list with real temp files."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.cli.commands.config_cmd import do_config_get, do_config_list, do_config_set
from mthds.config.credentials import CredentialSource, get_credential_value, list_credentials


class TestConfigCmd:
    """Integration tests for config command functions with temp credentials files."""

    @pytest.fixture(autouse=True)
    def _isolate_credentials(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Redirect credentials I/O to a temporary directory and reset migration flag."""
        config_dir = tmp_path / ".mthds"
        config_dir.mkdir()
        credentials_path = config_dir / "credentials"

        mocker.patch("mthds.config.credentials.CONFIG_DIR", config_dir)
        mocker.patch("mthds.config.credentials.CREDENTIALS_PATH", credentials_path)
        mocker.patch("mthds.config.credentials._migrate_if_needed")

    def test_config_set_and_get_roundtrip(self) -> None:
        """Setting a key via do_config_set then reading via credentials API returns the correct value."""
        do_config_set("runner", "pipelex")

        entry = get_credential_value("runner")
        assert entry.value == "pipelex"
        assert entry.source == CredentialSource.FILE

    def test_config_set_multiple_keys(self) -> None:
        """Setting multiple keys preserves all values."""
        do_config_set("runner", "pipelex")
        do_config_set("api-key", "test-secret-key")
        do_config_set("api-url", "https://custom.api.example.com")

        runner_entry = get_credential_value("runner")
        api_key_entry = get_credential_value("api_key")
        api_url_entry = get_credential_value("api_url")

        assert runner_entry.value == "pipelex"
        assert api_key_entry.value == "test-secret-key"
        assert api_url_entry.value == "https://custom.api.example.com"

    def test_config_get_unknown_key(self) -> None:
        """Getting an unknown key prints an error message without raising."""
        # The function prints to the Rich console (stderr) — it doesn't raise.
        do_config_get("nonexistent-key")

    def test_config_get_returns_default_for_unset_key(self) -> None:
        """Getting a key that has not been set returns its default value."""
        entry = get_credential_value("runner")
        assert entry.value == "api"
        assert entry.source == CredentialSource.DEFAULT

    def test_config_list_shows_all_keys(self) -> None:
        """list_credentials returns entries for runner, api-url, api-key, and telemetry."""
        entries = list_credentials()

        cli_keys = [entry.cli_key for entry in entries]
        assert "runner" in cli_keys
        assert "api-url" in cli_keys
        assert "api-key" in cli_keys
        assert "telemetry" in cli_keys
        assert len(entries) == 4

    def test_config_list_after_set(self) -> None:
        """list_credentials reflects values set via do_config_set."""
        do_config_set("runner", "pipelex")
        do_config_set("api-key", "my-secret")

        entries = list_credentials()
        entries_by_cli_key = {entry.cli_key: entry for entry in entries}

        assert entries_by_cli_key["runner"].value == "pipelex"
        assert entries_by_cli_key["runner"].source == CredentialSource.FILE
        assert entries_by_cli_key["api-key"].value == "my-secret"
        assert entries_by_cli_key["api-key"].source == CredentialSource.FILE
        # Unset keys should be defaults
        assert entries_by_cli_key["telemetry"].source == CredentialSource.DEFAULT

    def test_do_config_list_executes_without_error(self) -> None:
        """do_config_list runs without raising (outputs a Rich table to console)."""
        do_config_list()
