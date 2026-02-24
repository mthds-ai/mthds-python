import textwrap
from pathlib import Path

import pytest
import typer

from mthds.cli.commands.package.list_cmd import do_list

MINIMAL_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "A test package"
""")

FULL_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    display_name = "Acme Widgets"
    version = "2.1.0-beta.1"
    description = "Full-featured widget package"
    authors = ["Alice <alice@acme.com>"]
    license = "MIT"

    [dependencies]
    foo_pkg = {address = "github.com/acme/foo", version = "^1.0.0"}

    [exports.legal.contracts]
    pipes = ["extract_clause"]
""")


class TestListCmd:
    """Tests for the mthds.cli.commands.package.list_cmd module."""

    def test_do_list_no_manifest(self, tmp_path: Path):
        with pytest.raises(typer.Exit):
            do_list(directory=str(tmp_path))

    def test_do_list_minimal(self, tmp_path: Path):
        """Manifest with no deps/exports should only print the package table."""
        (tmp_path / "METHODS.toml").write_text(MINIMAL_TOML)
        # Should not raise
        do_list(directory=str(tmp_path))

    def test_do_list_full(self, tmp_path: Path):
        """Manifest with deps and exports should print all tables."""
        (tmp_path / "METHODS.toml").write_text(FULL_TOML)
        # Should not raise
        do_list(directory=str(tmp_path))
