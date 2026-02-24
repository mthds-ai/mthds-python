import textwrap
from pathlib import Path

import pytest
import typer
from pytest_mock import MockerFixture

from mthds.cli.commands.package.lock_cmd import do_lock
from mthds.package.lock_file import LOCK_FILENAME, LockedPackage, LockFile

MINIMAL_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "test"
""")

TOML_WITH_DEPS = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "test"

    [dependencies]
    dep = {address = "github.com/acme/dep", version = "^1.0.0"}
""")


class TestLockCmd:
    """Tests for the mthds.cli.commands.package.lock_cmd module."""

    def test_do_lock_no_manifest(self, tmp_path: Path):
        with pytest.raises(typer.Exit):
            do_lock(directory=str(tmp_path))

    def test_do_lock_no_deps(self, tmp_path: Path, mocker: MockerFixture):
        (tmp_path / "METHODS.toml").write_text(MINIMAL_TOML)

        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.resolve_all_dependencies",
            return_value=[],
        )
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.generate_lock_file",
            return_value=LockFile(),
        )

        do_lock(directory=str(tmp_path))

        lock_path = tmp_path / LOCK_FILENAME
        assert lock_path.exists()

    def test_do_lock_with_deps(self, tmp_path: Path, mocker: MockerFixture):
        (tmp_path / "METHODS.toml").write_text(TOML_WITH_DEPS)

        lock = LockFile(
            packages={
                "github.com/acme/dep": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/acme/dep",
                ),
            }
        )

        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.resolve_all_dependencies",
            return_value=[],
        )
        mocker.patch(
            "mthds.cli.commands.package._lock_helpers.generate_lock_file",
            return_value=lock,
        )

        do_lock(directory=str(tmp_path))

        lock_path = tmp_path / LOCK_FILENAME
        content = lock_path.read_text()
        assert "github.com/acme/dep" in content
