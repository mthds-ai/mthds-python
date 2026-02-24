"""Tests for path resolution logic in do_validate."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.cli.commands.validate_cmd import do_validate


class _CapturedTarget:
    """Captures the target argument passed to _validate_with_runner."""

    value: str | None = None


FAKE_PACKAGE_ROOT = Path("/fake/package/root")


class TestDoValidateTargetResolution:
    """Test the target path resolution branch in do_validate (lines 147-150).

    When --directory is set, relative .mthds file paths must be resolved
    to absolute paths so the runner subprocess finds them. Pipe codes
    (dotted or simple) must pass through unchanged.
    """

    @pytest.fixture(autouse=True)
    def _patch_internals(self, mocker: MockerFixture) -> _CapturedTarget:
        """Patch helpers so do_validate only exercises path resolution."""
        mocker.patch(
            "mthds.cli.commands.validate_cmd.resolve_directory",
            return_value=FAKE_PACKAGE_ROOT,
        )
        mocker.patch(
            "mthds.cli.commands.validate_cmd._validate_manifest",
            return_value=True,
        )
        captured = _CapturedTarget()

        def _capture_runner(
            _runner: str,
            target: str | None,
            _validate_all: bool,
            _extra_args: list[str],
            package_root: Path | None = None,  # noqa: ARG001
        ) -> None:
            captured.value = target

        mocker.patch(
            "mthds.cli.commands.validate_cmd._validate_with_runner",
            side_effect=_capture_runner,
        )
        self._captured = captured
        return captured

    @pytest.mark.parametrize(
        ("target", "directory", "expected_suffix"),
        [
            pytest.param("my_pipe.mthds", Path("/some/dir"), "my_pipe.mthds", id="relative mthds file with directory"),
            pytest.param("org.my_pipe", Path("/some/dir"), "org.my_pipe", id="dotted pipe code with directory"),
            pytest.param("my_pipe", Path("/some/dir"), "my_pipe", id="simple pipe code with directory"),
            pytest.param("/abs/path/file.mthds", Path("/some/dir"), "/abs/path/file.mthds", id="absolute mthds path with directory"),
            pytest.param("my_pipe.mthds", None, "my_pipe.mthds", id="relative mthds path without directory"),
            pytest.param("sub/dir/file.mthds", Path("/some/dir"), "sub/dir/file.mthds", id="nested relative mthds path with directory"),
        ],
    )
    def test_target_resolution(
        self,
        target: str,
        directory: Path | None,
        expected_suffix: str,
    ) -> None:
        """Verify that target is resolved or passed through correctly."""
        do_validate(
            target=target,
            runner="pipelex",
            directory=directory,
        )
        result = self._captured.value
        assert result is not None

        if directory is not None and not Path(target).is_absolute() and Path(target).suffix == ".mthds":
            # Relative .mthds paths should become absolute
            assert Path(result).is_absolute(), f"Expected absolute path, got: {result}"
            assert result.endswith(expected_suffix), f"Expected to end with {expected_suffix}, got: {result}"
        else:
            # Pipe codes and already-absolute paths pass through unchanged
            assert result == expected_suffix, f"Expected {expected_suffix!r}, got: {result!r}"

    def test_none_target_passes_through(self) -> None:
        """When target is None, it stays None regardless of directory."""
        do_validate(
            target=None,
            runner="pipelex",
            directory=Path("/some/dir"),
        )
        assert self._captured.value is None
