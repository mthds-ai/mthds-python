import subprocess  # noqa: S404
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from semantic_version import Version  # type: ignore[import-untyped]

from mthds.package.exceptions import VCSFetchError, VersionResolutionError
from mthds.package.vcs_resolver import (
    address_to_clone_url,
    clone_at_version,
    list_remote_version_tags,
    resolve_version_from_tags,
)


class TestVcsResolver:
    """Tests for the mthds.package.vcs_resolver module — all subprocess calls mocked."""

    # --- address_to_clone_url ---

    @pytest.mark.parametrize(
        ("address", "expected"),
        [
            ("github.com/org/repo", "https://github.com/org/repo.git"),
            ("github.com/org/repo.git", "https://github.com/org/repo.git"),
            ("gitlab.com/group/sub/proj", "https://gitlab.com/group/sub/proj.git"),
        ],
    )
    def test_address_to_clone_url(self, address: str, expected: str):
        assert address_to_clone_url(address) == expected

    # --- list_remote_version_tags ---

    def test_list_remote_version_tags_success(self, mocker: MockerFixture):
        """Parses valid ls-remote output, filtering ^{}, non-semver, and malformed lines."""
        ls_remote_output = (
            "abc123\trefs/tags/v1.0.0\ndef456\trefs/tags/v1.0.0^{}\nghi789\trefs/tags/v2.0.0\njkl012\trefs/tags/release-20240101\nmalformed-line\n"
        )
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=ls_remote_output, stderr=""),
        )
        result = list_remote_version_tags("https://github.com/org/repo.git")
        versions = [ver for ver, _tag in result]
        tags = [tag for _ver, tag in result]
        assert Version("1.0.0") in versions
        assert Version("2.0.0") in versions
        assert len(result) == 2
        assert "v1.0.0" in tags
        assert "v2.0.0" in tags

    def test_list_remote_version_tags_empty(self, mocker: MockerFixture):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        )
        result = list_remote_version_tags("https://github.com/org/repo.git")
        assert result == []

    def test_list_remote_version_tags_git_not_found(self, mocker: MockerFixture):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        )
        with pytest.raises(VCSFetchError, match="not installed"):
            list_remote_version_tags("https://github.com/org/repo.git")

    def test_list_remote_version_tags_called_process_error(self, mocker: MockerFixture):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git", stderr="access denied"),
        )
        with pytest.raises(VCSFetchError, match="Failed to list"):
            list_remote_version_tags("https://github.com/org/repo.git")

    def test_list_remote_version_tags_timeout(self, mocker: MockerFixture):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 60),
        )
        with pytest.raises(VCSFetchError, match="Timed out"):
            list_remote_version_tags("https://github.com/org/repo.git")

    # --- resolve_version_from_tags ---

    def test_resolve_version_from_tags_empty_tags(self):
        with pytest.raises(VersionResolutionError, match="No version tags available"):
            resolve_version_from_tags([], "^1.0.0")

    def test_resolve_version_from_tags_invalid_constraint(self):
        tags = [(Version("1.0.0"), "v1.0.0")]
        with pytest.raises(VersionResolutionError, match="Invalid version constraint"):
            resolve_version_from_tags(tags, ">>>invalid")

    def test_resolve_version_from_tags_valid_match(self):
        tags = [(Version("1.0.0"), "v1.0.0"), (Version("1.5.0"), "v1.5.0"), (Version("2.0.0"), "v2.0.0")]
        version, tag = resolve_version_from_tags(tags, "^1.0.0")
        assert version == Version("1.0.0")
        assert tag == "v1.0.0"

    def test_resolve_version_from_tags_no_match(self):
        tags = [(Version("2.0.0"), "v2.0.0"), (Version("3.0.0"), "v3.0.0")]
        with pytest.raises(VersionResolutionError, match="No version satisfying"):
            resolve_version_from_tags(tags, "^1.0.0")

    # --- clone_at_version ---

    def test_clone_at_version_success(self, mocker: MockerFixture, tmp_path: Path):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        )
        dest = tmp_path / "pkg"
        clone_at_version("https://github.com/org/repo.git", "v1.0.0", dest)

    def test_clone_at_version_git_not_found(self, mocker: MockerFixture, tmp_path: Path):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        )
        with pytest.raises(VCSFetchError, match="not installed"):
            clone_at_version("https://github.com/org/repo.git", "v1.0.0", tmp_path / "pkg")

    def test_clone_at_version_called_process_error(self, mocker: MockerFixture, tmp_path: Path):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git", stderr="clone failed"),
        )
        with pytest.raises(VCSFetchError, match="Failed to clone"):
            clone_at_version("https://github.com/org/repo.git", "v1.0.0", tmp_path / "pkg")

    def test_clone_at_version_timeout(self, mocker: MockerFixture, tmp_path: Path):
        mocker.patch(
            "mthds.package.vcs_resolver.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 120),
        )
        with pytest.raises(VCSFetchError, match="Timed out"):
            clone_at_version("https://github.com/org/repo.git", "v1.0.0", tmp_path / "pkg")
