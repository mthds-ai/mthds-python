"""Config commands for managing MTHDS credentials.

Provides set, get, and list operations for the credentials stored
in ``~/.mthds/credentials``.
"""

from rich import box
from rich.markup import escape
from rich.table import Table

from mthds.cli._console import get_console
from mthds.config.credentials import (
    VALID_KEYS,
    CredentialSource,
    get_credential_value,
    list_credentials,
    resolve_key,
    set_credential_value,
)


def do_config_set(key: str, value: str) -> None:
    """Set a credential value.

    Args:
        key: The CLI key name (e.g. "api-key", "runner").
        value: The value to store.
    """
    console = get_console()

    internal_key = resolve_key(key)
    if internal_key is None:
        console.print(f"[red]Unknown config key: '{escape(key)}'[/red]")
        console.print(f"[dim]Valid keys: {', '.join(VALID_KEYS)}[/dim]")
        return

    set_credential_value(internal_key, value)
    console.print(f"[green]Set '{escape(key)}' = '{escape(value)}'[/green]")


def do_config_get(key: str) -> None:
    """Get a credential value and display it with its source.

    Args:
        key: The CLI key name (e.g. "api-key", "runner").
    """
    console = get_console()

    internal_key = resolve_key(key)
    if internal_key is None:
        console.print(f"[red]Unknown config key: '{escape(key)}'[/red]")
        console.print(f"[dim]Valid keys: {', '.join(VALID_KEYS)}[/dim]")
        return

    entry = get_credential_value(internal_key)

    match entry.source:
        case CredentialSource.ENV:
            source_label = "env"
        case CredentialSource.FILE:
            source_label = "file"
        case CredentialSource.DEFAULT:
            source_label = "default"

    display_value = entry.value or "(empty)"
    console.print(f"[bold]{escape(key)}[/bold] = {escape(display_value)}  [dim](source: {source_label})[/dim]")


def do_config_list() -> None:
    """List all credential values with their sources."""
    console = get_console()

    entries = list_credentials()

    table = Table(title="MTHDS Configuration", box=box.ROUNDED, show_header=True)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_column("Source", style="dim")

    for entry in entries:
        match entry.source:
            case CredentialSource.ENV:
                source_label = "env"
            case CredentialSource.FILE:
                source_label = "file"
            case CredentialSource.DEFAULT:
                source_label = "default"

        display_value = entry.value or "(empty)"
        table.add_row(escape(entry.cli_key), escape(display_value), source_label)

    console.print(table)
