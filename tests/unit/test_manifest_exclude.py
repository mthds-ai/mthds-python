import textwrap

import pytest

from mthds.package.exceptions import ManifestValidationError
from mthds.package.manifest.parser import parse_methods_toml, serialize_manifest_to_toml

MANIFEST_WITH_EXCLUDE = textwrap.dedent("""\
    [package]
    address = "github.com/acme/invoice-letters"
    version = "1.0.0"
    description = "Invoice letters"
    exclude = ["samples/", "*.psd"]
""")


class TestManifestExclude:
    def test_exclude_is_read_and_written_back(self):
        """`[package] exclude` lists patterns in .gitignore syntax, kept in order, and survives a round trip."""
        manifest = parse_methods_toml(MANIFEST_WITH_EXCLUDE)
        assert manifest.exclude == ["samples/", "*.psd"]
        output = serialize_manifest_to_toml(manifest)
        assert 'exclude = ["samples/", "*.psd"]' in output
        assert parse_methods_toml(output).exclude == ["samples/", "*.psd"]

    def test_exclude_defaults_to_no_pattern_and_is_not_written(self):
        manifest = parse_methods_toml(MANIFEST_WITH_EXCLUDE.replace('exclude = ["samples/", "*.psd"]\n', ""))
        assert manifest.exclude == []
        assert "exclude" not in serialize_manifest_to_toml(manifest)

    @pytest.mark.parametrize(
        "pattern",
        [
            pytest.param("samples/\\n*.psd", id="a line feed"),
            pytest.param("samples/\\r", id="a carriage return"),
        ],
    )
    def test_exclude_pattern_with_a_line_break_is_refused(self, pattern: str):
        """Each entry is one pattern of one line, so an entry holding a line break is refused."""
        toml = MANIFEST_WITH_EXCLUDE.replace('["samples/", "*.psd"]', f'["{pattern}"]')
        with pytest.raises(ManifestValidationError, match="line break"):
            parse_methods_toml(toml)
