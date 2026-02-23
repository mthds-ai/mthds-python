import typer

from mthds.cli._console import get_console


def do_publish(tag: bool = False) -> None:  # noqa: ARG001
    """Publish is not yet implemented.

    Args:
        tag: Reserved for future use (create git tag on success).
    """
    console = get_console()
    console.print("[yellow]Publish is not yet implemented.[/yellow]")
    raise typer.Exit(code=0)
