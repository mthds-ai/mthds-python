from pathlib import Path

from mthds.cli._console import get_console, resolve_directory
from mthds.cli.commands._lock_helpers import parse_manifest_or_exit, resolve_and_generate_lock, write_lock_file


def do_lock(directory: Path | None = None) -> None:
    """Resolve dependencies and generate methods.lock.

    Args:
        directory: Package directory (defaults to current directory)
    """
    console = get_console()
    cwd = resolve_directory(directory)

    manifest = parse_manifest_or_exit(console, cwd)
    lock_file, lock_content = resolve_and_generate_lock(console, cwd, manifest)
    write_lock_file(console, cwd, lock_file, lock_content)
