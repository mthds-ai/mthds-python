import pytest

from mthds.package.bundle_metadata import BundleMetadata
from mthds.package.manifest.schema import DomainExports, MethodsManifest
from mthds.package.visibility import PackageVisibilityChecker, check_visibility


class TestVisibility:
    """Tests for the mthds.package.visibility module."""

    # --- Helpers ---

    @staticmethod
    def _make_manifest(
        exports: dict[str, DomainExports] | None = None,
    ) -> MethodsManifest:
        return MethodsManifest(
            address="github.com/acme/pkg",
            version="1.0.0",
            description="test",
            exports=exports or {},
        )

    # --- No manifest (all public) ---

    def test_no_manifest_all_public(self):
        checker = PackageVisibilityChecker(manifest=None, bundle_metadatas=[])
        errors = checker.validate_all_pipe_references()
        assert errors == []

    # --- Same domain always allowed ---

    def test_same_domain_always_allowed(self):
        manifest = self._make_manifest()
        metadata = BundleMetadata(
            domain="scoring",
            pipe_references=[("scoring.compute_score", "pipe header")],
        )
        checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=[metadata])
        errors = checker.validate_all_pipe_references()
        assert errors == []

    # --- Exported pipe accessible ---

    def test_exported_pipe_accessible(self):
        manifest = self._make_manifest(
            exports={"scoring": DomainExports(pipes=["compute_score"])},
        )
        metadata = BundleMetadata(
            domain="legal",
            pipe_references=[("scoring.compute_score", "pipe header")],
        )
        checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=[metadata])
        errors = checker.validate_all_pipe_references()
        assert errors == []

    # --- Main pipe auto-exported ---

    def test_main_pipe_auto_exported(self):
        manifest = self._make_manifest(
            exports={"scoring": DomainExports(pipes=[])},
        )
        metadata_source = BundleMetadata(
            domain="legal",
            pipe_references=[("scoring.compute_score", "pipe header")],
        )
        metadata_scoring = BundleMetadata(
            domain="scoring",
            main_pipe="compute_score",
        )
        checker = PackageVisibilityChecker(
            manifest=manifest,
            bundle_metadatas=[metadata_source, metadata_scoring],
        )
        errors = checker.validate_all_pipe_references()
        assert errors == []

    # --- Unexported pipe blocked ---

    def test_unexported_pipe_blocked(self):
        manifest = self._make_manifest(
            exports={"scoring": DomainExports(pipes=["public_pipe"])},
        )
        metadata = BundleMetadata(
            domain="legal",
            pipe_references=[("scoring.private_pipe", "pipe header")],
        )
        checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=[metadata])
        errors = checker.validate_all_pipe_references()
        assert len(errors) == 1
        assert "private_pipe" in errors[0].message

    # --- validate_all_pipe_references mix ---

    def test_validate_all_pipe_references_mixed(self):
        manifest = self._make_manifest(
            exports={"scoring": DomainExports(pipes=["public_pipe"])},
        )
        metadata = BundleMetadata(
            domain="legal",
            pipe_references=[
                ("scoring.public_pipe", "ref1"),
                ("scoring.private_pipe", "ref2"),
            ],
        )
        checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=[metadata])
        errors = checker.validate_all_pipe_references()
        assert len(errors) == 1
        assert errors[0].pipe_ref == "scoring.private_pipe"

    # --- validate_cross_package_references ---

    def test_validate_cross_package_references_always_error(self):
        """Cross-package references are always flagged (dependencies removed from schema)."""
        manifest = self._make_manifest()
        metadata = BundleMetadata(
            domain="legal",
            pipe_references=[("my_dep->scoring.compute_score", "pipe header")],
        )
        checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=[metadata])
        errors = checker.validate_cross_package_references()
        assert len(errors) == 1
        assert "my_dep" in errors[0].message

    def test_validate_cross_package_references_unknown_alias(self):
        manifest = self._make_manifest()
        metadata = BundleMetadata(
            domain="legal",
            pipe_references=[("unknown_dep->scoring.compute_score", "pipe header")],
        )
        checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=[metadata])
        errors = checker.validate_cross_package_references()
        assert len(errors) == 1
        assert "unknown_dep" in errors[0].message

    # --- validate_reserved_domains ---

    @pytest.mark.parametrize("reserved_domain", ["native", "mthds", "pipelex"])
    def test_validate_reserved_domains(self, reserved_domain: str):
        manifest = self._make_manifest()
        domain = f"{reserved_domain}.something"
        metadata = BundleMetadata(domain=domain)
        checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=[metadata])
        errors = checker.validate_reserved_domains()
        assert len(errors) == 1
        assert reserved_domain in errors[0].message

    # --- check_visibility convenience ---

    def test_check_visibility_convenience_no_errors(self):
        manifest = self._make_manifest(
            exports={"scoring": DomainExports(pipes=["compute_score"])},
        )
        metadata = BundleMetadata(
            domain="scoring",
            pipe_references=[("scoring.compute_score", "pipe header")],
        )
        errors = check_visibility(manifest, [metadata])
        assert errors == []

    def test_check_visibility_convenience_with_errors(self):
        manifest = self._make_manifest(
            exports={"scoring": DomainExports(pipes=[])},
        )
        metadata = BundleMetadata(
            domain="legal",
            pipe_references=[("scoring.private_pipe", "pipe header")],
        )
        errors = check_visibility(manifest, [metadata])
        assert len(errors) == 1
