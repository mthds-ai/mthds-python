"""Validate command for 'mthds validate'.

Validates METHODS.toml manifest structure and fields. When a runner is
specified (e.g. --runner pipelex), also delegates deeper validation to
the pipelex CLI as a subprocess.
"""

import shutil
import subprocess  # noqa: S404
from pathlib import Path

import typer
from rich.markup import escape

from mthds.cli._console import get_console
from mthds.package.discovery import MANIFEST_FILENAME
from mthds.package.exceptions import ManifestError
from mthds.package.manifest.parser import parse_methods_toml
from mthds.runners.types import RunnerType


def _validate_manifest(package_root: Path) -> bool:
    """Validate the METHODS.toml manifest in the given package root.

    Args:
        package_root: Path to the package root directory.

    Returns:
        True if the manifest is valid, False otherwise.
    """
    console = get_console()

    manifest_path = package_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        console.print(f"[red]{MANIFEST_FILENAME} not found in {escape(str(package_root))}[/red]")
        console.print("[dim]Run 'mthds package init' to create one.[/dim]")
        return False

    content = manifest_path.read_text(encoding="utf-8")
    try:
        parse_methods_toml(content)
    except ManifestError as exc:
        console.print(f"[red]{MANIFEST_FILENAME} is invalid: {escape(exc.message)}[/red]")
        return False

    console.print(f"[green]{MANIFEST_FILENAME} is valid.[/green]")
    return True


def _validate_with_pipelex(
    target: str | None,
    validate_all: bool,
    extra_args: list[str],
    directory: str | None = None,
) -> None:
    """Delegate validation to 'pipelex validate' as a subprocess.

    Args:
        target: Optional target (pipe code or .mthds file path).
        validate_all: Whether to validate all pipes.
        extra_args: Additional arguments passed through to pipelex.
        directory: Target package directory for pipelex -L flag.

    Raises:
        typer.Exit: If validation fails or pipelex is not found.
    """
    console = get_console()

    if shutil.which("pipelex") is None:
        console.print("[red]'pipelex' not found on PATH.[/red]")
        console.print("[dim]Install pipelex: curl -sSL https://pipelex.com/install.sh | sh[/dim]")
        raise typer.Exit(code=1)

    cmd: list[str] = ["pipelex", "validate"]
    if directory:
        cmd.extend(["-L", str(Path(directory).resolve())])
    if target:
        cmd.append(target)
    if validate_all:
        cmd.append("--all")
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
        raise typer.Exit(code=1) from exc
    except subprocess.TimeoutExpired as exc:
        console.print("[red]Runner validation timed out (10 min limit).[/red]")
        raise typer.Exit(code=1) from exc


def do_validate(
    target: str | None = None,
    validate_all: bool = False,
    runner: str | None = None,
    extra_args: list[str] | None = None,
    directory: str | None = None,
) -> None:
    """Validate the package manifest and optionally delegate to a runner.

    Args:
        target: Optional pipe code or .mthds file path for runner validation.
        validate_all: Whether to validate all pipes via the runner.
        runner: Runner to use for deeper validation (e.g. "pipelex").
        extra_args: Additional arguments passed through to the runner.
        directory: Target package directory (defaults to current directory).
    """
    console = get_console()
    package_root = Path(directory).resolve() if directory else Path.cwd()

    manifest_ok = _validate_manifest(package_root)

    if runner:
        if not manifest_ok:
            console.print("[dim]Skipping runner validation due to manifest errors.[/dim]")
            raise typer.Exit(code=1)

        try:
            runner_type = RunnerType(runner)
        except ValueError:
            console.print(f"[red]Unknown runner: '{escape(runner)}'. Use 'pipelex' or 'api'.[/red]")
            raise typer.Exit(code=1) from None

        match runner_type:
            case RunnerType.PIPELEX:
                _validate_with_pipelex(target, validate_all, extra_args or [], directory=directory)
            case RunnerType.API:
                console.print("[yellow]Validation via the API runner is not yet supported. Use --runner pipelex.[/yellow]")
                raise typer.Exit(code=1)
    elif not manifest_ok:
        raise typer.Exit(code=1)
