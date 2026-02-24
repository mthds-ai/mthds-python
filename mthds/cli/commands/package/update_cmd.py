from pathlib import Path

from rich.console import Console
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.cli.commands.package._lock_helpers import parse_manifest_or_exit, resolve_and_generate_lock, write_lock_file
from mthds.package.lock_file import LOCK_FILENAME, LockFile, LockFileError, parse_lock_file


def _display_lock_diff(console: Console, old_lock: LockFile, new_lock: LockFile) -> None:
    """Display differences between an old and new lock file.

    Args:
        console: Rich console for output.
        old_lock: The previous lock file.
        new_lock: The freshly generated lock file.
    """
    old_addresses = set(old_lock.packages)
    new_addresses = set(new_lock.packages)

    added = new_addresses - old_addresses
    removed = old_addresses - new_addresses
    common = old_addresses & new_addresses

    updated: list[str] = []
    for address in sorted(common):
        old_ver = old_lock.packages[address].version
        new_ver = new_lock.packages[address].version
        if old_ver != new_ver:
            updated.append(f"{address}: {old_ver} -> {new_ver}")

    if not added and not removed and not updated:
        console.print("[dim]No changes — lock file is up to date.[/dim]")
        return

    for address in sorted(added):
        version = new_lock.packages[address].version
        console.print(f"  [green]+ {escape(address)}@{escape(version)}[/green]")

    for address in sorted(removed):
        version = old_lock.packages[address].version
        console.print(f"  [red]- {escape(address)}@{escape(version)}[/red]")

    for line in updated:
        console.print(f"  [yellow]{escape(line)}[/yellow]")


def do_update(directory: str | None = None) -> None:
    """Re-resolve dependencies and update methods.lock.

    Args:
        directory: Target package directory (defaults to current directory)
    """
    console = get_console()
    cwd = Path(directory).resolve() if directory else Path.cwd()

    manifest = parse_manifest_or_exit(console, cwd)

    # Read existing lock for diff comparison
    lock_path = cwd / LOCK_FILENAME
    old_lock: LockFile | None = None
    if lock_path.exists():
        try:
            old_lock = parse_lock_file(lock_path.read_text(encoding="utf-8"))
        except LockFileError:
            pass  # Ignore unparseable old lock

    # Fresh resolve (ignoring existing lock)
    new_lock, lock_content = resolve_and_generate_lock(console, cwd, manifest)
    write_lock_file(console, cwd, new_lock, lock_content)

    # Display diff
    if old_lock is not None:
        _display_lock_diff(console, old_lock, new_lock)
    else:
        console.print("[dim]No previous lock file — created fresh.[/dim]")
