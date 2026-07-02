"""Tests for mthds.config — load, get, set, resolve_key."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.config import (
    ConfigSource,
    get_config_value,
    load_config,
    resolve_key,
    set_config_value,
)


class TestConfig:
    """Tests for the config module public API."""

    @pytest.fixture(autouse=True)
    def _isolate_config(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Redirect config I/O to a temporary directory."""
        config_dir = tmp_path / ".mthds"
        config_dir.mkdir()
        config_path = config_dir / "config"

        mocker.patch("mthds.config.CONFIG_DIR", config_dir)
        mocker.patch("mthds.config.CONFIG_PATH", config_path)
        # Hermetic env: a real MTHDS_* var on the dev/CI machine must not leak in.
        # Tests that need env vars layer their own mocker.patch.dict on top of this clean slate.
        mocker.patch.dict("os.environ", clear=True)

    # ── resolve_key ──────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("cli_key", "expected"),
        [
            ("runner", "runner"),
            ("base-url", "base_url"),
            ("api-key", "api_key"),
        ],
    )
    def test_resolve_key_valid(self, cli_key: str, expected: str) -> None:
        """Known CLI flag names resolve to the correct internal key."""
        assert resolve_key(cli_key) == expected

    def test_resolve_key_unknown_returns_none(self) -> None:
        """An unknown CLI flag returns None."""
        assert resolve_key("nonexistent-key") is None

    # ── load_config: defaults / file / env ───────────────────────

    def test_load_config_returns_defaults_when_no_file(self) -> None:
        """With no config file, defaults are returned."""
        config = load_config()
        assert config["runner"] == "api"
        assert config["base_url"] == "http://localhost:8081"
        assert config["api_key"] == ""

    def test_load_config_reads_file(self, tmp_path: Path) -> None:
        """Values written to the config file override defaults."""
        config_path = tmp_path / ".mthds" / "config"
        config_path.write_text("MTHDS_RUNNER=pipelex\nMTHDS_API_KEY=my-secret\n", encoding="utf-8")

        config = load_config()
        assert config["runner"] == "pipelex"
        assert config["api_key"] == "my-secret"
        # Unchanged keys still return defaults
        assert config["base_url"] == "http://localhost:8081"

    def test_load_config_ignores_unknown_js_keys(self, tmp_path: Path) -> None:
        """JS-only keys (DISABLE_TELEMETRY, MTHDS_AUTO_UPGRADE) in the shared file are harmlessly ignored."""
        config_path = tmp_path / ".mthds" / "config"
        config_path.write_text(
            "MTHDS_RUNNER=pipelex\nDISABLE_TELEMETRY=1\nMTHDS_AUTO_UPGRADE=1\n",
            encoding="utf-8",
        )

        config = load_config()
        assert config["runner"] == "pipelex"
        assert "telemetry" not in config
        assert "DISABLE_TELEMETRY" not in config

    def test_load_config_env_overrides_file(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Environment variables take precedence over file values."""
        config_path = tmp_path / ".mthds" / "config"
        config_path.write_text("MTHDS_RUNNER=pipelex\n", encoding="utf-8")

        mocker.patch.dict("os.environ", {"MTHDS_RUNNER": "api"})

        config = load_config()
        assert config["runner"] == "api"

    def test_load_config_env_overrides_defaults(self, mocker: MockerFixture) -> None:
        """Environment variables take precedence over defaults (no file)."""
        mocker.patch.dict("os.environ", {"MTHDS_API_KEY": "env-key-value"})

        config = load_config()
        assert config["api_key"] == "env-key-value"

    # ── get_config_value ─────────────────────────────────────────

    def test_get_config_value_default_source(self) -> None:
        """When no file or env var exists, source is DEFAULT."""
        entry = get_config_value("runner")
        assert entry.value == "api"
        assert entry.source == ConfigSource.DEFAULT
        assert entry.key == "runner"
        assert entry.cli_key == "runner"

    def test_get_config_value_file_source(self, tmp_path: Path) -> None:
        """When value comes from file, source is FILE."""
        config_path = tmp_path / ".mthds" / "config"
        config_path.write_text("MTHDS_API_KEY=file-key\n", encoding="utf-8")

        entry = get_config_value("api_key")
        assert entry.value == "file-key"
        assert entry.source == ConfigSource.FILE
        assert entry.cli_key == "api-key"

    def test_get_config_value_env_source(self, mocker: MockerFixture) -> None:
        """When value comes from env, source is ENV and it wins over file."""
        mocker.patch.dict("os.environ", {"MTHDS_BASE_URL": "https://custom.url"})

        entry = get_config_value("base_url")
        assert entry.value == "https://custom.url"
        assert entry.source == ConfigSource.ENV
        assert entry.cli_key == "base-url"

    # ── set_config_value ─────────────────────────────────────────

    def test_set_config_value_creates_file(self, tmp_path: Path) -> None:
        """Setting a value creates the config file with the entry."""
        set_config_value("runner", "pipelex")

        config_path = tmp_path / ".mthds" / "config"
        content = config_path.read_text(encoding="utf-8")
        assert "MTHDS_RUNNER=pipelex" in content

    def test_set_config_value_uses_new_key(self, tmp_path: Path) -> None:
        """Setting base_url / api_key writes the new MTHDS_ storage keys."""
        set_config_value("base_url", "https://alt.api.com")
        set_config_value("api_key", "fresh-key")

        config_path = tmp_path / ".mthds" / "config"
        content = config_path.read_text(encoding="utf-8")
        assert "MTHDS_BASE_URL=https://alt.api.com" in content
        assert "MTHDS_API_KEY=fresh-key" in content

    def test_set_config_value_preserves_other_keys(self, tmp_path: Path) -> None:
        """Setting one key does not remove other keys from the file."""
        config_path = tmp_path / ".mthds" / "config"
        config_path.write_text("MTHDS_API_KEY=existing\n", encoding="utf-8")

        set_config_value("runner", "pipelex")

        content = config_path.read_text(encoding="utf-8")
        assert "MTHDS_API_KEY=existing" in content
        assert "MTHDS_RUNNER=pipelex" in content

    def test_set_then_get_round_trip(self) -> None:
        """A value set via set_config_value is returned by get_config_value."""
        set_config_value("api_key", "round-trip-key")

        entry = get_config_value("api_key")
        assert entry.value == "round-trip-key"
        assert entry.source == ConfigSource.FILE

    # ── config file parsing edge cases ───────────────────────────

    def test_load_config_ignores_comments_and_blanks(self, tmp_path: Path) -> None:
        """Comments and blank lines in the config file are ignored."""
        config_path = tmp_path / ".mthds" / "config"
        config_path.write_text(
            "# This is a comment\n\nMTHDS_RUNNER=pipelex\n\n# Another comment\n",
            encoding="utf-8",
        )

        config = load_config()
        assert config["runner"] == "pipelex"
