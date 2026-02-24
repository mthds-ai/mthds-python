"""Shared helpers for lock and update commands."""

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from mthds.package.dependency_resolver import resolve_all_dependencies
from mthds.package.discovery import MANIFEST_FILENAME
from mthds.package.exceptions import DependencyResolveError, ManifestError, TransitiveDependencyError
from mthds.package.lock_file import LOCK_FILENAME, LockFile, LockFileError, generate_lock_file, serialize_lock_file
from mthds.package.manifest.parser import parse_methods_toml
from mthds.package.manifest.schema import MethodsManifest


def parse_manifest_or_exit(console: Console, cwd: Path) -> MethodsManifest:
    """Parse the METHODS.toml in cwd, or exit with an error message.

    Args:
        console: Rich console for output.
        cwd: The working directory containing METHODS.toml.

    Returns:
        The parsed manifest.
    """
    manifest_path = cwd / MANIFEST_FILENAME

    if not manifest_path.exists():
        console.print(f"[red]{MANIFEST_FILENAME} not found in current directory.[/red]")
        console.print("Run [bold]mthds init[/bold] first to create a manifest.")
        raise typer.Exit(code=1)

    content = manifest_path.read_text(encoding="utf-8")
    try:
        return parse_methods_toml(content)
    except ManifestError as exc:
        console.print(f"[red]Could not parse {MANIFEST_FILENAME}: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc


def resolve_and_generate_lock(console: Console, cwd: Path, manifest: MethodsManifest) -> tuple[LockFile, str]:
    """Resolve dependencies and generate a lock file.

    Args:
        console: Rich console for output.
        cwd: The working directory (package root).
        manifest: The parsed package manifest.

    Returns:
        Tuple of (lock_file, serialized_lock_content).
    """
    try:
        resolved = resolve_all_dependencies(manifest, cwd)
    except (DependencyResolveError, TransitiveDependencyError) as exc:
        console.print(f"[red]Dependency resolution failed: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    try:
        lock_file = generate_lock_file(manifest, resolved)
    except LockFileError as exc:
        console.print(f"[red]Lock file generation failed: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    lock_content = serialize_lock_file(lock_file)
    return lock_file, lock_content


def write_lock_file(console: Console, cwd: Path, lock_file: LockFile, lock_content: str) -> None:
    """Write the lock file and print a summary.

    Args:
        console: Rich console for output.
        cwd: The working directory.
        lock_file: The lock file model (for counting packages).
        lock_content: The serialized TOML content.
    """
    lock_path = cwd / LOCK_FILENAME
    lock_path.write_text(lock_content, encoding="utf-8")

    pkg_count = len(lock_file.packages)
    console.print(f"[green]Wrote {LOCK_FILENAME} with {pkg_count} package(s).[/green]")
