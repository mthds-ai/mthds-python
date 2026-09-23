"""Package version, derived from the installed distribution metadata.

`__version__` is read from the installed `mthds` distribution (via `importlib.metadata`),
so there is no hardcoded constant to drift from the `pyproject.toml` source of truth.
`tests/unit/test_version.py` asserts the resolved value matches the version declared in
`pyproject.toml`, catching a stale install (an editable tree whose metadata was not
refreshed after a bump).

This is the **package release** version. It is not `MTHDS_STANDARD_VERSION` nor
`PROTOCOL_VERSION`, which are copies of standard cuts (see `docs/versioning.md`).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

#: The PyPI distribution name (the import package is also `mthds`).
PACKAGE_NAME = "mthds"

try:
    __version__: str = version(PACKAGE_NAME)
except PackageNotFoundError:
    # Running from a source tree that was never installed (no dist metadata).
    __version__ = "0.0.0"
