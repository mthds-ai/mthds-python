import textwrap
from io import StringIO
from pathlib import Path

import pytest
import typer
from pytest_mock import MockerFixture
from rich.console import Console

from mthds.cli.commands.package.update_cmd import _display_lock_diff, do_update  # noqa: PLC2701
from mthds.package.lock_file import LOCK_FILENAME, LockedPackage, LockFile

MINIMAL_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "test"
""")


class TestUpdateCmd:
    """Tests for the mthds.cli.commands.package.update_cmd module."""

    # --- _display_lock_diff ---

    def test_display_lock_diff_identical(self):
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=200)
        lock = LockFile(
            packages={
                "github.com/org/repo": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/org/repo",
                ),
            }
        )
        _display_lock_diff(console, lock, lock)
        text = output.getvalue()
        assert "no changes" in text.lower() or "No changes" in text

    def test_display_lock_diff_added(self):
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=200)
        old_lock = LockFile()
        new_lock = LockFile(
            packages={
                "github.com/org/new": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/org/new",
                ),
            }
        )
        _display_lock_diff(console, old_lock, new_lock)
        text = output.getvalue()
        assert "+" in text
        assert "github.com/org/new" in text

    def test_display_lock_diff_removed(self):
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=200)
        old_lock = LockFile(
            packages={
                "github.com/org/old": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/org/old",
                ),
            }
        )
        new_lock = LockFile()
        _display_lock_diff(console, old_lock, new_lock)
        text = output.getvalue()
        assert "-" in text
        assert "github.com/org/old" in text

    def test_display_lock_diff_updated(self):
        output = StringIO()
        console = Console(file=output, no_color=True, width=200)
        old_lock = LockFile(
            packages={
                "github.com/org/repo": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/org/repo",
                ),
            }
        )
        new_lock = LockFile(
            packages={
                "github.com/org/repo": LockedPackage(
                    version="2.0.0",
                    hash="sha256:" + "b" * 64,
                    source="https://github.com/org/repo",
                ),
            }
        )
        _display_lock_diff(console, old_lock, new_lock)
        text = output.getvalue()
        assert "1.0.0" in text
        assert "2.0.0" in text

    # --- do_update ---

    def test_do_update_no_manifest(self, tmp_path: Path):
        with pytest.raises(typer.Exit):
            do_update(directory=str(tmp_path))

    def test_do_update_no_existing_lock(self, tmp_path: Path, mocker: MockerFixture):
        (tmp_path / "METHODS.toml").write_text(MINIMAL_TOML)

        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.resolve_all_dependencies",
            return_value=[],
        )
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.generate_lock_file",
            return_value=LockFile(),
        )

        do_update(directory=str(tmp_path))

        lock_path = tmp_path / LOCK_FILENAME
        assert lock_path.exists()

    def test_do_update_corrupt_old_lock(self, tmp_path: Path, mocker: MockerFixture):
        """Corrupt old lock is treated as no old lock (no diff shown)."""
        (tmp_path / "METHODS.toml").write_text(MINIMAL_TOML)
        (tmp_path / LOCK_FILENAME).write_text("[broken\ntoml")

        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.resolve_all_dependencies",
            return_value=[],
        )
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.generate_lock_file",
            return_value=LockFile(),
        )

        # Should not raise — corrupt lock is ignored
        do_update(directory=str(tmp_path))
