from pathlib import Path

import pytest
import typer
from pytest_mock import MockerFixture

from mthds.cli.commands.package.install_cmd import do_install
from mthds.package.exceptions import DependencyResolveError, IntegrityError
from mthds.package.lock_file import LOCK_FILENAME, LockedPackage, LockFile, serialize_lock_file


class TestInstallCmd:
    """Tests for the mthds.cli.commands.package.install_cmd module."""

    @staticmethod
    def _write_lock(tmp_path: Path, lock: LockFile) -> None:
        lock_path = tmp_path / LOCK_FILENAME
        lock_path.write_text(serialize_lock_file(lock))

    def test_do_install_no_lock(self, tmp_path: Path):
        with pytest.raises(typer.Exit):
            do_install(directory=str(tmp_path))

    def test_do_install_empty_lock(self, tmp_path: Path):
        self._write_lock(tmp_path, LockFile())
        # Should not raise, just prints "Nothing to install"
        do_install(directory=str(tmp_path))

    def test_do_install_all_cached(self, tmp_path: Path, mocker: MockerFixture):
        lock = LockFile(
            packages={
                "github.com/acme/dep": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/acme/dep",
                ),
            }
        )
        self._write_lock(tmp_path, lock)

        mocker.patch("mthds.cli.commands.package.install_cmd.is_cached", return_value=True)
        mock_resolve = mocker.patch("mthds.cli.commands.package.install_cmd.resolve_remote_dependency")
        mocker.patch("mthds.cli.commands.package.install_cmd.verify_lock_file")

        do_install(directory=str(tmp_path))
        mock_resolve.assert_not_called()

    def test_do_install_fetch_missing(self, tmp_path: Path, mocker: MockerFixture):
        lock = LockFile(
            packages={
                "github.com/acme/dep": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/acme/dep",
                ),
            }
        )
        self._write_lock(tmp_path, lock)

        mocker.patch("mthds.cli.commands.package.install_cmd.is_cached", return_value=False)
        mock_resolve = mocker.patch("mthds.cli.commands.package.install_cmd.resolve_remote_dependency")
        mocker.patch("mthds.cli.commands.package.install_cmd.verify_lock_file")

        do_install(directory=str(tmp_path))
        mock_resolve.assert_called_once()

    def test_do_install_fetch_failure(self, tmp_path: Path, mocker: MockerFixture):
        lock = LockFile(
            packages={
                "github.com/acme/dep": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/acme/dep",
                ),
            }
        )
        self._write_lock(tmp_path, lock)

        mocker.patch("mthds.cli.commands.package.install_cmd.is_cached", return_value=False)
        mocker.patch(
            "mthds.cli.commands.package.install_cmd.resolve_remote_dependency",
            side_effect=DependencyResolveError("fetch failed"),
        )

        with pytest.raises(typer.Exit):
            do_install(directory=str(tmp_path))

    def test_do_install_integrity_failure(self, tmp_path: Path, mocker: MockerFixture):
        lock = LockFile(
            packages={
                "github.com/acme/dep": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/acme/dep",
                ),
            }
        )
        self._write_lock(tmp_path, lock)

        mocker.patch("mthds.cli.commands.package.install_cmd.is_cached", return_value=True)
        mocker.patch(
            "mthds.cli.commands.package.install_cmd.verify_lock_file",
            side_effect=IntegrityError("hash mismatch"),
        )

        with pytest.raises(typer.Exit):
            do_install(directory=str(tmp_path))
