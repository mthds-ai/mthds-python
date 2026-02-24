"""Runner delegation for 'mthds run'.

Delegates execution to a runner via subprocess (pipelex) or via the existing
MthdsAPIClient. Auto-detect checks if 'pipelex' is on PATH and falls back
to the API client if not.
"""

import asyncio
import json
import shutil
import subprocess  # noqa: S404
from pathlib import Path
from typing import cast

import typer
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.client import MthdsAPIClient
from mthds.models.pipeline_inputs import PipelineInputs


def _parse_inputs_json(raw_json: str) -> dict[str, str]:
    """Parse a JSON string into a dict[str, str] for pipeline inputs.

    Args:
        raw_json: JSON string to parse.

    Returns:
        A dict mapping string keys to string values.

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

    typed_dict = cast("dict[str, object]", parsed)
    return {str(key): str(val) for key, val in typed_dict.items()}


def _detect_runner() -> str:
    """Auto-detect which runner is available.

    Returns:
        "pipelex" if pipelex is on PATH, "api" otherwise.
    """
    if shutil.which("pipelex") is not None:
        return "pipelex"
    return "api"


def _run_with_pipelex(
    target: str,
    inputs_file: str | None,
    inputs_json: str | None,
    extra_args: list[str],
) -> None:
    """Delegate execution to 'pipelex run' as a subprocess.

    Args:
        target: The .mthds file path or pipe code.
        inputs_file: Path to a JSON inputs file.
        inputs_json: Inline JSON inputs string.
        extra_args: Additional arguments passed through to pipelex.
    """
    console = get_console()

    cmd: list[str] = ["pipelex", "run", target]
    if inputs_file:
        cmd.extend(["-i", inputs_file])
    if inputs_json:
        cmd.extend(["--inputs-json", inputs_json])
    cmd.extend(extra_args)

    console.print(f"[dim]Delegating to: {' '.join(escape(arg) for arg in cmd)}[/dim]")

    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            check=False,
            timeout=600,
        )
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
    except FileNotFoundError as exc:
        console.print("[red]'pipelex' not found on PATH.[/red]")
        console.print("[dim]Install pipelex: curl -sSL https://pipelex.com/install.sh | sh[/dim]")
        console.print("[dim]Or use --runner api to run via the MTHDS API instead.[/dim]")
        raise typer.Exit(code=1) from exc
    except subprocess.TimeoutExpired as exc:
        console.print("[red]Execution timed out (10 min limit).[/red]")
        raise typer.Exit(code=1) from exc


def _run_with_api(
    target: str,
    inputs_file: str | None,
    inputs_json: str | None,
) -> None:
    """Delegate execution to the MTHDS API via MthdsAPIClient.

    Args:
        target: The .mthds file path or pipe code.
        inputs_file: Path to a JSON inputs file.
        inputs_json: Inline JSON inputs string.
    """
    console = get_console()

    # Determine pipe_code vs mthds_content
    pipe_code: str | None = None
    mthds_content: str | None = None
    target_path = Path(target)

    if target_path.is_file() and target_path.suffix == ".mthds":
        mthds_content = target_path.read_text(encoding="utf-8")
    else:
        pipe_code = target

    # Parse inputs
    inputs_dict: dict[str, str] | None = None
    if inputs_file:
        inputs_path = Path(inputs_file)
        if not inputs_path.is_file():
            console.print(f"[red]Inputs file not found: {escape(inputs_file)}[/red]")
            raise typer.Exit(code=1)
        inputs_dict = _parse_inputs_json(inputs_path.read_text(encoding="utf-8"))
    elif inputs_json:
        inputs_dict = _parse_inputs_json(inputs_json)

    pipeline_inputs: PipelineInputs | None = None
    if inputs_dict is not None:
        pipeline_inputs = PipelineInputs(inputs=inputs_dict)

    async def _execute() -> None:
        client = MthdsAPIClient()
        client.start_client()
        try:
            response = await client.execute_pipeline(
                pipe_code=pipe_code,
                mthds_content=mthds_content,
                inputs=pipeline_inputs,
            )
            console.print_json(json.dumps(response.model_dump(), default=str))
        finally:
            await client.close()

    asyncio.run(_execute())


def do_run(
    target: str,
    inputs_file: str | None = None,
    inputs_json: str | None = None,
    runner: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """Execute a pipe via a runner.

    Args:
        target: .mthds file path or pipe code to execute.
        inputs_file: Path to a JSON file containing inputs.
        inputs_json: Inline JSON string with inputs.
        runner: Runner to use ("pipelex", "api", or None for auto-detect).
        extra_args: Additional arguments passed through to the runner.
    """
    console = get_console()

    resolved_runner = runner or _detect_runner()

    match resolved_runner:
        case "pipelex":
            _run_with_pipelex(target, inputs_file, inputs_json, extra_args or [])
        case "api":
            _run_with_api(target, inputs_file, inputs_json)
        case _:
            console.print(f"[red]Unknown runner: '{escape(resolved_runner)}'. Use 'pipelex' or 'api'.[/red]")
            raise typer.Exit(code=1)
