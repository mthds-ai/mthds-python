from pathlib import Path

from mthds.cli._console import get_console
from mthds.cli.commands.package._lock_helpers import parse_manifest_or_exit, resolve_and_generate_lock, write_lock_file


def do_lock(directory: str | None = None) -> None:
    """Resolve dependencies and generate methods.lock.

    Args:
        directory: Target package directory (defaults to current directory)
    """
    console = get_console()
    cwd = Path(directory).resolve() if directory else Path.cwd()

    manifest = parse_manifest_or_exit(console, cwd)
    lock_file, lock_content = resolve_and_generate_lock(console, cwd, manifest)
    write_lock_file(console, cwd, lock_file, lock_content)
