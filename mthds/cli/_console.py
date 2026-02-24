from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

_console: Console | None = None


def get_console() -> Console:
    """Return the shared Rich console instance for CLI output."""
    global _console  # noqa: PLW0603
    if _console is None:
        _console = Console(stderr=True)
    return _console


def resolve_directory(directory: Path | None) -> Path:
    """Resolve the --directory option to an existing directory path.

    Args:
        directory: User-provided directory path, or None for current directory.

    Returns:
        Resolved absolute path to the directory.

    Raises:
        typer.Exit: If the path does not exist or is not a directory.
    """
    if directory is None:
        return Path.cwd()

    resolved = Path(directory).resolve()
    if not resolved.exists():
        console = get_console()
        console.print(f"[red]Directory not found: {escape(str(resolved))}[/red]")
        raise typer.Exit(code=1)
    if not resolved.is_dir():
        console = get_console()
        console.print(f"[red]Not a directory: {escape(str(resolved))}[/red]")
        raise typer.Exit(code=1)
    return resolved
