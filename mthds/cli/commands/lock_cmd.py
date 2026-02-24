from pathlib import Path

import typer
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.packages.dependency_resolver import resolve_all_dependencies
from mthds.packages.discovery import MANIFEST_FILENAME
from mthds.packages.exceptions import DependencyResolveError, ManifestError, TransitiveDependencyError
from mthds.packages.lock_file import LOCK_FILENAME, LockFileError, generate_lock_file, serialize_lock_file
from mthds.packages.manifest_parser import parse_methods_toml


def do_lock(directory: Path | None = None) -> None:
    """Resolve dependencies and generate methods.lock.

    Args:
        directory: Package directory (defaults to current directory)
    """
    console = get_console()
    cwd = Path(directory).resolve() if directory else Path.cwd()
    manifest_path = cwd / MANIFEST_FILENAME

    if not manifest_path.exists():
        console.print(f"[red]{MANIFEST_FILENAME} not found in current directory.[/red]")
        console.print("Run [bold]mthds init[/bold] first to create a manifest.")
        raise typer.Exit(code=1)

    content = manifest_path.read_text(encoding="utf-8")
    try:
        manifest = parse_methods_toml(content)
    except ManifestError as exc:
        console.print(f"[red]Could not parse {MANIFEST_FILENAME}: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    try:
        resolved = resolve_all_dependencies(manifest, cwd)
    except (DependencyResolveError, TransitiveDependencyError) as exc:
        console.print(f"[red]Dependency resolution failed: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    try:
        lock = generate_lock_file(manifest, resolved)
    except LockFileError as exc:
        console.print(f"[red]Lock file generation failed: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    lock_content = serialize_lock_file(lock)
    lock_path = cwd / LOCK_FILENAME
    lock_path.write_text(lock_content, encoding="utf-8")

    pkg_count = len(lock.packages)
    console.print(f"[green]Wrote {LOCK_FILENAME} with {pkg_count} package(s).[/green]")
