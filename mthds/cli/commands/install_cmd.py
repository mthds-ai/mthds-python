from pathlib import Path

import typer
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.packages.dependency_resolver import resolve_remote_dependency
from mthds.packages.exceptions import DependencyResolveError, IntegrityError
from mthds.packages.lock_file import LOCK_FILENAME, LockFileError, parse_lock_file, verify_lock_file
from mthds.packages.manifest import PackageDependency
from mthds.packages.package_cache import is_cached


def do_install() -> None:
    """Install dependencies from methods.lock."""
    console = get_console()
    cwd = Path.cwd()
    lock_path = cwd / LOCK_FILENAME

    if not lock_path.exists():
        console.print(f"[red]{LOCK_FILENAME} not found in current directory.[/red]")
        console.print("Run [bold]mthds lock[/bold] first to generate a lock file.")
        raise typer.Exit(code=1)

    lock_content = lock_path.read_text(encoding="utf-8")
    try:
        lock_file = parse_lock_file(lock_content)
    except LockFileError as exc:
        console.print(f"[red]Could not parse {LOCK_FILENAME}: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    if not lock_file.packages:
        console.print("[dim]Nothing to install — lock file is empty.[/dim]")
        return

    fetched_count = 0
    cached_count = 0

    for address, locked in lock_file.packages.items():
        if is_cached(address, locked.version):
            cached_count += 1
            continue

        # Fetch missing package by resolving with exact version constraint
        dep = PackageDependency(
            address=address,
            version=locked.version,
            alias=address.rsplit("/", maxsplit=1)[-1].replace("-", "_").replace(".", "_").lower(),
        )
        try:
            resolve_remote_dependency(dep)
        except DependencyResolveError as exc:
            console.print(f"[red]Failed to fetch '{escape(address)}@{escape(locked.version)}': {escape(exc.message)}[/red]")
            raise typer.Exit(code=1) from exc

        fetched_count += 1

    # Verify integrity
    try:
        verify_lock_file(lock_file)
    except IntegrityError as exc:
        console.print(f"[red]Integrity verification failed: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Installed {fetched_count} package(s), {cached_count} already cached.[/green]")
