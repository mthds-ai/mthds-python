import re
from pathlib import Path

import pytest

from mthds.version import PACKAGE_NAME, __version__

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+")


def _declared_version() -> str:
    """The `[project].version` declared in pyproject.toml.

    `^version` (MULTILINE) anchors at the line start, so it never matches the
    `python_version` / `target-version` tooling keys.
    """
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None, "no [project].version found in pyproject.toml"
    return match.group(1)


class TestVersion:
    def test_package_name_is_the_dist_name(self) -> None:
        assert PACKAGE_NAME == "mthds"

    def test_version_is_semver(self) -> None:
        assert _SEMVER.match(__version__), f"__version__ {__version__!r} is not a semver string"

    def test_version_matches_pyproject(self) -> None:
        """A stale install would misreport the package in every `User-Agent` it sends."""
        if __version__ == "0.0.0":
            pytest.skip("mthds distribution metadata not installed; run `make install`")
        assert __version__ == _declared_version()
