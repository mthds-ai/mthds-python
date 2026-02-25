from pathlib import Path

from pydantic import BaseModel

from mthds.package.discovery import MANIFEST_FILENAME
from mthds.package.exceptions import (
    AmbiguousPipeCodeError,
    DuplicateMethodNameError,
    MethodNotFoundError,
    PipeCodeNotFoundError,
)
from mthds.package.manifest.parser import parse_methods_toml
from mthds.package.manifest.schema import MethodsManifest

GLOBAL_METHODS_DIR = Path.home() / ".mthds" / "methods"
PROJECT_METHODS_DIR = Path(".mthds") / "methods"


class InstalledMethod(BaseModel):
    """An installed method discovered from the filesystem."""

    name: str
    path: Path
    manifest: MethodsManifest
    mthds_files: list[Path]


def discover_installed_methods(
    include_global: bool = True,
    include_project: bool = True,
) -> list[InstalledMethod]:
    """Scan ~/.mthds/methods/ and ./.mthds/methods/ for installed methods.

    For each subdirectory with a METHODS.toml:
    - Parse the manifest and get ``name`` from it
    - The directory name must match manifest.name
    - Collect all .mthds files recursively

    Args:
        include_global: Whether to scan the global methods directory
        include_project: Whether to scan the project-local methods directory

    Returns:
        A list of discovered installed methods
    """
    methods: list[InstalledMethod] = []
    dirs_to_scan: list[Path] = []

    if include_project:
        project_dir = PROJECT_METHODS_DIR.resolve()
        if project_dir.is_dir():
            dirs_to_scan.append(project_dir)

    if include_global:
        if GLOBAL_METHODS_DIR.is_dir():
            dirs_to_scan.append(GLOBAL_METHODS_DIR)

    for methods_dir in dirs_to_scan:
        for subdir in sorted(methods_dir.iterdir()):
            if not subdir.is_dir():
                continue
            manifest_path = subdir / MANIFEST_FILENAME
            if not manifest_path.is_file():
                continue

            content = manifest_path.read_text(encoding="utf-8")
            manifest = parse_methods_toml(content)

            name = manifest.name if manifest.name is not None else subdir.name

            mthds_files = sorted(subdir.rglob("*.mthds"))

            methods.append(
                InstalledMethod(
                    name=name,
                    path=subdir,
                    manifest=manifest,
                    mthds_files=mthds_files,
                )
            )

    return methods


def find_method_by_name(
    method_name: str,
    methods: list[InstalledMethod] | None = None,
) -> InstalledMethod:
    """Find a method by name.

    Args:
        method_name: The method name to search for
        methods: Pre-discovered methods list; if None, runs discovery

    Returns:
        The matching InstalledMethod

    Raises:
        MethodNotFoundError: If no method matches the given name
        DuplicateMethodNameError: If multiple methods share the same name
    """
    if methods is None:
        methods = discover_installed_methods()

    matches = [method for method in methods if method.name == method_name]

    if len(matches) == 0:
        msg = f"No installed method named '{method_name}' found."
        raise MethodNotFoundError(msg)
    if len(matches) > 1:
        locations = ", ".join(str(method.path) for method in matches)
        msg = f"Multiple methods named '{method_name}' found: {locations}"
        raise DuplicateMethodNameError(msg)

    return matches[0]


def get_all_exported_pipes(method: InstalledMethod) -> set[str]:
    """Collect all pipe codes from a method's exports (all domains).

    Args:
        method: The installed method to inspect

    Returns:
        A set of all pipe codes exported by the method
    """
    pipe_codes: set[str] = set()
    for domain_exports in method.manifest.exports.values():
        pipe_codes.update(domain_exports.pipes)
    return pipe_codes


def find_method_by_exported_pipe(
    pipe_code: str,
    methods: list[InstalledMethod] | None = None,
) -> InstalledMethod:
    """Find which installed method exports a given pipe code.

    Scans all methods' exports sections for matching pipe codes.

    Args:
        pipe_code: The pipe code to search for
        methods: Pre-discovered methods list; if None, runs discovery

    Returns:
        The installed method that exports the given pipe code

    Raises:
        PipeCodeNotFoundError: If the pipe code is not found in any method's exports
        AmbiguousPipeCodeError: If the pipe code is found in multiple methods
    """
    if methods is None:
        methods = discover_installed_methods()

    matches: list[InstalledMethod] = []
    for method in methods:
        exported_pipes = get_all_exported_pipes(method)
        if pipe_code in exported_pipes:
            matches.append(method)

    if len(matches) == 0:
        msg = f"Pipe code '{pipe_code}' not found in any installed method's exports."
        raise PipeCodeNotFoundError(msg)
    if len(matches) > 1:
        method_names = ", ".join(method.name for method in matches)
        msg = f"Pipe code '{pipe_code}' is exported by multiple methods: {method_names}"
        raise AmbiguousPipeCodeError(msg)

    return matches[0]
