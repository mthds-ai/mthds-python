from pathlib import Path

import typer
from rich import box
from rich.markup import escape
from rich.table import Table

from mthds.cli._console import get_console
from mthds.packages.discovery import MANIFEST_FILENAME, find_package_manifest
from mthds.packages.exceptions import ManifestError


def do_list(directory: Path | None = None) -> None:
    """Display the package manifest information.

    Walks up from the given directory to find a METHODS.toml and displays its contents.

    Args:
        directory: Package directory (defaults to current directory)
    """
    console = get_console()
    cwd = Path(directory).resolve() if directory else Path.cwd()

    # Create a dummy bundle path to trigger the walk-up search from cwd
    dummy_bundle_path = cwd / "dummy.mthds"
    try:
        manifest = find_package_manifest(dummy_bundle_path)
    except ManifestError as exc:
        console.print(f"[red]Error reading METHODS.toml: {escape(exc.message)}[/red]")
        raise typer.Exit(code=1) from exc

    if manifest is None:
        console.print(f"[yellow]No {MANIFEST_FILENAME} found in current directory or parent directories.[/yellow]")
        console.print("Run [bold]mthds init[/bold] to create one.")
        raise typer.Exit(code=1)

    # Display package info
    console.print(f"\n[bold]{MANIFEST_FILENAME}[/bold]\n")

    # Package table
    pkg_table = Table(title="Package", box=box.ROUNDED, show_header=True)
    pkg_table.add_column("Field", style="cyan")
    pkg_table.add_column("Value")
    pkg_table.add_row("Address", escape(manifest.address))
    if manifest.display_name:
        pkg_table.add_row("Display Name", escape(manifest.display_name))
    pkg_table.add_row("Version", escape(manifest.version))
    pkg_table.add_row("Description", escape(manifest.description))
    if manifest.authors:
        pkg_table.add_row("Authors", escape(", ".join(manifest.authors)))
    if manifest.license:
        pkg_table.add_row("License", escape(manifest.license))
    if manifest.mthds_version:
        pkg_table.add_row("MTHDS Version", escape(manifest.mthds_version))
    console.print(pkg_table)

    # Dependencies table
    if manifest.dependencies:
        console.print()
        deps_table = Table(title="Dependencies", box=box.ROUNDED, show_header=True)
        deps_table.add_column("Alias", style="cyan")
        deps_table.add_column("Address")
        deps_table.add_column("Version")
        for dep in manifest.dependencies:
            deps_table.add_row(escape(dep.alias), escape(dep.address), escape(dep.version))
        console.print(deps_table)

    # Exports table
    if manifest.exports:
        console.print()
        exports_table = Table(title="Exports", box=box.ROUNDED, show_header=True)
        exports_table.add_column("Domain", style="cyan")
        exports_table.add_column("Pipes")
        for domain_export in manifest.exports:
            exports_table.add_row(
                escape(domain_export.domain_path),
                escape(", ".join(domain_export.pipes)),
            )
        console.print(exports_table)

    console.print()
