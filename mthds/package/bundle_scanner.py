"""Scan .mthds bundle files to extract domain and pipe information.

Used by downstream tools (e.g. pipelex) to auto-generate METHODS.toml
manifests from a collection of bundle files.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

from mthds._utils.toml_utils import TomlError, load_toml_from_path
from mthds.package.manifest.schema import DomainExports

logger = logging.getLogger(__name__)


def scan_bundles_for_domain_info(
    mthds_files: list[Path],
) -> tuple[dict[str, set[str]], dict[str, str], list[str]]:
    """Scan .mthds bundle files and extract domain/pipe metadata.

    Parses each file as TOML and collects:
    - Which pipe codes belong to each domain
    - Which domain has a main_pipe declared

    Args:
        mthds_files: List of paths to .mthds files to scan.

    Returns:
        A 3-tuple of:
        - domain_pipes: mapping domain -> set of pipe codes
        - domain_main_pipes: mapping domain -> main_pipe code
        - errors: list of human-readable error strings for files that
          could not be parsed
    """
    domain_pipes: dict[str, set[str]] = {}
    domain_main_pipes: dict[str, str] = {}
    errors: list[str] = []

    for file_path in mthds_files:
        try:
            data: dict[str, Any] = load_toml_from_path(str(file_path))
        except (TomlError, OSError) as exc:
            errors.append(f"{file_path}: {exc}")
            continue

        domain = data.get("domain")
        if not isinstance(domain, str) or not domain:
            errors.append(f"{file_path}: missing or invalid 'domain' field")
            continue

        # Collect pipe codes from [pipe.*] sections
        pipes_section = data.get("pipe")
        pipe_codes: set[str] = set(cast("dict[str, Any]", pipes_section).keys()) if isinstance(pipes_section, dict) else set()

        if domain in domain_pipes:
            domain_pipes[domain].update(pipe_codes)
        else:
            domain_pipes[domain] = pipe_codes

        # Collect main_pipe if declared
        main_pipe = data.get("main_pipe")
        if isinstance(main_pipe, str) and main_pipe:
            existing = domain_main_pipes.get(domain)
            if existing and existing != main_pipe:
                logger.warning(
                    "Conflicting main_pipe for domain '%s': '%s' vs '%s' — keeping first",
                    domain,
                    existing,
                    main_pipe,
                )
            else:
                domain_main_pipes[domain] = main_pipe

    return domain_pipes, domain_main_pipes, errors


def build_domain_exports_from_scan(
    domain_pipes: dict[str, set[str]],
    domain_main_pipes: dict[str, str],
) -> dict[str, DomainExports]:
    """Build DomainExports dict from scan results.

    Each domain gets an export entry with all its pipe codes.
    The main_pipe is included in the pipe list if not already present.

    Args:
        domain_pipes: mapping domain -> set of pipe codes
        domain_main_pipes: mapping domain -> main_pipe code

    Returns:
        Dict of domain_path -> DomainExports, sorted by domain path.
    """
    exports: dict[str, DomainExports] = {}

    for domain in sorted(domain_pipes.keys()):
        pipes = set(domain_pipes[domain])

        # Ensure main_pipe is in the exported pipe list
        main_pipe = domain_main_pipes.get(domain)
        if main_pipe:
            pipes.add(main_pipe)

        exports[domain] = DomainExports.model_construct(
            pipes=sorted(pipes),
        )

    return exports
