import textwrap
from pathlib import Path

import pytest

from mthds.package.exceptions import ManifestError
from mthds.package.manifest.schema import DomainExports, MethodsManifest
from mthds.package.package_contents import MethodsPackage, make_package_from_directory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_MANIFEST_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "A test package"
""")

MANIFEST_WITH_EXPORTS_TOML = textwrap.dedent("""\
    [package]
    address = "github.com/acme/widgets"
    version = "1.0.0"
    description = "A test package"
    main_pipe = "extract_clause"

    [exports.legal]
    pipes = ["extract_clause", "summarize"]
""")


def _make_minimal_manifest() -> MethodsManifest:
    return MethodsManifest(
        address="github.com/acme/widgets",
        version="1.0.0",
        description="A test package",
    )


def _make_manifest_with_exports() -> MethodsManifest:
    return MethodsManifest(
        address="github.com/acme/widgets",
        version="1.0.0",
        description="A test package",
        main_pipe="extract_clause",
        exports={"legal": DomainExports(pipes=["extract_clause", "summarize"])},
    )


# ===========================================================================
# MethodsPackage model
# ===========================================================================


class TestMethodsPackage:
    def test_minimal_package(self):
        manifest = _make_minimal_manifest()
        package = MethodsPackage(manifest=manifest)
        assert package.manifest.address == "github.com/acme/widgets"
        assert package.mthds_files == []

    def test_package_with_mthds_files(self):
        manifest = _make_manifest_with_exports()
        package = MethodsPackage(
            manifest=manifest,
            mthds_files=["legal/contracts.mthds", "legal/compliance.mthds"],
        )
        assert len(package.mthds_files) == 2
        assert "legal/contracts.mthds" in package.mthds_files

    def test_package_extra_fields_forbidden(self):
        manifest = _make_minimal_manifest()
        with pytest.raises(Exception, match="extra"):
            MethodsPackage(manifest=manifest, unknown_field="value")  # type: ignore[call-arg]


# ===========================================================================
# make_package_from_directory
# ===========================================================================


class TestMakePackageFromDirectory:
    def test_minimal_package_no_mthds_files(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(MINIMAL_MANIFEST_TOML, encoding="utf-8")

        package = make_package_from_directory(tmp_path)
        assert package.manifest.address == "github.com/acme/widgets"
        assert package.mthds_files == []

    def test_discovers_mthds_files(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(MINIMAL_MANIFEST_TOML, encoding="utf-8")
        (tmp_path / "domain.mthds").write_text("", encoding="utf-8")
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "nested.mthds").write_text("", encoding="utf-8")

        package = make_package_from_directory(tmp_path)
        assert len(package.mthds_files) == 2
        assert "domain.mthds" in package.mthds_files
        assert "sub/nested.mthds" in package.mthds_files

    def test_mthds_files_are_sorted(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(MINIMAL_MANIFEST_TOML, encoding="utf-8")
        (tmp_path / "zebra.mthds").write_text("", encoding="utf-8")
        (tmp_path / "alpha.mthds").write_text("", encoding="utf-8")

        package = make_package_from_directory(tmp_path)
        assert package.mthds_files == ["alpha.mthds", "zebra.mthds"]

    def test_ignores_non_mthds_files(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(MINIMAL_MANIFEST_TOML, encoding="utf-8")
        (tmp_path / "readme.md").write_text("", encoding="utf-8")
        (tmp_path / "config.toml").write_text("", encoding="utf-8")
        (tmp_path / "domain.mthds").write_text("", encoding="utf-8")

        package = make_package_from_directory(tmp_path)
        assert package.mthds_files == ["domain.mthds"]

    def test_missing_manifest_raises(self, tmp_path: Path):
        with pytest.raises(ManifestError, match=r"METHODS\.toml"):
            make_package_from_directory(tmp_path)

    def test_manifest_with_exports_and_main_pipe(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(MANIFEST_WITH_EXPORTS_TOML, encoding="utf-8")
        (tmp_path / "legal.mthds").write_text("", encoding="utf-8")

        package = make_package_from_directory(tmp_path)
        assert package.manifest.main_pipe == "extract_clause"
        assert "extract_clause" in package.manifest.exports["legal"].pipes
        assert package.mthds_files == ["legal.mthds"]
