"""Setup commands for the MTHDS CLI.

Provides runner availability checking and installation guidance.
"""

import shutil

from rich.markup import escape

from mthds.cli._console import get_console


def do_setup_runner(name: str) -> None:
    """Check if a runner is available and print installation instructions.

    Args:
        name: The runner name to check (e.g. "pipelex").
    """
    console = get_console()

    match name:
        case "pipelex":
            if shutil.which("pipelex") is not None:
                console.print(f"[green]Runner '{escape(name)}' is available on PATH.[/green]")
            else:
                console.print(f"[yellow]Runner '{escape(name)}' is not installed.[/yellow]")
                console.print("[dim]Install pipelex: curl -sSL https://pipelex.com/install.sh | sh[/dim]")
        case "api":
            console.print("[green]Runner 'api' is always available (built-in).[/green]")
        case _:
            console.print(f"[red]Unknown runner: '{escape(name)}'[/red]")
            console.print("[dim]Available runners: pipelex, api[/dim]")
