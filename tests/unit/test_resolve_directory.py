"""Tests for resolve_directory helper."""

from pathlib import Path

import pytest
import typer
from pytest_mock import MockerFixture

from mthds.cli._console import resolve_directory  # noqa: PLC2701


class TestResolveDirectory:
    """Test the resolve_directory function from _console.py."""

    @pytest.fixture(autouse=True)
    def _suppress_console(self, mocker: MockerFixture) -> None:
        """Suppress Rich console output during tests."""
        mock_console = mocker.MagicMock()
        mocker.patch("mthds.cli._console.get_console", return_value=mock_console)

    def test_none_returns_cwd(self) -> None:
        """None input returns the resolved current working directory."""
        result = resolve_directory(None)
        assert result == Path.cwd().resolve()
        assert result.is_absolute()

    def test_valid_directory(self, tmp_path: Path) -> None:
        """A valid directory path returns its resolved absolute form."""
        result = resolve_directory(tmp_path)
        assert result == tmp_path.resolve()
        assert result.is_absolute()

    def test_nonexistent_path_raises_exit(self, tmp_path: Path) -> None:
        """A non-existent path raises typer.Exit."""
        nonexistent = tmp_path / "does_not_exist"
        with pytest.raises(typer.Exit):
            resolve_directory(nonexistent)

    def test_file_not_directory_raises_exit(self, tmp_path: Path) -> None:
        """A path that is a file (not a directory) raises typer.Exit."""
        file_path = tmp_path / "a_file.txt"
        file_path.write_text("content")
        with pytest.raises(typer.Exit):
            resolve_directory(file_path)

    def test_subdirectory(self, tmp_path: Path) -> None:
        """A nested subdirectory resolves correctly."""
        sub = tmp_path / "level1" / "level2"
        sub.mkdir(parents=True)
        result = resolve_directory(sub)
        assert result == sub.resolve()
