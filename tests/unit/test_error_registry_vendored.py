import ast
import hashlib
import importlib.util
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # the test runs this repository's own generator
import sys
from collections.abc import Callable
from typing import cast

import pytest

from mthds.protocol.problem.registry import CORE_CODE_SPECS, REGISTRY_VERSION, STATUS_READINGS
from mthds.protocol.protocol import CORE_ERROR_REGISTRY_VERSION
from tests.unit.test_data import VendoredRegistry


def _generator_literal() -> Callable[[str], str]:
    """The generator's `_literal`, loaded from its script, which is no importable package."""
    spec = importlib.util.spec_from_file_location("generate_error_registry", VendoredRegistry.GENERATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("Callable[[str], str]", module.__dict__["_literal"])


_LITERAL = _generator_literal()


class TestErrorRegistryVendored:
    def test_vendored_bytes_match_the_sidecar(self) -> None:
        """The vendored snapshot and schema are byte for byte the files the sidecar records, so a hand edit or a partial re-vendor fails here."""
        sidecar = VendoredRegistry.SIDECAR
        assert sidecar["source_repository"] == "mthds-ai/mthds"
        assert sidecar["source_directory"] == "docs/spec/openapi"
        assert len(sidecar["source_commit"]) == 40
        recorded = {name: hashlib.sha256((VendoredRegistry.DIRECTORY / name).read_bytes()).hexdigest() for name in sidecar["files"]}
        assert sidecar["files"] == recorded
        assert set(sidecar["files"]) == {"mthds-error-registry.json", "mthds-error-registry.schema.json"}

    def test_versions_agree(self) -> None:
        """The vendored snapshot, its sidecar, the generated module and the version the package declares name one registry."""
        assert VendoredRegistry.SNAPSHOT["version"] == CORE_ERROR_REGISTRY_VERSION
        assert VendoredRegistry.SIDECAR["registry_version"] == CORE_ERROR_REGISTRY_VERSION
        assert REGISTRY_VERSION == CORE_ERROR_REGISTRY_VERSION

    def test_generated_module_holds_every_code(self) -> None:
        """Every code of the snapshot has its entry in the generated module, and no other code does."""
        assert set(CORE_CODE_SPECS) == {entry["code"] for entry in VendoredRegistry.SNAPSHOT["codes"]}
        assert STATUS_READINGS

    @pytest.mark.parametrize(
        ("topic", "text"),
        [
            ("a short text", "The run failed."),
            (
                "a long text",
                "The runtime answered with the HTTP status {status} and a body that is not a problem document the client can read, again.",
            ),
            ("a double space where the text is cut", "a" * 100 + "  b"),
            ("a double space inside a chunk", "word " * 15 + " double " + "word " * 15),
            ("a leading space", " " + "word " * 30),
            ("trailing spaces", "word " * 30 + "   "),
            ("one word longer than a chunk", "x" * 250),
        ],
    )
    def test_a_long_literal_keeps_every_space(self, topic: str, text: str) -> None:
        """A text cut into an implicit concatenation reads back exactly, whatever spaces it holds where it is cut."""
        assert ast.literal_eval(_LITERAL(text)) == text, topic

    def test_regenerating_gives_no_diff(self) -> None:
        """Regenerating the module from the vendored snapshot writes exactly the committed module, offline."""
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [sys.executable, str(VendoredRegistry.GENERATOR_PATH), "--check"],
            capture_output=True,
            check=False,
            cwd=VendoredRegistry.REPO_ROOT,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
