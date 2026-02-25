import textwrap

import pytest

from mthds.package.exceptions import ManifestParseError, ManifestValidationError
from mthds.package.manifest.parser import parse_methods_toml, serialize_manifest_to_toml
from mthds.package.manifest.schema import MethodsManifest, PackageDependency, is_valid_method_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_TOML = textwrap.dedent("""\
    [package]
    name = "acme-widgets"
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "A minimal package"
""")

FULL_TOML = textwrap.dedent("""\
    [package]
    name = "acme-widgets"
    address = "github.com/acme/widgets"
    display_name = "Acme Widgets"
    version = "2.1.0-beta.1"
    description = "Full-featured widget package"
    authors = ["Alice <alice@acme.com>", "Bob <bob@acme.com>"]
    license = "MIT"
    mthds_version = "^1.0.0"
    main_pipe = "extract_clause"

    [dependencies]
    foo_pkg = {address = "github.com/acme/foo", version = "^1.0.0"}
    bar_pkg = {address = "github.com/acme/bar", version = ">=0.5.0, <2.0.0"}

    [exports.legal.contracts]
    pipes = ["extract_clause", "summarize"]

    [exports.legal.compliance]
    pipes = ["check_rule"]

    [exports.finance]
    pipes = ["compute_tax"]
""")


# ===========================================================================
# Happy-path: parsing
# ===========================================================================


class TestParseMethodsToml:
    def test_minimal(self):
        manifest = parse_methods_toml(MINIMAL_TOML)
        assert manifest.name == "acme-widgets"
        assert manifest.address == "github.com/acme/widgets"
        assert manifest.version == "1.0.0"
        assert manifest.description == "A minimal package"
        assert manifest.display_name is None
        assert manifest.authors == []
        assert manifest.license is None
        assert manifest.mthds_version is None
        assert manifest.main_pipe is None
        assert manifest.dependencies == {}
        assert manifest.exports == {}

    def test_full(self):
        manifest = parse_methods_toml(FULL_TOML)
        assert manifest.name == "acme-widgets"
        assert manifest.address == "github.com/acme/widgets"
        assert manifest.display_name == "Acme Widgets"
        assert manifest.version == "2.1.0-beta.1"
        assert manifest.authors == ["Alice <alice@acme.com>", "Bob <bob@acme.com>"]
        assert manifest.license == "MIT"
        assert manifest.mthds_version == "^1.0.0"
        assert manifest.main_pipe == "extract_clause"

        # Dependencies
        assert len(manifest.dependencies) == 2
        assert set(manifest.dependencies.keys()) == {"foo_pkg", "bar_pkg"}
        assert manifest.dependencies["foo_pkg"].address == "github.com/acme/foo"
        assert manifest.dependencies["foo_pkg"].version == "^1.0.0"
        assert manifest.dependencies["foo_pkg"].path is None

        # Exports
        assert len(manifest.exports) == 3
        assert set(manifest.exports.keys()) == {"legal.contracts", "legal.compliance", "finance"}
        assert manifest.exports["legal.contracts"].pipes == ["extract_clause", "summarize"]

    def test_dependency_with_path(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies]
            local_dep = {address = "github.com/acme/local", version = "0.1.0", path = "../local"}
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.dependencies["local_dep"].path == "../local"

    def test_nested_exports_deep(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.legal.contracts.shareholder]
            pipes = ["extract"]
        """)
        manifest = parse_methods_toml(toml)
        assert len(manifest.exports) == 1
        assert "legal.contracts.shareholder" in manifest.exports

    def test_domain_with_pipes_and_subdomains(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.legal]
            pipes = ["overview"]

            [exports.legal.contracts]
            pipes = ["extract_clause"]
        """)
        manifest = parse_methods_toml(toml)
        assert len(manifest.exports) == 2
        assert set(manifest.exports.keys()) == {"legal", "legal.contracts"}

    def test_no_dependencies_no_exports(self):
        manifest = parse_methods_toml(MINIMAL_TOML)
        assert manifest.dependencies == {}
        assert manifest.exports == {}


# ===========================================================================
# Happy-path: direct construction
# ===========================================================================


class TestDirectConstruction:
    def test_minimal_direct(self):
        manifest = MethodsManifest(
            address="example.com/org/repo",
            version="0.1.0",
            description="A test package",
        )
        assert manifest.address == "example.com/org/repo"
        assert manifest.version == "0.1.0"
        assert manifest.dependencies == {}

    def test_with_dependencies(self):
        manifest = MethodsManifest(
            address="example.com/org/repo",
            version="0.1.0",
            description="A test package",
            dependencies={
                "foo_pkg": PackageDependency(address="github.com/acme/foo", version="^1.0.0"),
            },
        )
        assert "foo_pkg" in manifest.dependencies
        assert manifest.dependencies["foo_pkg"].address == "github.com/acme/foo"

    def test_model_validate_raw_dict(self):
        raw = {
            "package": {
                "address": "github.com/org/repo",
                "version": "1.0.0",
                "description": "test",
            },
        }
        manifest = MethodsManifest.model_validate(raw)
        assert manifest.address == "github.com/org/repo"


# ===========================================================================
# Round-trip: parse -> serialize -> parse
# ===========================================================================


class TestRoundTrip:
    def test_minimal_round_trip(self):
        original = parse_methods_toml(MINIMAL_TOML)
        serialized = serialize_manifest_to_toml(original)
        restored = parse_methods_toml(serialized)
        assert restored.name == original.name
        assert restored.address == original.address
        assert restored.version == original.version
        assert restored.description == original.description

    def test_full_round_trip(self):
        original = parse_methods_toml(FULL_TOML)
        serialized = serialize_manifest_to_toml(original)
        restored = parse_methods_toml(serialized)

        assert restored.name == original.name
        assert restored.address == original.address
        assert restored.display_name == original.display_name
        assert restored.version == original.version
        assert restored.authors == original.authors
        assert restored.license == original.license
        assert restored.mthds_version == original.mthds_version
        assert restored.main_pipe == original.main_pipe

        assert len(restored.dependencies) == len(original.dependencies)
        for alias in original.dependencies:
            assert alias in restored.dependencies
            assert restored.dependencies[alias].address == original.dependencies[alias].address
            assert restored.dependencies[alias].version == original.dependencies[alias].version

        assert len(restored.exports) == len(original.exports)
        for domain_path in original.exports:
            assert domain_path in restored.exports
            assert restored.exports[domain_path].pipes == original.exports[domain_path].pipes


# ===========================================================================
# TOML syntax errors
# ===========================================================================


class TestTomlSyntaxErrors:
    def test_invalid_toml_raises_parse_error(self):
        with pytest.raises(ManifestParseError):
            parse_methods_toml("[package\nbroken toml")

    def test_empty_string_raises_validation_error(self):
        with pytest.raises(ManifestValidationError):
            parse_methods_toml("")


# ===========================================================================
# Validation errors — [package] fields
# ===========================================================================


class TestPackageFieldValidation:
    def test_missing_package_section(self):
        with pytest.raises(ManifestValidationError):
            parse_methods_toml('[dependencies]\nfoo = {address = "github.com/a/b", version = "1.0.0"}')

    def test_missing_address(self):
        toml = textwrap.dedent("""\
            [package]
            version = "1.0.0"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError):
            parse_methods_toml(toml)

    def test_missing_version(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError):
            parse_methods_toml(toml)

    def test_missing_description(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
        """)
        with pytest.raises(ManifestValidationError):
            parse_methods_toml(toml)

    def test_invalid_address_no_dot(self):
        toml = textwrap.dedent("""\
            [package]
            address = "nodot/repo"
            version = "1.0.0"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError, match="address"):
            parse_methods_toml(toml)

    def test_invalid_semver(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "not-a-version"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError, match="version"):
            parse_methods_toml(toml)

    def test_empty_description(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "   "
        """)
        with pytest.raises(ManifestValidationError, match="description"):
            parse_methods_toml(toml)

    def test_display_name_too_long(self):
        long_name = "A" * 200
        toml = textwrap.dedent(f"""\
            [package]
            address = "github.com/acme/widgets"
            display_name = "{long_name}"
            version = "1.0.0"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError, match="128"):
            parse_methods_toml(toml)

    def test_display_name_empty(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            display_name = "   "
            version = "1.0.0"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError, match=r"[Dd]isplay name"):
            parse_methods_toml(toml)

    def test_empty_author(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
            authors = ["Alice", "  "]
        """)
        with pytest.raises(ManifestValidationError, match=r"[Aa]uthor"):
            parse_methods_toml(toml)

    def test_empty_license(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
            license = "  "
        """)
        with pytest.raises(ManifestValidationError, match=r"[Ll]icense"):
            parse_methods_toml(toml)

    def test_invalid_mthds_version(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
            mthds_version = "not valid!!"
        """)
        with pytest.raises(ManifestValidationError, match="mthds_version"):
            parse_methods_toml(toml)


# ===========================================================================
# Validation errors — unknown keys / sections
# ===========================================================================


class TestUnknownKeysAndSections:
    def test_unknown_top_level_section(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [bogus]
            key = "value"
        """)
        with pytest.raises(ManifestValidationError, match="Unknown sections"):
            parse_methods_toml(toml)

    def test_unknown_package_key(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
            unknown_key = "value"
        """)
        with pytest.raises(ManifestValidationError, match="extra"):
            parse_methods_toml(toml)


# ===========================================================================
# Validation errors — [dependencies]
# ===========================================================================


class TestDependencyValidation:
    def test_dependency_not_a_table(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies]
            bad_dep = "not a table"
        """)
        with pytest.raises(ManifestValidationError, match="bad_dep"):
            parse_methods_toml(toml)

    def test_dependency_invalid_address(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies]
            my_dep = {address = "no-dot-slash", version = "1.0.0"}
        """)
        with pytest.raises(ManifestValidationError, match="address"):
            parse_methods_toml(toml)

    def test_dependency_invalid_version(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies]
            my_dep = {address = "github.com/acme/dep", version = "!!!"}
        """)
        with pytest.raises(ManifestValidationError, match="version"):
            parse_methods_toml(toml)

    def test_dependency_invalid_alias_not_snake_case(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies]
            MyDep = {address = "github.com/acme/dep", version = "1.0.0"}
        """)
        with pytest.raises(ManifestValidationError, match="alias"):
            parse_methods_toml(toml)

    def test_dependency_dict_keys_inherently_unique(self):
        """Dict keys are inherently unique — no duplicate alias validator needed."""
        manifest = MethodsManifest(
            address="github.com/acme/widgets",
            version="1.0.0",
            description="test",
            dependencies={
                "foo": PackageDependency(address="github.com/a/b", version="1.0.0"),
            },
        )
        assert len(manifest.dependencies) == 1

    def test_dependency_unknown_key(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies.my_dep]
            address = "github.com/acme/dep"
            version = "1.0.0"
            bogus = "field"
        """)
        with pytest.raises(ManifestValidationError):
            parse_methods_toml(toml)


# ===========================================================================
# Validation errors — [exports]
# ===========================================================================


class TestExportsValidation:
    def test_invalid_domain_path_not_snake_case(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.MyDomain]
            pipes = ["extract"]
        """)
        with pytest.raises(ManifestValidationError, match="domain"):
            parse_methods_toml(toml)

    def test_invalid_pipe_name_not_snake_case(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.legal]
            pipes = ["extractClause"]
        """)
        with pytest.raises(ManifestValidationError, match="pipe"):
            parse_methods_toml(toml)

    def test_reserved_domain_native(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.native.something]
            pipes = ["extract"]
        """)
        with pytest.raises(ManifestValidationError, match="reserved"):
            parse_methods_toml(toml)

    def test_reserved_domain_mthds(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.mthds]
            pipes = ["extract"]
        """)
        with pytest.raises(ManifestValidationError, match="reserved"):
            parse_methods_toml(toml)

    def test_reserved_domain_pipelex(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.pipelex.something]
            pipes = ["extract"]
        """)
        with pytest.raises(ManifestValidationError, match="reserved"):
            parse_methods_toml(toml)

    def test_pipes_not_a_list(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports.legal]
            pipes = "not_a_list"
        """)
        with pytest.raises(ManifestValidationError, match="pipes"):
            parse_methods_toml(toml)


# ===========================================================================
# Serialization
# ===========================================================================


class TestSerializeManifest:
    def test_serialized_contains_package_section(self):
        manifest = parse_methods_toml(MINIMAL_TOML)
        output = serialize_manifest_to_toml(manifest)
        assert "[package]" in output
        assert 'address = "github.com/acme/widgets"' in output

    def test_serialized_omits_empty_optional_fields(self):
        manifest = parse_methods_toml(MINIMAL_TOML)
        output = serialize_manifest_to_toml(manifest)
        assert "display_name" not in output
        assert "license" not in output
        assert "mthds_version" not in output
        assert "[dependencies]" not in output
        assert "[exports" not in output

    def test_serialized_includes_dependencies_and_exports(self):
        manifest = parse_methods_toml(FULL_TOML)
        output = serialize_manifest_to_toml(manifest)
        assert "[dependencies]" in output
        assert "foo_pkg" in output
        assert "[exports" in output
        assert "extract_clause" in output


# ===========================================================================
# Edge cases and semver variants
# ===========================================================================


class TestEdgeCases:
    @pytest.mark.parametrize(
        "version",
        [
            "0.0.0",
            "1.0.0",
            "10.20.30",
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0+build.123",
            "1.0.0-beta.1+build.456",
        ],
    )
    def test_valid_semver_versions(self, version: str):
        toml = textwrap.dedent(f"""\
            [package]
            address = "github.com/acme/widgets"
            version = "{version}"
            description = "test"
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.version == version

    @pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "1.0.0.0", "latest"])
    def test_invalid_semver_versions(self, version: str):
        toml = textwrap.dedent(f"""\
            [package]
            address = "github.com/acme/widgets"
            version = "{version}"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError):
            parse_methods_toml(toml)

    @pytest.mark.parametrize(
        "constraint",
        ["1.0.0", "^1.0.0", "~1.0.0", ">=1.0.0", ">=1.0.0, <2.0.0", "*", "1.*"],
    )
    def test_valid_version_constraints_in_dependencies(self, constraint: str):
        toml = textwrap.dedent(f"""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies]
            dep = {{address = "github.com/acme/dep", version = "{constraint}"}}
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.dependencies["dep"].version == constraint

    def test_empty_exports_section(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [exports]
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.exports == {}

    def test_empty_dependencies_section(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"

            [dependencies]
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.dependencies == {}


# ===========================================================================
# Name validation
# ===========================================================================


class TestNameValidation:
    @pytest.mark.parametrize(
        "name",
        [
            "ab",
            "my-method",
            "my_method",
            "a1",
            "legal-contracts",
            "a" * 25,
            "method123",
            "a-b_c",
        ],
    )
    def test_valid_names(self, name: str):
        assert is_valid_method_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "a",
            "A",
            "1abc",
            "-abc",
            "_abc",
            "My-Method",
            "a" * 26,
            "",
            "ab cd",
            "ab.cd",
        ],
    )
    def test_invalid_names(self, name: str):
        assert not is_valid_method_name(name)

    def test_name_in_manifest(self):
        toml = textwrap.dedent("""\
            [package]
            name = "my-method"
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.name == "my-method"

    def test_invalid_name_in_manifest(self):
        toml = textwrap.dedent("""\
            [package]
            name = "My Method!"
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
        """)
        with pytest.raises(ManifestValidationError, match="method name"):
            parse_methods_toml(toml)

    def test_manifest_without_name_backward_compat(self):
        """Manifests without a name field should still parse (name is optional)."""
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "A package without a name"
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.name is None
        assert manifest.address == "github.com/acme/widgets"


# ===========================================================================
# Main pipe validation
# ===========================================================================


class TestMainPipeValidation:
    def test_valid_main_pipe(self):
        toml = textwrap.dedent("""\
            [package]
            name = "my-method"
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
            main_pipe = "extract_clause"
        """)
        manifest = parse_methods_toml(toml)
        assert manifest.main_pipe == "extract_clause"

    def test_invalid_main_pipe(self):
        toml = textwrap.dedent("""\
            [package]
            name = "my-method"
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
            main_pipe = "extractClause"
        """)
        with pytest.raises(ManifestValidationError, match="main_pipe"):
            parse_methods_toml(toml)

    def test_main_pipe_none_by_default(self):
        manifest = parse_methods_toml(MINIMAL_TOML)
        assert manifest.main_pipe is None

    def test_serialized_includes_name_and_main_pipe(self):
        manifest = parse_methods_toml(FULL_TOML)
        output = serialize_manifest_to_toml(manifest)
        assert 'name = "acme-widgets"' in output
        assert 'main_pipe = "extract_clause"' in output

    def test_serialized_omits_name_and_main_pipe_when_none(self):
        toml = textwrap.dedent("""\
            [package]
            address = "github.com/acme/widgets"
            version = "1.0.0"
            description = "test"
        """)
        manifest = parse_methods_toml(toml)
        output = serialize_manifest_to_toml(manifest)
        assert "name" not in output
        assert "main_pipe" not in output
