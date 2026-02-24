"""Package visibility checking for cross-domain pipe references.

Enforces the MTHDS visibility rules:
- Pipes default to private.
- Only pipes in [exports] or declared as main_pipe are public.
- Same-domain references are always allowed.
- Cross-domain references must target exported or main_pipe pipes.
"""

import logging

from pydantic import BaseModel, ConfigDict

from mthds.package.bundle_metadata import BundleMetadata
from mthds.package.manifest.schema import RESERVED_DOMAINS, MethodsManifest, is_reserved_domain_path
from mthds.package.qualified_ref import QualifiedRef, QualifiedRefError

logger = logging.getLogger(__name__)


class VisibilityError(BaseModel):
    """A single visibility violation."""

    model_config = ConfigDict(frozen=True)

    pipe_ref: str
    source_domain: str
    target_domain: str
    context: str
    message: str


class PackageVisibilityChecker:
    """Checks cross-domain pipe visibility against a manifest's exports.

    If no manifest is provided, all pipes are considered public (backward compat).
    """

    def __init__(
        self,
        manifest: MethodsManifest | None,
        bundle_metadatas: list[BundleMetadata],
    ):
        self._manifest = manifest
        self._bundle_metadatas = bundle_metadatas

        # Build lookup: exported_pipes[domain_path] = set of pipe codes
        self._exported_pipes: dict[str, set[str]] = {}
        if manifest:
            for domain_export in manifest.exports:
                self._exported_pipes[domain_export.domain_path] = set(domain_export.pipes)

        # Build lookup: main_pipes[domain_path] = main_pipe code (auto-exported)
        self._main_pipes: dict[str, str] = {}
        for metadata in bundle_metadatas:
            if metadata.main_pipe:
                existing = self._main_pipes.get(metadata.domain)
                if existing and existing != metadata.main_pipe:
                    logger.warning(
                        "Conflicting main_pipe for domain '%s': '%s' vs '%s' — keeping first value",
                        metadata.domain,
                        existing,
                        metadata.main_pipe,
                    )
                else:
                    self._main_pipes[metadata.domain] = metadata.main_pipe

    def is_pipe_accessible_from(self, pipe_ref: QualifiedRef, source_domain: str) -> bool:
        """Check if a domain-qualified pipe ref is accessible from source_domain.

        Args:
            pipe_ref: The parsed pipe reference.
            source_domain: The domain making the reference.

        Returns:
            True if the pipe is accessible.
        """
        # No manifest -> all pipes public
        if self._manifest is None:
            return True

        # Bare ref -> always allowed (no domain check)
        if not pipe_ref.is_qualified:
            return True

        # Same-domain ref -> always allowed
        if pipe_ref.is_local_to(source_domain):
            return True

        target_domain = pipe_ref.domain_path
        assert target_domain is not None
        pipe_code = pipe_ref.local_code

        # Check if it's in exports
        exported = self._exported_pipes.get(target_domain, set())
        if pipe_code in exported:
            return True

        # Check if it's a main_pipe (auto-exported)
        main_pipe = self._main_pipes.get(target_domain)
        return bool(main_pipe and pipe_code == main_pipe)

    def validate_all_pipe_references(self) -> list[VisibilityError]:
        """Validate all cross-domain pipe refs across all bundles.

        Returns:
            List of VisibilityError for each violation found.
        """
        # No manifest -> no violations
        if self._manifest is None:
            return []

        errors: list[VisibilityError] = []

        for metadata in self._bundle_metadatas:
            for pipe_ref_str, context in metadata.pipe_references:
                # Try to parse as pipe ref
                try:
                    ref = QualifiedRef.parse_pipe_ref(pipe_ref_str)
                except QualifiedRefError:
                    continue

                if not self.is_pipe_accessible_from(ref, metadata.domain):
                    target_domain = ref.domain_path or ""
                    msg = (
                        f"Pipe '{pipe_ref_str}' referenced in {context} (domain '{metadata.domain}') "
                        f"is not exported by domain '{target_domain}'. "
                        f"Add it to [exports.{target_domain}] pipes in METHODS.toml."
                    )
                    errors.append(
                        VisibilityError(
                            pipe_ref=pipe_ref_str,
                            source_domain=metadata.domain,
                            target_domain=target_domain,
                            context=context,
                            message=msg,
                        )
                    )

        return errors

    def validate_cross_package_references(self) -> list[VisibilityError]:
        """Validate cross-package references (using '->' syntax).

        Checks that:
        - If a ref contains '->' and the alias IS in dependencies -> log info
        - If a ref contains '->' and the alias is NOT in dependencies -> error

        Returns:
            List of VisibilityError for unknown dependency aliases.
        """
        if self._manifest is None:
            return []

        # Build alias lookup from manifest dependencies
        known_aliases: set[str] = {dep.alias for dep in self._manifest.dependencies}

        errors: list[VisibilityError] = []

        for metadata in self._bundle_metadatas:
            for pipe_ref_str, context in metadata.pipe_references:
                if not QualifiedRef.has_cross_package_prefix(pipe_ref_str):
                    continue

                alias, _remainder = QualifiedRef.split_cross_package_ref(pipe_ref_str)

                if alias in known_aliases:
                    # Known alias -> informational (cross-package resolution is active)
                    logger.info(
                        "Cross-package reference '%s' in %s (domain '%s'): alias '%s' is a known dependency.",
                        pipe_ref_str,
                        context,
                        metadata.domain,
                        alias,
                    )
                else:
                    # Unknown alias -> error
                    msg = (
                        f"Cross-package reference '{pipe_ref_str}' in {context} "
                        f"(domain '{metadata.domain}'): alias '{alias}' is not declared "
                        "in [dependencies] of METHODS.toml."
                    )
                    errors.append(
                        VisibilityError(
                            pipe_ref=pipe_ref_str,
                            source_domain=metadata.domain,
                            target_domain=alias,
                            context=context,
                            message=msg,
                        )
                    )

        return errors

    def validate_reserved_domains(self) -> list[VisibilityError]:
        """Check that no bundle declares a domain starting with a reserved segment.

        Returns:
            List of VisibilityError for each bundle using a reserved domain.
        """
        errors: list[VisibilityError] = []

        for metadata in self._bundle_metadatas:
            if is_reserved_domain_path(metadata.domain):
                first_segment = metadata.domain.split(".")[0]
                msg = (
                    f"Bundle domain '{metadata.domain}' uses reserved domain '{first_segment}'. "
                    f"Reserved domains ({', '.join(sorted(RESERVED_DOMAINS))}) cannot be used in user packages."
                )
                errors.append(
                    VisibilityError(
                        pipe_ref="",
                        source_domain=metadata.domain,
                        target_domain=first_segment,
                        context="bundle domain declaration",
                        message=msg,
                    )
                )

        return errors


def check_visibility(
    manifest: MethodsManifest | None,
    bundle_metadatas: list[BundleMetadata],
) -> list[VisibilityError]:
    """Convenience function: check visibility for a set of bundle metadatas.

    Validates both intra-package cross-domain visibility and cross-package references.

    Args:
        manifest: The package manifest (None means all-public).
        bundle_metadatas: The bundle metadata objects to check.

    Returns:
        List of visibility errors.
    """
    checker = PackageVisibilityChecker(manifest=manifest, bundle_metadatas=bundle_metadatas)
    errors = checker.validate_reserved_domains()
    errors.extend(checker.validate_all_pipe_references())
    errors.extend(checker.validate_cross_package_references())
    return errors
