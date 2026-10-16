import hashlib
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # the test runs this repository's own generator
import sys

from mthds.protocol.problem.registry import CORE_CODE_SPECS, REGISTRY_VERSION, STATUS_READINGS
from mthds.protocol.protocol import CORE_ERROR_REGISTRY_VERSION
from tests.unit.test_data import VendoredRegistry


class TestErrorRegistryVendored:
    def test_vendored_bytes_match_the_sidecar(self):
        """The vendored snapshot and schema are byte for byte the files the sidecar records, so a hand edit or a partial re-vendor fails here."""
        sidecar = VendoredRegistry.SIDECAR
        assert sidecar["source_repository"] == "mthds-ai/mthds"
        assert sidecar["source_directory"] == "docs/spec/openapi"
        assert len(sidecar["source_commit"]) == 40
        recorded = {name: hashlib.sha256((VendoredRegistry.DIRECTORY / name).read_bytes()).hexdigest() for name in sidecar["files"]}
        assert sidecar["files"] == recorded
        assert set(sidecar["files"]) == {"mthds-error-registry.json", "mthds-error-registry.schema.json"}

    def test_versions_agree(self):
        """The vendored snapshot, its sidecar, the generated module and the version the package declares name one registry."""
        assert VendoredRegistry.SNAPSHOT["version"] == CORE_ERROR_REGISTRY_VERSION
        assert VendoredRegistry.SIDECAR["registry_version"] == CORE_ERROR_REGISTRY_VERSION
        assert REGISTRY_VERSION == CORE_ERROR_REGISTRY_VERSION

    def test_generated_module_holds_every_code(self):
        """Every code of the snapshot has its entry in the generated module, and no other code does."""
        assert set(CORE_CODE_SPECS) == {entry["code"] for entry in VendoredRegistry.SNAPSHOT["codes"]}
        assert STATUS_READINGS

    def test_regenerating_gives_no_diff(self):
        """Regenerating the module from the vendored snapshot writes exactly the committed module, offline."""
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [sys.executable, str(VendoredRegistry.GENERATOR_PATH), "--check"],
            capture_output=True,
            check=False,
            cwd=VendoredRegistry.REPO_ROOT,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
