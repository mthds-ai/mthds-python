from rich.console import Console

_console: Console | None = None


def get_console() -> Console:
    """Return the shared Rich console instance for CLI output."""
    global _console  # noqa: PLW0603
    if _console is None:
        _console = Console(stderr=True)
    return _console
