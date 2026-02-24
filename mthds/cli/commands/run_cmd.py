"""Runner delegation for 'mthds run'.

Delegates execution to a runner via the RunnerProtocol.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import typer
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.runners.pipelex_runner import PipelexRunnerError
from mthds.runners.registry import create_runner
from mthds.runners.types import RunnerType


def _parse_inputs_json(raw_json: str) -> dict[str, Any]:
    """Parse a JSON string into a dict for pipeline inputs.

    Args:
        raw_json: JSON string to parse.

    Returns:
        A dict mapping string keys to values suitable for pipeline inputs.

    Raises:
        typer.Exit: If the JSON is invalid or not a flat object.
    """
    console = get_console()
    try:
        parsed: object = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON inputs: {escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc

    if not isinstance(parsed, dict):
        console.print("[red]Inputs JSON must be a flat object (dict), not a list or scalar.[/red]")
        raise typer.Exit(code=1)

    return cast("dict[str, Any]", parsed)


def do_run(
    target: str,
    inputs_file: str | None = None,
    inputs_json: str | None = None,
    runner: str | None = None,
    extra_args: list[str] | None = None,
    directory: str | None = None,
) -> None:
    """Execute a pipe via a runner.

    Args:
        target: .mthds file path or pipe code to execute.
        inputs_file: Path to a JSON file containing inputs.
        inputs_json: Inline JSON string with inputs.
        runner: Runner to use ("pipelex", "api", or None for auto-detect).
        extra_args: Additional arguments passed through to the runner.
        directory: Target package directory (defaults to current directory).
    """
    _ = extra_args  # reserved for future use
    console = get_console()

    runner_type: RunnerType | None = None
    if runner:
        try:
            runner_type = RunnerType(runner)
        except ValueError:
            console.print(f"[red]Unknown runner: '{escape(runner)}'. Use 'pipelex' or 'api'.[/red]")
            raise typer.Exit(code=1) from None

    library_dirs = [str(Path(directory).resolve())] if directory else None
    runner_instance = create_runner(runner_type, library_dirs=library_dirs)

    # Resolve target → pipe_code / mthds_content
    pipe_code: str | None = None
    mthds_content: str | None = None
    package_dir = Path(directory).resolve() if directory else Path.cwd()
    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = package_dir / target

    if target_path.is_file() and target_path.suffix == ".mthds":
        mthds_content = target_path.read_text(encoding="utf-8")
    else:
        pipe_code = target

    # Parse inputs
    pipeline_inputs: dict[str, Any] | None = None
    if inputs_file:
        inputs_path = Path(inputs_file)
        if not inputs_path.is_file():
            console.print(f"[red]Inputs file not found: {escape(inputs_file)}[/red]")
            raise typer.Exit(code=1)
        pipeline_inputs = _parse_inputs_json(inputs_path.read_text(encoding="utf-8"))
    elif inputs_json:
        pipeline_inputs = _parse_inputs_json(inputs_json)

    async def _execute() -> None:
        try:
            response = await runner_instance.execute_pipeline(
                pipe_code=pipe_code,
                mthds_content=mthds_content,
                inputs=pipeline_inputs,
            )
            console.print_json(json.dumps(response.model_dump(), default=str))
        except PipelexRunnerError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(code=1) from exc

    asyncio.run(_execute())
