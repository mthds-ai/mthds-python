"""Validate command for 'mthds validate'.

Validates METHODS.toml manifest structure and fields. When a runner is
specified (e.g. --runner pipelex), also delegates deeper validation to
the runner CLI as a subprocess.
"""

import shutil
import subprocess  # noqa: S404
from pathlib import Path

import typer
from rich.markup import escape

from mthds.cli._console import get_console, resolve_directory
from mthds.packages.discovery import MANIFEST_FILENAME
from mthds.packages.exceptions import ManifestError
from mthds.packages.manifest_parser import parse_methods_toml


def _validate_manifest(package_root: Path) -> bool:
    """Validate the METHODS.toml manifest in the given package root.

    Parses the manifest file and checks that all fields are structurally
    correct (address format, semver version, non-empty description, etc.).

    Args:
        package_root: Path to the package root directory.

    Returns:
        True if the manifest is valid, False otherwise.
    """
    console = get_console()

    manifest_path = package_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        console.print(f"[red]{MANIFEST_FILENAME} not found in {escape(str(package_root))}[/red]")
        console.print("[dim]Run 'mthds init' to create one.[/dim]")
        return False

    content = manifest_path.read_text(encoding="utf-8")
    try:
        parse_methods_toml(content)
    except ManifestError as exc:
        console.print(f"[red]{MANIFEST_FILENAME} is invalid: {escape(exc.message)}[/red]")
        return False

    console.print(f"[green]{MANIFEST_FILENAME} is valid.[/green]")
    return True


def _validate_with_runner(
    runner: str,
    target: str | None,
    validate_all: bool,
    extra_args: list[str],
    package_root: Path | None = None,
) -> None:
    """Delegate deeper validation to a runner CLI as a subprocess.

    Args:
        runner: Runner name (currently only "pipelex" is supported).
        target: Optional target (pipe code or .mthds file path).
        validate_all: Whether to validate all pipes (--all flag).
        extra_args: Additional arguments passed through to the runner.
        package_root: Directory to run the runner in (defaults to CWD).
    """
    console = get_console()

    match runner:
        case "pipelex":
            _validate_with_pipelex(target, validate_all, extra_args, package_root=package_root)
        case _:
            console.print(f"[red]Unknown runner: '{escape(runner)}'. Currently only 'pipelex' is supported.[/red]")
            raise typer.Exit(code=1)


def _validate_with_pipelex(
    target: str | None,
    validate_all: bool,
    extra_args: list[str],
    package_root: Path | None = None,
) -> None:
    """Delegate validation to 'pipelex validate' as a subprocess.

    Args:
        target: Optional target (pipe code or .mthds file path).
        validate_all: Whether to validate all pipes.
        extra_args: Additional arguments passed through to pipelex.
        package_root: Directory to run pipelex in (defaults to CWD).
    """
    console = get_console()

    if shutil.which("pipelex") is None:
        console.print("[red]'pipelex' not found on PATH.[/red]")
        console.print("[dim]Install pipelex: curl -sSL https://pipelex.com/install.sh | sh[/dim]")
        raise typer.Exit(code=1)

    cmd: list[str] = ["pipelex", "validate"]
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
            cwd=package_root,
        )
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
    except FileNotFoundError as exc:
        console.print("[red]'pipelex' not found on PATH.[/red]")
        console.print("[dim]Install pipelex: curl -sSL https://pipelex.com/install.sh | sh[/dim]")
        raise typer.Exit(code=1) from exc
    except subprocess.TimeoutExpired as exc:
        console.print("[red]Runner validation timed out (10 min limit).[/red]")
        raise typer.Exit(code=1) from exc


def do_validate(
    target: str | None = None,
    validate_all: bool = False,
    runner: str | None = None,
    extra_args: list[str] | None = None,
    directory: Path | None = None,
) -> None:
    """Validate the package manifest and optionally delegate to a runner.

    Args:
        target: Optional pipe code or .mthds file path for runner validation.
        validate_all: Whether to validate all pipes via the runner.
        runner: Runner to use for deeper validation (e.g. "pipelex").
        extra_args: Additional arguments passed through to the runner.
        directory: Package directory (defaults to current directory).
    """
    package_root = resolve_directory(directory)

    # When --directory shifts the working directory, resolve any relative file
    # path in target against the original CWD so the subprocess finds the
    # correct file.
    if target is not None and directory is not None:
        target_as_path = Path(target)
        if not target_as_path.is_absolute() and target_as_path.suffix == ".mthds":
            target = str(target_as_path.resolve())

    manifest_ok = _validate_manifest(package_root)

    if runner:
        if not manifest_ok:
            console = get_console()
            console.print("[dim]Skipping runner validation due to manifest errors.[/dim]")
            raise typer.Exit(code=1)

        _validate_with_runner(runner, target, validate_all, extra_args or [], package_root=package_root)
    elif not manifest_ok:
        raise typer.Exit(code=1)
