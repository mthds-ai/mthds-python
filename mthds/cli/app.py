"""MTHDS package manager CLI.

Provides commands for managing MTHDS packages: init, list, add, lock, install,
update, publish, validate, and run.
"""

from typing import Annotated

import typer

from mthds.cli.commands.add_cmd import do_add
from mthds.cli.commands.init_cmd import do_init
from mthds.cli.commands.install_cmd import do_install
from mthds.cli.commands.list_cmd import do_list
from mthds.cli.commands.lock_cmd import do_lock
from mthds.cli.commands.publish_cmd import do_publish
from mthds.cli.commands.run_cmd import do_run
from mthds.cli.commands.update_cmd import do_update
from mthds.cli.commands.validate_cmd import do_validate

app = typer.Typer(
    name="mthds",
    no_args_is_help=True,
    help="MTHDS package manager — manage and validate MTHDS packages.",
)


@app.command("init", help="Initialize a METHODS.toml package manifest in the current directory")
def init_cmd(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing METHODS.toml"),
    ] = False,
) -> None:
    """Create a bare METHODS.toml skeleton."""
    do_init(force=force)


@app.command("list", help="Display the package manifest (METHODS.toml) for the current directory")
def list_cmd() -> None:
    """Show the package manifest if one exists."""
    do_list()


@app.command("add", help="Add a dependency to METHODS.toml")
def add_cmd(
    address: Annotated[
        str,
        typer.Argument(help="Package address (e.g. 'github.com/org/repo')"),
    ],
    alias: Annotated[
        str | None,
        typer.Option("--alias", "-a", help="Dependency alias (auto-derived from address if not provided)"),
    ] = None,
    version: Annotated[
        str,
        typer.Option("--version", "-v", help="Version constraint"),
    ] = "0.1.0",
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Local filesystem path to the dependency"),
    ] = None,
) -> None:
    """Add a dependency to the package manifest."""
    do_add(address=address, alias=alias, version=version, path=path)


@app.command("lock", help="Resolve dependencies and generate methods.lock")
def lock_cmd() -> None:
    """Resolve all dependencies and write a lock file."""
    do_lock()


@app.command("install", help="Install dependencies from methods.lock")
def install_cmd() -> None:
    """Fetch packages recorded in the lock file."""
    do_install()


@app.command("update", help="Re-resolve dependencies and update methods.lock")
def update_cmd() -> None:
    """Fresh resolve of all dependencies and rewrite the lock file."""
    do_update()


@app.command("publish", help="Publish package for distribution (not yet implemented)")
def publish_cmd(
    tag: Annotated[
        bool,
        typer.Option("--tag", help="Create git tag v{version} locally on success"),
    ] = False,
) -> None:
    """Validate that the package is ready for distribution."""
    do_publish(tag=tag)


@app.command("validate", help="Validate METHODS.toml and optionally run deeper validation via a runner")
def validate_cmd(
    target: Annotated[
        str | None,
        typer.Argument(help="Pipe code or .mthds file path (for runner validation)"),
    ] = None,
    validate_all: Annotated[
        bool,
        typer.Option("--all", "-a", help="Validate all pipes via the runner"),
    ] = False,
    runner: Annotated[
        str | None,
        typer.Option("--runner", "-r", help="Runner for deeper validation (e.g. 'pipelex')"),
    ] = None,
    extra_args: Annotated[
        list[str] | None,
        typer.Argument(help="Additional arguments passed through to the runner"),
    ] = None,
) -> None:
    """Validate the package manifest and optionally delegate to a runner."""
    do_validate(target=target, validate_all=validate_all, runner=runner, extra_args=extra_args)


@app.command("run", help="Execute a pipe via a runner (pipelex subprocess or MTHDS API)")
def run_cmd(
    target: Annotated[
        str,
        typer.Argument(help=".mthds file path or pipe code to execute"),
    ],
    inputs: Annotated[
        str | None,
        typer.Option("--inputs", "-i", help="Path to a JSON file containing inputs"),
    ] = None,
    inputs_json: Annotated[
        str | None,
        typer.Option("--inputs-json", help="Inline JSON string with inputs"),
    ] = None,
    runner: Annotated[
        str | None,
        typer.Option("--runner", "-r", help="Runner to use: 'pipelex' or 'api' (auto-detect if omitted)"),
    ] = None,
    extra_args: Annotated[
        list[str] | None,
        typer.Argument(help="Additional arguments passed through to the runner"),
    ] = None,
) -> None:
    """Execute a pipe via a runner."""
    do_run(target=target, inputs_file=inputs, inputs_json=inputs_json, runner=runner, extra_args=extra_args)
