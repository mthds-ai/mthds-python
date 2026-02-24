"""MTHDS CLI.

Provides commands for managing MTHDS packages (package subgroup), configuration,
setup, build stubs, validation, and pipeline execution.
"""

from typing import Annotated

import typer

from mthds.cli.commands.build_cmd import do_build_inputs, do_build_output, do_build_pipe, do_build_runner
from mthds.cli.commands.config_cmd import do_config_get, do_config_list, do_config_set
from mthds.cli.commands.package.app import package_app
from mthds.cli.commands.run_cmd import do_run
from mthds.cli.commands.setup_cmd import do_setup_runner
from mthds.cli.commands.validate_cmd import do_validate

app = typer.Typer(
    name="mthds",
    no_args_is_help=True,
    help="MTHDS CLI — manage packages, configure credentials, and run pipelines.",
)

# ── Package subcommand group ─────────────────────────────────────────
app.add_typer(package_app, name="package")

# ── Config subcommand group ──────────────────────────────────────────
config_app = typer.Typer(
    name="config",
    no_args_is_help=True,
    help="Manage MTHDS configuration and credentials.",
)
app.add_typer(config_app, name="config")


@config_app.command("set", help="Set a configuration value")
def config_set_cmd(
    key: Annotated[
        str,
        typer.Argument(help="Configuration key (e.g. 'api-key', 'runner', 'api-url', 'telemetry')"),
    ],
    value: Annotated[
        str,
        typer.Argument(help="Value to set"),
    ],
) -> None:
    """Set a credential value."""
    do_config_set(key=key, value=value)


@config_app.command("get", help="Get a configuration value")
def config_get_cmd(
    key: Annotated[
        str,
        typer.Argument(help="Configuration key (e.g. 'api-key', 'runner', 'api-url', 'telemetry')"),
    ],
) -> None:
    """Get a credential value and its source."""
    do_config_get(key=key)


@config_app.command("list", help="List all configuration values")
def config_list_cmd() -> None:
    """List all credential values with their sources."""
    do_config_list()


# ── Setup subcommand group ───────────────────────────────────────────
setup_app = typer.Typer(
    name="setup",
    no_args_is_help=True,
    help="Setup runners and dependencies.",
)
app.add_typer(setup_app, name="setup")


@setup_app.command("runner", help="Check if a runner is available and print installation instructions")
def setup_runner_cmd(
    name: Annotated[
        str,
        typer.Argument(help="Runner name (e.g. 'pipelex', 'api')"),
    ],
) -> None:
    """Check runner availability and show install instructions."""
    do_setup_runner(name=name)


# ── Build subcommand group ───────────────────────────────────────────
build_app = typer.Typer(
    name="build",
    no_args_is_help=True,
    help="Build pipes, runners, inputs, and outputs (delegates to a runner).",
)
app.add_typer(build_app, name="build")


@build_app.command("pipe", help="Build a pipe from a brief description")
def build_pipe_cmd(
    brief: Annotated[
        str,
        typer.Argument(help="Brief description of the pipe to build"),
    ],
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Build a pipe from a brief."""
    do_build_pipe(brief=brief, directory=directory)


@build_app.command("runner", help="Build a runner configuration")
def build_runner_cmd(
    target: Annotated[
        str,
        typer.Argument(help="Target runner to build for"),
    ],
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Build a runner configuration."""
    do_build_runner(target=target, directory=directory)


@build_app.command("inputs", help="Build inputs for a pipe")
def build_inputs_cmd(
    target: Annotated[
        str,
        typer.Argument(help="Target runner"),
    ],
    pipe_code: Annotated[
        str,
        typer.Argument(help="Pipe code to build inputs for"),
    ],
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Build inputs for a pipe."""
    do_build_inputs(target=target, pipe_code=pipe_code, directory=directory)


@build_app.command("output", help="Build output configuration for a pipe")
def build_output_cmd(
    target: Annotated[
        str,
        typer.Argument(help="Target runner"),
    ],
    pipe_code: Annotated[
        str,
        typer.Argument(help="Pipe code to build output for"),
    ],
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format"),
    ] = "json",
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
) -> None:
    """Build output configuration for a pipe."""
    do_build_output(target=target, pipe_code=pipe_code, fmt=fmt, directory=directory)


# ── Top-level commands ───────────────────────────────────────────────


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
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
    extra_args: Annotated[
        list[str] | None,
        typer.Argument(help="Additional arguments passed through to the runner"),
    ] = None,
) -> None:
    """Validate the package manifest and optionally delegate to a runner."""
    do_validate(target=target, validate_all=validate_all, runner=runner, extra_args=extra_args, directory=directory)


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
    directory: Annotated[
        str | None,
        typer.Option("--directory", "-d", help="Target package directory (defaults to current directory)"),
    ] = None,
    extra_args: Annotated[
        list[str] | None,
        typer.Argument(help="Additional arguments passed through to the runner"),
    ] = None,
) -> None:
    """Execute a pipe via a runner."""
    do_run(target=target, inputs_file=inputs, inputs_json=inputs_json, runner=runner, extra_args=extra_args, directory=directory)
