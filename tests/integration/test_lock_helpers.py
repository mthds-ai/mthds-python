import os
import textwrap
from pathlib import Path

import pytest
import typer
from pytest_mock import MockerFixture
from rich.console import Console

from mthds.cli.commands.package._lock_helpers import parse_manifest_or_exit, resolve_and_generate_lock, write_lock_file  # noqa: PLC2701
from mthds.package.exceptions import DependencyResolveError, LockFileError, TransitiveDependencyError
from mthds.package.lock_file import LOCK_FILENAME, LockedPackage, LockFile
from mthds.package.manifest.schema import MethodsManifest, PackageDependency

MINIMAL_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "test"
""")


def _quiet_console() -> Console:
    """Create a console that discards output."""
    return Console(file=open(os.devnull, "w", encoding="utf-8"))


class TestLockHelpers:
    """Tests for the mthds.cli.commands.package._lock_helpers module."""

    # --- parse_manifest_or_exit ---

    def test_parse_manifest_or_exit_no_file(self, tmp_path: Path):
        with pytest.raises(typer.Exit):
            parse_manifest_or_exit(_quiet_console(), tmp_path)

    def test_parse_manifest_or_exit_invalid(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text("[broken\ntoml")
        with pytest.raises(typer.Exit):
            parse_manifest_or_exit(_quiet_console(), tmp_path)

    def test_parse_manifest_or_exit_success(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(MINIMAL_TOML)
        result = parse_manifest_or_exit(_quiet_console(), tmp_path)
        assert result.address == "github.com/acme/widgets"

    # --- resolve_and_generate_lock ---

    def test_resolve_and_generate_lock_dependency_error(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.resolve_all_dependencies",
            side_effect=DependencyResolveError("resolution failed"),
        )
        manifest = MethodsManifest(
            address="github.com/acme/widgets",
            version="1.0.0",
            description="test",
            dependencies={"dep": PackageDependency(address="github.com/acme/dep", version="^1.0.0")},
        )
        with pytest.raises(typer.Exit):
            resolve_and_generate_lock(_quiet_console(), tmp_path, manifest)

    def test_resolve_and_generate_lock_transitive_error(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.resolve_all_dependencies",
            side_effect=TransitiveDependencyError("cycle detected"),
        )
        manifest = MethodsManifest(
            address="github.com/acme/widgets",
            version="1.0.0",
            description="test",
        )
        with pytest.raises(typer.Exit):
            resolve_and_generate_lock(_quiet_console(), tmp_path, manifest)

    def test_resolve_and_generate_lock_lockfile_error(self, tmp_path: Path, mocker: MockerFixture):
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.resolve_all_dependencies",
            return_value=[],
        )
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.generate_lock_file",
            side_effect=LockFileError("generation failed"),
        )
        manifest = MethodsManifest(
            address="github.com/acme/widgets",
            version="1.0.0",
            description="test",
        )
        with pytest.raises(typer.Exit):
            resolve_and_generate_lock(_quiet_console(), tmp_path, manifest)

    # --- write_lock_file ---

    def test_write_lock_file(self, tmp_path: Path):
        lock = LockFile(
            packages={
                "github.com/org/repo": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/org/repo",
                ),
            }
        )
        write_lock_file(_quiet_console(), tmp_path, lock, "lock content here")

        lock_path = tmp_path / LOCK_FILENAME
        assert lock_path.exists()
        assert lock_path.read_text() == "lock content here"
