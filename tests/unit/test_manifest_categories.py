import re
import textwrap

import pytest
from pydantic import ValidationError

from mthds.package.exceptions import ManifestValidationError
from mthds.package.manifest.parser import parse_methods_toml, serialize_manifest_to_toml
from mthds.package.manifest.schema import MethodsManifest, is_mthds_version_satisfied

MANIFEST_WITHOUT_CATEGORIES = textwrap.dedent("""\
    [package]
    address = "github.com/acme/legal-tools"
    version = "0.3.0"
    description = "Legal document analysis"
""")

# The complete example of the standard's manifest format, as `v8.1.0` publishes it.
STANDARD_COMPLETE_EXAMPLE = textwrap.dedent("""\
    [package]
    name          = "nda_analyzer"
    address       = "github.com/acme/legal-tools"
    display_name  = "Legal Tools"
    version       = "0.3.0"
    description   = "Legal document analysis and contract review methods."
    authors       = ["ACME Legal Tech <legal@acme.com>"]
    license       = "MIT"
    mthds_version = ">=8.1.0"
    main_pipe     = "analyze_nda"
    exclude       = ["drafts/"]
    categories    = ["legal", "compliance"]

    [exports.legal]
    pipes = ["classify_document"]

    [exports.legal.contracts]
    pipes = ["extract_clause", "analyze_nda", "compare_contracts"]

    [exports.scoring]
    pipes = ["compute_weighted_score"]
""")


def _manifest_declaring(categories_toml: str) -> str:
    """A manifest whose `categories` key holds the given TOML value, written as is."""
    return f"{MANIFEST_WITHOUT_CATEGORIES}categories = {categories_toml}\n"


class TestManifestCategories:
    def test_categories_are_read_and_written_back(self):
        """A manifest declaring categories parses, and a rewrite carries them."""
        manifest = parse_methods_toml(_manifest_declaring('["legal", "customer-support", "3d-printing"]'))
        assert manifest.categories == ["legal", "customer-support", "3d-printing"]
        output = serialize_manifest_to_toml(manifest)
        assert 'categories = ["legal", "customer-support", "3d-printing"]' in output
        assert parse_methods_toml(output).categories == ["legal", "customer-support", "3d-printing"]

    def test_the_standards_complete_example_parses(self):
        """The example the standard publishes reads as written, and this library implements the standard it asks for."""
        manifest = parse_methods_toml(STANDARD_COMPLETE_EXAMPLE)
        assert manifest.categories == ["legal", "compliance"]
        assert manifest.exclude == ["drafts/"]
        assert manifest.mthds_version is not None
        assert is_mthds_version_satisfied(manifest.mthds_version)

    @pytest.mark.parametrize(
        "toml",
        [
            pytest.param(MANIFEST_WITHOUT_CATEGORIES, id="the key left out"),
            pytest.param(_manifest_declaring("[]"), id="an empty array"),
        ],
    )
    def test_no_category_is_declared_by_an_empty_array_as_by_leaving_the_key_out(self, toml: str):
        """An empty array declares what leaving the field out declares, so the two read alike and neither is written back."""
        manifest = parse_methods_toml(toml)
        assert manifest.categories == []
        assert manifest == parse_methods_toml(MANIFEST_WITHOUT_CATEGORIES)
        assert "categories" not in serialize_manifest_to_toml(manifest)

    @pytest.mark.parametrize(
        ("toml_value", "as_written"),
        [
            pytest.param('["legal", "legal"]', ["legal", "legal"], id="an entry repeated"),
            pytest.param('["sales", "legal", "sales"]', ["sales", "legal", "sales"], id="an entry repeated around another"),
            pytest.param('["sales", "legal"]', ["sales", "legal"], id="entries out of alphabetical order"),
        ],
    )
    def test_repeats_and_order_are_accepted_and_carried_as_written(self, toml_value: str, as_written: list[str]):
        """Repeats and order mean nothing, so nothing refuses them, and a tool rewriting the manifest leaves them as written."""
        manifest = parse_methods_toml(_manifest_declaring(toml_value))
        assert manifest.categories == as_written
        output = serialize_manifest_to_toml(manifest)
        assert f"categories = {toml_value}" in output
        assert parse_methods_toml(output).categories == as_written

    @pytest.mark.parametrize(
        "category",
        [
            pytest.param("a-value-no-catalog-lists", id="a value no catalog lists"),
            pytest.param("x", id="a single letter"),
            pytest.param("7", id="a single digit"),
            pytest.param("2026", id="digits alone"),
            pytest.param("3d-printing", id="a leading digit"),
            pytest.param("a-1-b-2", id="several hyphens"),
        ],
    )
    def test_an_unknown_value_matching_the_pattern_is_accepted(self, category: str):
        """The standard lists no values, so a value is refused for its form and never for being unknown."""
        assert parse_methods_toml(_manifest_declaring(f'["{category}"]')).categories == [category]

    @pytest.mark.parametrize(
        ("toml_entry", "refused"),
        [
            pytest.param('"Legal"', "Legal", id="an uppercase letter"),
            pytest.param('"customer_support"', "customer_support", id="an underscore"),
            pytest.param('"customer--support"', "customer--support", id="a doubled hyphen"),
            pytest.param('"-legal"', "-legal", id="a leading hyphen"),
            pytest.param('"legal-"', "legal-", id="a trailing hyphen"),
            pytest.param('"-"', "-", id="a hyphen alone"),
            pytest.param('""', "", id="an empty string"),
            pytest.param('"customer support"', "customer support", id="a space inside"),
            pytest.param('" legal"', " legal", id="a leading space"),
            pytest.param('"legal "', "legal ", id="a trailing space"),
            pytest.param('"legal\\n"', "legal\n", id="a trailing line feed, which a dollar sign alone would let through"),
            pytest.param('"\\nlegal"', "\nlegal", id="a leading line feed"),
            pytest.param('"legal\\nsales"', "legal\nsales", id="a line feed inside"),
            pytest.param('"legal\\r\\n"', "legal\r\n", id="a trailing carriage return and line feed"),
            pytest.param('"legal.contracts"', "legal.contracts", id="a dot"),
            pytest.param('"légal"', "légal", id="a lowercase letter outside ASCII"),
            pytest.param('"٣d"', "٣d", id="a digit outside ASCII"),
        ],
    )
    def test_an_entry_breaking_the_pattern_refuses_the_manifest(self, toml_entry: str, refused: str):
        """A manifest holding an entry that does not match the pattern as a whole is invalid, and the refusal names the entry."""
        with pytest.raises(ManifestValidationError, match=re.escape(f"Invalid category {refused!r}")):
            parse_methods_toml(_manifest_declaring(f"[{toml_entry}]"))

    def test_one_bad_entry_among_good_ones_refuses_the_manifest(self):
        with pytest.raises(ManifestValidationError, match=re.escape("Invalid category 'Sales'")):
            parse_methods_toml(_manifest_declaring('["legal", "Sales", "compliance"]'))

    @pytest.mark.parametrize(
        "toml_value",
        [
            pytest.param('"legal"', id="a string rather than an array"),
            pytest.param("1", id="an integer rather than an array"),
            pytest.param("true", id="a boolean rather than an array"),
            pytest.param("{ legal = true }", id="a table rather than an array"),
            pytest.param("[1]", id="an integer entry"),
            pytest.param("[1.5]", id="a float entry"),
            pytest.param("[true]", id="a boolean entry"),
            pytest.param("[2026-11-06]", id="a date entry"),
            pytest.param('[["legal"]]', id="an array entry"),
            pytest.param("[{ name = 'legal' }]", id="a table entry"),
            pytest.param('["legal", 1]', id="an integer entry among strings"),
        ],
    )
    def test_a_value_that_is_not_an_array_of_strings_refuses_the_manifest(self, toml_value: str):
        """`categories` is an array of strings, and nothing is coerced into one."""
        with pytest.raises(ManifestValidationError, match="categories"):
            parse_methods_toml(_manifest_declaring(toml_value))

    def test_direct_construction_validates_the_same_way(self):
        """A manifest built in code obeys the same rule as one read from TOML."""
        built = MethodsManifest(address="github.com/acme/legal-tools", version="0.3.0", description="Legal", categories=["legal", "legal"])
        assert built.categories == ["legal", "legal"]
        with pytest.raises(ValidationError, match=re.escape("Invalid category 'Legal'")):
            MethodsManifest(address="github.com/acme/legal-tools", version="0.3.0", description="Legal", categories=["Legal"])
