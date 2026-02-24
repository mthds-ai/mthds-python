import textwrap
from pathlib import Path

import pytest
import typer

from mthds.cli.commands.package.add_cmd import derive_alias_from_address, do_add
from mthds.package.manifest.parser import parse_methods_toml

MINIMAL_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "test"
""")

TOML_WITH_DEP = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "test"

    [dependencies]
    existing_dep = {address = "github.com/acme/existing", version = "^1.0.0"}
""")


class TestAddCmd:
    """Tests for the mthds.cli.commands.package.add_cmd module."""

    # --- derive_alias_from_address ---

    @pytest.mark.parametrize(
        ("address", "expected_alias"),
        [
            ("github.com/org/my-package", "my_package"),
            ("github.com/org/my.package", "my_package"),
            ("github.com/org/package/", "package"),
            ("github.com/org/$pecial!", "pecial"),
        ],
    )
    def test_derive_alias_from_address(self, address: str, expected_alias: str):
        assert derive_alias_from_address(address) == expected_alias

    def test_derive_alias_fallback(self):
        """All special chars removed -> fallback to 'dep'."""
        assert derive_alias_from_address("github.com/org/!!!/") == "dep"

    # --- do_add ---

    def test_do_add_success(self, tmp_path: Path):
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(MINIMAL_TOML)

        do_add(
            address="github.com/acme/new_dep",
            alias="new_dep",
            version="^1.0.0",
            directory=str(tmp_path),
        )

        updated = parse_methods_toml(manifest_path.read_text())
        assert "new_dep" in updated.dependencies
        assert updated.dependencies["new_dep"].address == "github.com/acme/new_dep"
        assert updated.dependencies["new_dep"].version == "^1.0.0"

    def test_do_add_auto_alias(self, tmp_path: Path):
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(MINIMAL_TOML)

        do_add(
            address="github.com/acme/my-package",
            version="^2.0.0",
            directory=str(tmp_path),
        )

        updated = parse_methods_toml(manifest_path.read_text())
        assert "my_package" in updated.dependencies

    def test_do_add_duplicate_alias(self, tmp_path: Path):
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(TOML_WITH_DEP)

        with pytest.raises(typer.Exit):
            do_add(
                address="github.com/acme/another",
                alias="existing_dep",
                version="^1.0.0",
                directory=str(tmp_path),
            )

    def test_do_add_no_manifest(self, tmp_path: Path):
        with pytest.raises(typer.Exit):
            do_add(
                address="github.com/acme/dep",
                alias="dep",
                version="^1.0.0",
                directory=str(tmp_path),
            )

    def test_do_add_with_path(self, tmp_path: Path):
        manifest_path = tmp_path / "METHODS.toml"
        manifest_path.write_text(MINIMAL_TOML)

        do_add(
            address="github.com/acme/local",
            alias="local_dep",
            version="0.1.0",
            path="../local",
            directory=str(tmp_path),
        )

        updated = parse_methods_toml(manifest_path.read_text())
        assert "local_dep" in updated.dependencies
        assert updated.dependencies["local_dep"].path == "../local"
