"""Tests for mthds.config.credentials legacy config.json / .env.local migration."""

import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.config.credentials import load_credentials


class TestCredentialsMigration:
    """Tests the one-time migration from the legacy JS config.json / .env.local files."""

    @pytest.fixture(autouse=True)
    def _isolate_credentials(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Redirect every credentials path to a temp dir and reset the one-shot migration flag."""
        config_dir = tmp_path / ".mthds"
        config_dir.mkdir()

        mocker.patch("mthds.config.credentials.CONFIG_DIR", config_dir)
        mocker.patch("mthds.config.credentials.CREDENTIALS_PATH", config_dir / "credentials")
        mocker.patch("mthds.config.credentials._LEGACY_CONFIG_PATH", config_dir / "config.json")
        mocker.patch("mthds.config.credentials._LEGACY_ENV_LOCAL_PATH", config_dir / ".env.local")
        mocker.patch("mthds.config.credentials._migration_done", False)
        # Hermetic env: a real MTHDS_*/PIPELEX_* var must not shadow the migrated file values.
        mocker.patch.dict("os.environ", clear=True)

    def test_config_json_migrates_to_new_keys(self, tmp_path: Path) -> None:
        """A legacy config.json migrates into the credentials file using the new MTHDS_ keys."""
        config_dir = tmp_path / ".mthds"
        legacy_config = config_dir / "config.json"
        legacy_config.write_text(
            json.dumps(
                {
                    "runner": "api",
                    "apiUrl": "https://legacy.example.com",
                    "apiKey": "legacy-secret",
                    "telemetry": False,
                }
            ),
            encoding="utf-8",
        )

        creds = load_credentials()
        assert creds["api_url"] == "https://legacy.example.com"
        assert creds["api_key"] == "legacy-secret"
        assert creds["runner"] == "api"
        assert creds["telemetry"] == "1"

        # The migrated credentials file uses the new storage keys and the legacy file is gone.
        content = (config_dir / "credentials").read_text(encoding="utf-8")
        assert "MTHDS_API_URL=https://legacy.example.com" in content
        assert "MTHDS_API_KEY=legacy-secret" in content
        assert "PIPELEX_API_URL" not in content
        assert "PIPELEX_API_KEY" not in content
        assert not legacy_config.is_file()
