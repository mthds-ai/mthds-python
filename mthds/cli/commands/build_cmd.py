"""Build commands for the MTHDS CLI.

Build operations delegate to the pipelex CLI subprocess. The API runner
does not yet support build operations.
"""

import shutil
from pathlib import Path

import typer
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.runners.pipelex_runner import PipelexRunnerError, run_subprocess
from mthds.runners.types import RunnerType


def _library_args(directory: str | None) -> list[str]:
    """Build -L arguments for pipelex commands.

    Args:
        directory: Target package directory or None.

    Returns:
        List of CLI arguments (e.g. ["-L", "/abs/path"]) or empty list.
    """
    if directory:
        return ["-L", str(Path(directory).resolve())]
    return []


def _resolve_runner(runner: str | None) -> RunnerType:
    """Resolve a runner string to a RunnerType, defaulting to pipelex for build.

    Args:
        runner: Runner name or None (defaults to pipelex for build ops).

    Returns:
        RunnerType.

    Raises:
        typer.Exit: If the runner name is unknown or unsupported.
    """
    if runner is None:
        if shutil.which("pipelex") is not None:
            return RunnerType.PIPELEX
        console = get_console()
        console.print("[yellow]Build commands require the pipelex runner. Install it with: mthds setup runner pipelex[/yellow]")
        raise typer.Exit(code=1)

    try:
        resolved = RunnerType(runner)
    except ValueError:
        console = get_console()
        console.print(f"[red]Unknown runner: '{escape(runner)}'. Use 'pipelex' or 'api'.[/red]")
        raise typer.Exit(code=1) from None

    match resolved:
        case RunnerType.PIPELEX:
            return resolved
        case RunnerType.API:
            console = get_console()
            console.print("[yellow]Build commands are not yet supported via the API runner. Use --runner pipelex.[/yellow]")
            raise typer.Exit(code=1)


def do_build_pipe(brief: str, runner: str | None = None, directory: str | None = None) -> None:
    """Build a pipe from a brief description.

    Args:
        brief: A brief description of the pipe to build.
        runner: Runner to use or None for auto-detect.
        directory: Target package directory (defaults to current directory).
    """
    _resolve_runner(runner)
    console = get_console()
    cmd = ["pipelex", *_library_args(directory), "build", "pipe", brief]
    console.print(f"[dim]Delegating to: {' '.join(escape(arg) for arg in cmd)}[/dim]")
    try:
        run_subprocess(cmd)
    except PipelexRunnerError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


def do_build_runner(target: str, pipe_code: str | None = None, runner: str | None = None, directory: str | None = None) -> None:
    """Generate runner code for a pipe.

    Args:
        target: .mthds bundle file.
        pipe_code: Pipe code to generate runner for.
        runner: Runner to use or None for auto-detect.
        directory: Target package directory (defaults to current directory).
    """
    _resolve_runner(runner)
    console = get_console()
    cmd: list[str] = ["pipelex", *_library_args(directory), "build", "runner", target]
    if pipe_code:
        cmd.extend(["--pipe", pipe_code])
    console.print(f"[dim]Delegating to: {' '.join(escape(arg) for arg in cmd)}[/dim]")
    try:
        run_subprocess(cmd)
    except PipelexRunnerError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


def do_build_inputs(target: str, pipe_code: str, runner: str | None = None, directory: str | None = None) -> None:
    """Build inputs for a pipe.

    Args:
        target: .mthds bundle file.
        pipe_code: The pipe code to build inputs for.
        runner: Runner to use or None for auto-detect.
        directory: Target package directory (defaults to current directory).
    """
    _resolve_runner(runner)
    console = get_console()
    cmd = ["pipelex", *_library_args(directory), "build", "inputs", target, "--pipe", pipe_code]
    console.print(f"[dim]Delegating to: {' '.join(escape(arg) for arg in cmd)}[/dim]")
    try:
        run_subprocess(cmd)
    except PipelexRunnerError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


def do_build_output(target: str, pipe_code: str, fmt: str = "schema", runner: str | None = None, directory: str | None = None) -> None:
    """Build output configuration for a pipe.

    Args:
        target: .mthds bundle file.
        pipe_code: The pipe code to build output for.
        fmt: The output format.
        runner: Runner to use or None for auto-detect.
        directory: Target package directory (defaults to current directory).
    """
    _resolve_runner(runner)
    console = get_console()
    cmd = ["pipelex", *_library_args(directory), "build", "output", target, "--pipe", pipe_code, "--format", fmt]
    console.print(f"[dim]Delegating to: {' '.join(escape(arg) for arg in cmd)}[/dim]")
    try:
        run_subprocess(cmd)
    except PipelexRunnerError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
