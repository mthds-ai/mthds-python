"""Package management subcommand group.

Registers all package management commands: init, list, add, lock, install,
and update.
"""

from typing import Annotated

import typer

from mthds.cli.commands.package.add_cmd import do_add
from mthds.cli.commands.package.init_cmd import do_init
from mthds.cli.commands.package.install_cmd import do_install
from mthds.cli.commands.package.list_cmd import do_list
from mthds.cli.commands.package.lock_cmd import do_lock
from mthds.cli.commands.package.update_cmd import do_update

package_app = typer.Typer(
    name="package",
    no_args_is_help=True,
    help="Manage MTHDS packages: init, list, add, lock, install, update.",
)


@package_app.command("init", help="Initialize a METHODS.toml package manifest in the current directory")
def init_cmd(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing METHODS.toml"),
    ] = False,
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Create a bare METHODS.toml skeleton."""
    do_init(force=force, directory=directory)


@package_app.command("list", help="Display the package manifest (METHODS.toml) for the current directory")
def list_cmd(
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Show the package manifest if one exists."""
    do_list(directory=directory)


@package_app.command("add", help="Add a dependency to METHODS.toml")
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
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Add a dependency to the package manifest."""
    do_add(address=address, alias=alias, version=version, path=path, directory=directory)


@package_app.command("lock", help="Resolve dependencies and generate methods.lock")
def lock_cmd(
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Resolve all dependencies and write a lock file."""
    do_lock(directory=directory)


@package_app.command("install", help="Install dependencies from methods.lock")
def install_cmd(
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Fetch packages recorded in the lock file."""
    do_install(directory=directory)


@package_app.command("update", help="Re-resolve dependencies and update methods.lock")
def update_cmd(
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Fresh resolve of all dependencies and rewrite the lock file."""
    do_update(directory=directory)
