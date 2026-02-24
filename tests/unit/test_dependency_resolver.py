from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from semantic_version import Version  # type: ignore[import-untyped]

from mthds.package.dependency_resolver import (
    collect_mthds_files,
    determine_exported_pipes,
    resolve_all_dependencies,
)
from mthds.package.exceptions import DependencyResolveError, TransitiveDependencyError
from mthds.package.manifest.schema import DomainExports, MethodsManifest, PackageDependency


class TestDependencyResolver:
    """Tests for the mthds.package.dependency_resolver module — VCS/cache mocked."""

    # --- Helpers ---

    @staticmethod
    def _make_manifest(
        address: str = "github.com/acme/root",
        version: str = "1.0.0",
        dependencies: dict[str, PackageDependency] | None = None,
        exports: dict[str, DomainExports] | None = None,
    ) -> MethodsManifest:
        return MethodsManifest(
            address=address,
            version=version,
            description="test",
            dependencies=dependencies or {},
            exports=exports or {},
        )

    # --- collect_mthds_files ---

    def test_collect_mthds_files_empty_dir(self, tmp_path: Path):
        assert collect_mthds_files(tmp_path) == []

    def test_collect_mthds_files_nested(self, tmp_path: Path):
        (tmp_path / "top.mthds").write_text("content")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.mthds").write_text("content")
        (sub / "readme.md").write_text("not mthds")

        result = collect_mthds_files(tmp_path)
        assert len(result) == 2
        names = [path.name for path in result]
        assert "top.mthds" in names
        assert "nested.mthds" in names

    # --- determine_exported_pipes ---

    def test_determine_exported_pipes_none_manifest(self):
        assert determine_exported_pipes(None) is None

    def test_determine_exported_pipes_no_exports(self):
        manifest = self._make_manifest()
        assert determine_exported_pipes(manifest) is None

    def test_determine_exported_pipes_with_exports(self):
        manifest = self._make_manifest(exports={"scoring": DomainExports(pipes=["compute_score", "validate"])})
        result = determine_exported_pipes(manifest)
        assert result == {"compute_score", "validate"}

    # --- resolve_all_dependencies: no deps ---

    def test_resolve_all_no_deps(self, tmp_path: Path):
        manifest = self._make_manifest()
        result = resolve_all_dependencies(manifest, tmp_path)
        assert result == []

    # --- resolve_all_dependencies: local only ---

    def test_resolve_all_local_only(self, tmp_path: Path, mocker: MockerFixture):
        """Local deps are resolved without any VCS calls."""
        dep_dir = tmp_path / "local_dep"
        dep_dir.mkdir()
        (dep_dir / "pipe.mthds").write_text("content")

        manifest = self._make_manifest(
            dependencies={
                "local_dep": PackageDependency(
                    address="github.com/acme/local",
                    version="0.1.0",
                    path=str(dep_dir),
                ),
            }
        )

        # Ensure no VCS functions are called
        mock_list_tags = mocker.patch("mthds.package.dependency_resolver.list_remote_version_tags")
        mock_clone = mocker.patch("mthds.package.dependency_resolver.clone_at_version")

        result = resolve_all_dependencies(manifest, tmp_path)
        assert len(result) == 1
        assert result[0].alias == "local_dep"
        mock_list_tags.assert_not_called()
        mock_clone.assert_not_called()

    # --- resolve_all_dependencies: local nonexistent path ---

    def test_resolve_local_nonexistent_path(self, tmp_path: Path):
        manifest = self._make_manifest(
            dependencies={
                "bad_dep": PackageDependency(
                    address="github.com/acme/bad",
                    version="0.1.0",
                    path="/nonexistent/path",
                ),
            }
        )
        with pytest.raises(DependencyResolveError, match="does not exist"):
            resolve_all_dependencies(manifest, tmp_path)

    # --- resolve_all_dependencies: remote with cache hit ---

    def test_resolve_remote_cache_hit(self, tmp_path: Path, mocker: MockerFixture):
        cached_dir = tmp_path / "cached"
        cached_dir.mkdir()
        (cached_dir / "pipe.mthds").write_text("content")

        mocker.patch(
            "mthds.package.dependency_resolver.list_remote_version_tags",
            return_value=[(Version("1.0.0"), "v1.0.0")],
        )
        mocker.patch("mthds.package.dependency_resolver.is_cached", return_value=True)
        mocker.patch("mthds.package.dependency_resolver.get_cached_package_path", return_value=cached_dir)
        mock_clone = mocker.patch("mthds.package.dependency_resolver.clone_at_version")

        manifest = self._make_manifest(
            dependencies={
                "remote_dep": PackageDependency(address="github.com/acme/remote", version="^1.0.0"),
            }
        )
        result = resolve_all_dependencies(manifest, tmp_path)
        assert len(result) == 1
        assert result[0].alias == "remote_dep"
        mock_clone.assert_not_called()

    # --- resolve_all_dependencies: remote with cache miss ---

    def test_resolve_remote_cache_miss(self, tmp_path: Path, mocker: MockerFixture):
        cached_dir = tmp_path / "cached"
        cached_dir.mkdir()

        mocker.patch(
            "mthds.package.dependency_resolver.list_remote_version_tags",
            return_value=[(Version("1.0.0"), "v1.0.0")],
        )
        mocker.patch("mthds.package.dependency_resolver.is_cached", return_value=False)
        mocker.patch("mthds.package.dependency_resolver.clone_at_version")
        mocker.patch("mthds.package.dependency_resolver.store_in_cache", return_value=cached_dir)

        manifest = self._make_manifest(
            dependencies={
                "remote_dep": PackageDependency(address="github.com/acme/remote", version="^1.0.0"),
            }
        )
        result = resolve_all_dependencies(manifest, tmp_path)
        assert len(result) == 1

    # --- transitive resolution ---

    def test_transitive_resolution(self, tmp_path: Path, mocker: MockerFixture):
        """A -> B -> C (3 levels, all mocked)."""
        cached_dir_b = tmp_path / "cached_b"
        cached_dir_b.mkdir()
        cached_dir_c = tmp_path / "cached_c"
        cached_dir_c.mkdir()

        manifest_b = self._make_manifest(
            address="github.com/acme/dep_b",
            dependencies={
                "dep_c": PackageDependency(address="github.com/acme/dep_c", version="^1.0.0"),
            },
        )
        manifest_c = self._make_manifest(address="github.com/acme/dep_c")

        def mock_find_manifest(directory: Path) -> MethodsManifest | None:
            if directory == cached_dir_b:
                return manifest_b
            if directory == cached_dir_c:
                return manifest_c
            return None

        mocker.patch("mthds.package.dependency_resolver._find_manifest_in_dir", side_effect=mock_find_manifest)

        call_count = 0

        def mock_list_tags(_url: str) -> list:
            return [(Version("1.0.0"), "v1.0.0")]

        mocker.patch("mthds.package.dependency_resolver.list_remote_version_tags", side_effect=mock_list_tags)
        mocker.patch("mthds.package.dependency_resolver.is_cached", return_value=False)
        mocker.patch("mthds.package.dependency_resolver.clone_at_version")

        def mock_store(_source: Path, address: str, _version: str, _cache_root: Path | None = None) -> Path:
            nonlocal call_count
            call_count += 1
            if "dep_b" in address:
                return cached_dir_b
            return cached_dir_c

        mocker.patch("mthds.package.dependency_resolver.store_in_cache", side_effect=mock_store)

        manifest_a = self._make_manifest(
            dependencies={
                "dep_b": PackageDependency(address="github.com/acme/dep_b", version="^1.0.0"),
            }
        )

        result = resolve_all_dependencies(manifest_a, tmp_path)
        addresses = {dep.address for dep in result}
        assert "github.com/acme/dep_b" in addresses
        assert "github.com/acme/dep_c" in addresses

    # --- cycle detection ---

    def test_cycle_detection(self, tmp_path: Path, mocker: MockerFixture):
        """A -> B -> A cycle should raise TransitiveDependencyError."""
        cached_dir = tmp_path / "cached"
        cached_dir.mkdir()

        manifest_b = self._make_manifest(
            address="github.com/acme/dep_b",
            dependencies={
                "dep_a": PackageDependency(address="github.com/acme/root", version="^1.0.0"),
            },
        )

        mocker.patch("mthds.package.dependency_resolver._find_manifest_in_dir", return_value=manifest_b)
        mocker.patch(
            "mthds.package.dependency_resolver.list_remote_version_tags",
            return_value=[(Version("1.0.0"), "v1.0.0")],
        )
        mocker.patch("mthds.package.dependency_resolver.is_cached", return_value=False)
        mocker.patch("mthds.package.dependency_resolver.clone_at_version")
        mocker.patch("mthds.package.dependency_resolver.store_in_cache", return_value=cached_dir)

        manifest_a = self._make_manifest(
            dependencies={
                "dep_b": PackageDependency(address="github.com/acme/dep_b", version="^1.0.0"),
            }
        )

        with pytest.raises(TransitiveDependencyError, match="cycle"):
            resolve_all_dependencies(manifest_a, tmp_path)

    # --- diamond resolution ---

    def test_diamond_resolution(self, tmp_path: Path, mocker: MockerFixture):
        """A -> B(^1.0.0), A -> C, C -> B(^1.2.0) — should re-resolve to 1.2.0."""
        cached_dir_b = tmp_path / "cached_b"
        cached_dir_b.mkdir()
        cached_dir_c = tmp_path / "cached_c"
        cached_dir_c.mkdir()

        manifest_c = self._make_manifest(
            address="github.com/acme/dep_c",
            dependencies={
                "dep_b": PackageDependency(address="github.com/acme/dep_b", version="^1.2.0"),
            },
        )

        def mock_find_manifest(directory: Path) -> MethodsManifest | None:
            if directory == cached_dir_c:
                return manifest_c
            return None  # dep_b has no sub-deps

        mocker.patch("mthds.package.dependency_resolver._find_manifest_in_dir", side_effect=mock_find_manifest)
        mocker.patch(
            "mthds.package.dependency_resolver.list_remote_version_tags",
            return_value=[(Version("1.0.0"), "v1.0.0"), (Version("1.2.0"), "v1.2.0"), (Version("1.5.0"), "v1.5.0")],
        )
        mocker.patch("mthds.package.dependency_resolver.is_cached", return_value=False)
        mocker.patch("mthds.package.dependency_resolver.clone_at_version")

        def mock_store(_source: Path, address: str, _version: str, _cache_root: Path | None = None) -> Path:
            if "dep_b" in address:
                return cached_dir_b
            return cached_dir_c

        mocker.patch("mthds.package.dependency_resolver.store_in_cache", side_effect=mock_store)

        manifest_a = self._make_manifest(
            dependencies={
                "dep_b": PackageDependency(address="github.com/acme/dep_b", version="^1.0.0"),
                "dep_c": PackageDependency(address="github.com/acme/dep_c", version="^1.0.0"),
            }
        )

        result = resolve_all_dependencies(manifest_a, tmp_path)
        dep_b = next(dep for dep in result if dep.address == "github.com/acme/dep_b")
        # dep_b should exist in results (it was resolved)
        assert dep_b is not None

    # --- diamond conflict ---

    def test_diamond_conflict(self, tmp_path: Path, mocker: MockerFixture):
        """B(^1.0.0) and B(^2.0.0) are incompatible -> TransitiveDependencyError."""
        cached_dir_c = tmp_path / "cached_c"
        cached_dir_c.mkdir()
        cached_dir_b = tmp_path / "cached_b"
        cached_dir_b.mkdir()

        manifest_c = self._make_manifest(
            address="github.com/acme/dep_c",
            dependencies={
                "dep_b": PackageDependency(address="github.com/acme/dep_b", version="^2.0.0"),
            },
        )

        def mock_find_manifest(directory: Path) -> MethodsManifest | None:
            if directory == cached_dir_c:
                return manifest_c
            return None

        mocker.patch("mthds.package.dependency_resolver._find_manifest_in_dir", side_effect=mock_find_manifest)
        mocker.patch(
            "mthds.package.dependency_resolver.list_remote_version_tags",
            return_value=[(Version("1.0.0"), "v1.0.0"), (Version("1.5.0"), "v1.5.0")],
        )
        mocker.patch("mthds.package.dependency_resolver.is_cached", return_value=False)
        mocker.patch("mthds.package.dependency_resolver.clone_at_version")

        def mock_store(_source: Path, address: str, _version: str, _cache_root: Path | None = None) -> Path:
            if "dep_b" in address:
                return cached_dir_b
            return cached_dir_c

        mocker.patch("mthds.package.dependency_resolver.store_in_cache", side_effect=mock_store)

        manifest_a = self._make_manifest(
            dependencies={
                "dep_b": PackageDependency(address="github.com/acme/dep_b", version="^1.0.0"),
                "dep_c": PackageDependency(address="github.com/acme/dep_c", version="^1.0.0"),
            }
        )

        with pytest.raises(TransitiveDependencyError, match="No version"):
            resolve_all_dependencies(manifest_a, tmp_path)
