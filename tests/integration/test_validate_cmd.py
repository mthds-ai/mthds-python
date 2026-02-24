"""Integration tests for mthds.cli.commands.validate_cmd — do_validate with real temp files."""

import subprocess  # noqa: S404
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer
from pytest_mock import MockerFixture

from mthds.cli.commands.validate_cmd import do_validate

VALID_MANIFEST = """\
[package]
address = "test.example/my-pkg"
version = "1.0.0"
description = "Test package"
"""

INVALID_MANIFEST_BAD_TOML = """\
[package
address = "broken
"""

INVALID_MANIFEST_BAD_SCHEMA = """\
[package]
address = "no-dot-no-slash"
version = "not-semver"
description = "Bad"
"""


class TestValidateCmd:
    """Integration tests for do_validate() with real temp directories and TOML files."""

    def test_validate_valid_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A valid METHODS.toml is accepted without error."""
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(VALID_MANIFEST, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        # Should complete without raising
        do_validate()

    def test_validate_missing_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A directory without METHODS.toml raises typer.Exit(1)."""
        monkeypatch.chdir(tmp_path)

        with pytest.raises(typer.Exit) as exc_info:
            do_validate()

        assert exc_info.value.exit_code == 1

    def test_validate_invalid_manifest_bad_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid TOML syntax in METHODS.toml raises typer.Exit(1)."""
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(INVALID_MANIFEST_BAD_TOML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(typer.Exit) as exc_info:
            do_validate()

        assert exc_info.value.exit_code == 1

    def test_validate_invalid_manifest_bad_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Syntactically valid TOML but failing schema validation raises typer.Exit(1)."""
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(INVALID_MANIFEST_BAD_SCHEMA, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(typer.Exit) as exc_info:
            do_validate()

        assert exc_info.value.exit_code == 1

    def test_validate_with_pipelex_runner(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
        """With --runner pipelex, delegates to subprocess after manifest validation."""
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(VALID_MANIFEST, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        mocker.patch("mthds.cli.commands.validate_cmd.shutil.which", return_value="/usr/local/bin/pipelex")

        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_subprocess_run = mocker.patch("mthds.cli.commands.validate_cmd.subprocess.run", return_value=mock_result)

        do_validate(runner="pipelex")

        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "pipelex"
        assert cmd[1] == "validate"

    def test_validate_with_unknown_runner(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Providing an unknown runner name after a valid manifest raises typer.Exit(1)."""
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(VALID_MANIFEST, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(typer.Exit) as exc_info:
            do_validate(runner="nonexistent")

        assert exc_info.value.exit_code == 1

    def test_validate_with_api_runner_not_supported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Providing runner='api' after a valid manifest raises typer.Exit(1) with unsupported message."""
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(VALID_MANIFEST, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(typer.Exit) as exc_info:
            do_validate(runner="api")

        assert exc_info.value.exit_code == 1
