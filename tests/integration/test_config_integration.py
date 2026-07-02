"""Integration tests for mthds.config — real file operations with temp directories."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.config import (
    ConfigSource,
    get_config_value,
    load_config,
    set_config_value,
)


class TestConfigIntegration:
    """Integration tests for config with real file I/O using tmp_path."""

    @pytest.fixture(autouse=True)
    def _isolate_config(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Redirect config I/O to a temporary directory."""
        config_dir = tmp_path / ".mthds"
        config_dir.mkdir()
        config_path = config_dir / "config"

        mocker.patch("mthds.config.CONFIG_DIR", config_dir)
        mocker.patch("mthds.config.CONFIG_PATH", config_path)
        # Hermetic env: a real MTHDS_* var on the dev/CI machine must not leak in.
        mocker.patch.dict("os.environ", clear=True)

    def test_write_and_read_config(self, tmp_path: Path) -> None:
        """Writing config to a temp file and reading back returns the same values."""
        set_config_value("runner", "pipelex")
        set_config_value("api_key", "secret-123")
        set_config_value("base_url", "https://custom.example.com")

        config = load_config()
        assert config["runner"] == "pipelex"
        assert config["api_key"] == "secret-123"
        assert config["base_url"] == "https://custom.example.com"

        # Verify the file actually exists on disk
        config_path = tmp_path / ".mthds" / "config"
        assert config_path.is_file()
        content = config_path.read_text(encoding="utf-8")
        assert "MTHDS_RUNNER=pipelex" in content
        assert "MTHDS_API_KEY=secret-123" in content
        assert "MTHDS_API_URL=https://custom.example.com" in content

    def test_env_override_file(self, mocker: MockerFixture) -> None:
        """Environment variables take precedence over values in the config file."""
        set_config_value("runner", "pipelex")

        # Verify file value
        entry_before = get_config_value("runner")
        assert entry_before.value == "pipelex"
        assert entry_before.source == ConfigSource.FILE

        # Set env var to override
        mocker.patch.dict("os.environ", {"MTHDS_RUNNER": "api"})

        entry_after = get_config_value("runner")
        assert entry_after.value == "api"
        assert entry_after.source == ConfigSource.ENV

    def test_missing_file_uses_defaults(self) -> None:
        """With no config file, default values are returned."""
        config = load_config()

        assert config["runner"] == "api"
        assert config["base_url"] == "http://localhost:8081"
        assert config["api_key"] == ""

    @pytest.mark.parametrize("key", ["runner", "base_url", "api_key"])
    def test_missing_file_source_is_default(self, key: str) -> None:
        """With no config file, source is DEFAULT."""
        entry = get_config_value(key)
        assert entry.source == ConfigSource.DEFAULT

    def test_overwrite_existing_value(self, tmp_path: Path) -> None:
        """Setting a key that already exists in the file overwrites the value."""
        set_config_value("runner", "pipelex")
        set_config_value("runner", "api")

        entry = get_config_value("runner")
        assert entry.value == "api"
        assert entry.source == ConfigSource.FILE

        config_path = tmp_path / ".mthds" / "config"
        content = config_path.read_text(encoding="utf-8")
        assert content.count("MTHDS_RUNNER=") == 1

    def test_file_content_is_dotenv_format(self, tmp_path: Path) -> None:
        """The config file uses KEY=VALUE format with newlines."""
        set_config_value("api_key", "my-key")
        set_config_value("runner", "pipelex")

        config_path = tmp_path / ".mthds" / "config"
        content = config_path.read_text(encoding="utf-8")
        lines = [line for line in content.strip().splitlines() if line.strip()]

        for line in lines:
            assert "=" in line, f"Line does not have KEY=VALUE format: {line}"

    def test_load_after_multiple_set_operations(self) -> None:
        """Multiple set operations followed by load returns all values correctly."""
        set_config_value("runner", "pipelex")
        set_config_value("api_key", "key-abc")
        set_config_value("base_url", "https://alt.api.com")

        config = load_config()
        assert config["runner"] == "pipelex"
        assert config["api_key"] == "key-abc"
        assert config["base_url"] == "https://alt.api.com"
