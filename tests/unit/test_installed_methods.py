import textwrap
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.package.exceptions import (
    AmbiguousPipeCodeError,
    DuplicateMethodNameError,
    MethodNotFoundError,
    PipeCodeNotFoundError,
)
from mthds.package.installed_methods import (
    InstalledMethod,
    discover_installed_methods,
    find_method_by_exported_pipe,
    find_method_by_name,
    get_all_exported_pipes,
)
from mthds.package.manifest.parser import parse_methods_toml

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

MANIFEST_WITH_EXPORTS = textwrap.dedent("""\
    [package]
    name = "legal-ai"
    address = "github.com/acme/legal-ai"
    version = "1.0.0"
    description = "Legal AI method"

    [exports.legal.contracts]
    pipes = ["extract_clause", "summarize"]

    [exports.finance]
    pipes = ["compute_tax"]
""")

MANIFEST_SIMPLE = textwrap.dedent("""\
    [package]
    name = "simple-method"
    address = "github.com/acme/simple"
    version = "0.1.0"
    description = "Simple method"

    [exports.general]
    pipes = ["hello_world"]
""")


def _make_method(name: str, manifest_toml: str, path: Path | None = None) -> InstalledMethod:
    """Create an InstalledMethod from a TOML string for testing."""
    manifest = parse_methods_toml(manifest_toml)
    return InstalledMethod(
        name=name,
        path=path or Path(f"/fake/methods/{name}"),
        manifest=manifest,
        mthds_files=[],
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestInstalledMethods:
    # -----------------------------------------------------------------------
    # get_all_exported_pipes
    # -----------------------------------------------------------------------

    def test_get_all_exported_pipes(self):
        method = _make_method("legal-ai", MANIFEST_WITH_EXPORTS)
        pipes = get_all_exported_pipes(method)
        assert pipes == {"extract_clause", "summarize", "compute_tax"}

    def test_get_all_exported_pipes_empty(self):
        toml = textwrap.dedent("""\
            [package]
            name = "no-exports"
            address = "github.com/acme/no-exports"
            version = "1.0.0"
            description = "No exports"
        """)
        method = _make_method("no-exports", toml)
        pipes = get_all_exported_pipes(method)
        assert pipes == set()

    # -----------------------------------------------------------------------
    # find_method_by_name
    # -----------------------------------------------------------------------

    def test_find_method_by_name_found(self):
        methods = [
            _make_method("legal-ai", MANIFEST_WITH_EXPORTS),
            _make_method("simple-method", MANIFEST_SIMPLE),
        ]
        result = find_method_by_name("legal-ai", methods=methods)
        assert result.name == "legal-ai"

    def test_find_method_by_name_not_found(self):
        methods = [_make_method("legal-ai", MANIFEST_WITH_EXPORTS)]
        with pytest.raises(MethodNotFoundError, match="nonexistent"):
            find_method_by_name("nonexistent", methods=methods)

    def test_find_method_by_name_duplicate(self):
        methods = [
            _make_method("legal-ai", MANIFEST_WITH_EXPORTS, path=Path("/a/legal-ai")),
            _make_method("legal-ai", MANIFEST_WITH_EXPORTS, path=Path("/b/legal-ai")),
        ]
        with pytest.raises(DuplicateMethodNameError, match="legal-ai"):
            find_method_by_name("legal-ai", methods=methods)

    # -----------------------------------------------------------------------
    # find_method_by_exported_pipe
    # -----------------------------------------------------------------------

    def test_find_method_by_exported_pipe_found(self):
        methods = [
            _make_method("legal-ai", MANIFEST_WITH_EXPORTS),
            _make_method("simple-method", MANIFEST_SIMPLE),
        ]
        result = find_method_by_exported_pipe("extract_clause", methods=methods)
        assert result.name == "legal-ai"

    def test_find_method_by_exported_pipe_not_found(self):
        methods = [_make_method("legal-ai", MANIFEST_WITH_EXPORTS)]
        with pytest.raises(PipeCodeNotFoundError, match="nonexistent_pipe"):
            find_method_by_exported_pipe("nonexistent_pipe", methods=methods)

    def test_find_method_by_exported_pipe_ambiguous(self):
        """Two methods export the same pipe code."""
        toml_dup = textwrap.dedent("""\
            [package]
            name = "other-method"
            address = "github.com/acme/other"
            version = "1.0.0"
            description = "Other method"

            [exports.legal]
            pipes = ["extract_clause"]
        """)
        methods = [
            _make_method("legal-ai", MANIFEST_WITH_EXPORTS),
            _make_method("other-method", toml_dup),
        ]
        with pytest.raises(AmbiguousPipeCodeError, match="extract_clause"):
            find_method_by_exported_pipe("extract_clause", methods=methods)

    # -----------------------------------------------------------------------
    # discover_installed_methods (with mock filesystem)
    # -----------------------------------------------------------------------

    def test_discover_installed_methods_empty(self, tmp_path: Path, mocker: MockerFixture):
        """No methods directories exist."""
        mocker.patch(
            "mthds.package.installed_methods.GLOBAL_METHODS_DIR",
            tmp_path / "global" / "methods",
        )
        mocker.patch(
            "mthds.package.installed_methods.PROJECT_METHODS_DIR",
            tmp_path / "project" / "methods",
        )
        methods = discover_installed_methods()
        assert methods == []

    def test_discover_installed_methods_finds_methods(self, tmp_path: Path, mocker: MockerFixture):
        """Discover a method from the global directory."""
        global_dir = tmp_path / "global" / "methods"
        global_dir.mkdir(parents=True)

        method_dir = global_dir / "legal-ai"
        method_dir.mkdir()
        (method_dir / "METHODS.toml").write_text(MANIFEST_WITH_EXPORTS)
        (method_dir / "bundle.mthds").write_text("fake bundle")

        mocker.patch("mthds.package.installed_methods.GLOBAL_METHODS_DIR", global_dir)
        mocker.patch(
            "mthds.package.installed_methods.PROJECT_METHODS_DIR",
            tmp_path / "project" / "methods",
        )

        methods = discover_installed_methods()
        assert len(methods) == 1
        assert methods[0].name == "legal-ai"
        assert len(methods[0].mthds_files) == 1
        assert methods[0].mthds_files[0].name == "bundle.mthds"

    def test_discover_installed_methods_project_priority(self, tmp_path: Path, mocker: MockerFixture):
        """Both global and project methods are discovered."""
        global_dir = tmp_path / "global" / "methods"
        global_dir.mkdir(parents=True)
        project_dir = tmp_path / "project" / "methods"
        project_dir.mkdir(parents=True)

        # Global method
        global_method = global_dir / "legal-ai"
        global_method.mkdir()
        (global_method / "METHODS.toml").write_text(MANIFEST_WITH_EXPORTS)

        # Project method
        project_method = project_dir / "simple-method"
        project_method.mkdir()
        (project_method / "METHODS.toml").write_text(MANIFEST_SIMPLE)

        mocker.patch("mthds.package.installed_methods.GLOBAL_METHODS_DIR", global_dir)
        mocker.patch("mthds.package.installed_methods.PROJECT_METHODS_DIR", project_dir)

        methods = discover_installed_methods()
        assert len(methods) == 2
        names = {method.name for method in methods}
        assert names == {"legal-ai", "simple-method"}

    def test_discover_skips_directories_without_manifest(self, tmp_path: Path, mocker: MockerFixture):
        """Directories without METHODS.toml are skipped."""
        global_dir = tmp_path / "global" / "methods"
        global_dir.mkdir(parents=True)

        (global_dir / "no-manifest").mkdir()
        (global_dir / "no-manifest" / "bundle.mthds").write_text("fake")

        mocker.patch("mthds.package.installed_methods.GLOBAL_METHODS_DIR", global_dir)
        mocker.patch(
            "mthds.package.installed_methods.PROJECT_METHODS_DIR",
            tmp_path / "project" / "methods",
        )

        methods = discover_installed_methods()
        assert methods == []
