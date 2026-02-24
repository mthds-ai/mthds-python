from importlib.metadata import version

from rich.console import Console

_console: Console | None = None

_LOGO = (
    "                    __  __              __",
    "   ____ ___  ___  / /_/ /_  ____  ____/ /____",
    r"  / __ `__ \/ _ \/ __/ __ \/ __ \/ __  / ___/",
    " / / / / / /  __/ /_/ / / / /_/ / /_/ (__  )",
    r"/_/ /_/ /_/\___/\__/_/ /_/\____/\__,_/____/",
)


def get_version() -> str:
    """Return the installed package version."""
    try:
        return version("mthds")
    except Exception:
        return "0.0.0"


def get_console() -> Console:
    """Return the shared Rich console instance for CLI output."""
    global _console  # noqa: PLW0603
    if _console is None:
        _console = Console(stderr=True)
    return _console


def print_logo() -> None:
    """Print the methods ASCII logo to stderr."""
    console = get_console()
    console.print()
    for line in _LOGO:
        console.print(f"[white]{line}[/white]")
    console.print()
