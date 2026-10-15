"""Fixtures for the method-tree tests: the host's capabilities, and the materialization of a corpus tree case.

Materializing follows the corpus's consumption contract (`conformance/specs/mthds-method-tree.md`,
"Materializing a tree case"): probe what the host's file system allows in the directory the
workspaces live in, then write each entry at its path, each name exactly as given, a decomposed
name staying decomposed, a symbolic link's target written as is and never resolved.
"""

import base64
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.unit.method_tree.test_data import HostCapability

COMPOSED_E_ACUTE = "é"
DECOMPOSED_E_ACUTE = "é"


def _probe_capabilities(directory: Path) -> frozenset[str]:
    capabilities: set[str] = set()
    probe_directory = directory / "capability-probe"
    probe_directory.mkdir()
    (probe_directory / "probe").write_bytes(b"")
    if not (probe_directory / "PROBE").exists():
        capabilities.add(HostCapability.CASE_SENSITIVE_NAMES)
    (probe_directory / f"caf{COMPOSED_E_ACUTE}").write_bytes(b"")
    if not (probe_directory / f"caf{DECOMPOSED_E_ACUTE}").exists():
        capabilities.add(HostCapability.NORMALIZATION_SENSITIVE_NAMES)
    try:
        Path(probe_directory / "link").symlink_to("probe")
        capabilities.add(HostCapability.SYMBOLIC_LINKS)
    except (OSError, NotImplementedError):
        pass
    try:
        os.mkfifo(probe_directory / "pipe")
        capabilities.add(HostCapability.NAMED_PIPES)
    except (OSError, AttributeError):
        pass
    return frozenset(capabilities)


@pytest.fixture(scope="session")
def host_capabilities(tmp_path_factory: pytest.TempPathFactory) -> frozenset[str]:
    """What the file system holding the test workspaces allows, probed where the workspaces live."""
    return _probe_capabilities(tmp_path_factory.getbasetemp())


def _write_entry(workspace: Path, *, entry: dict[str, Any]) -> None:
    location = workspace.joinpath(*entry["path"].split("/"))
    location.parent.mkdir(parents=True, exist_ok=True)
    match entry["type"]:
        case "file":
            data = base64.b64decode(entry["base64"]) if "base64" in entry else entry["text"].encode("utf-8")
            location.write_bytes(data)
        case "directory":
            location.mkdir(parents=True, exist_ok=True)
        case "symlink":
            Path(location).symlink_to(entry["target"])
        case "fifo":
            os.mkfifo(location)
        case unknown:
            msg = f"unknown entry type {unknown!r} in the corpus"
            raise ValueError(msg)


@pytest.fixture
def materialize_tree_case(tmp_path: Path, host_capabilities: frozenset[str]) -> Callable[[dict[str, Any]], Path]:
    """Write a tree case's workspace in a fresh directory and return the path to hand over, skipping a case the host cannot hold."""

    def materialize(case: dict[str, Any]) -> Path:
        missing = sorted(set(case["requires"]) - host_capabilities)
        if missing:
            pytest.skip(f"this host's file system lacks {', '.join(missing)}")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        for entry in case["entries"]:
            _write_entry(workspace, entry=entry)
        handed_over: str = case["handed_over"]
        return workspace if handed_over == "." else workspace.joinpath(*handed_over.split("/"))

    return materialize
