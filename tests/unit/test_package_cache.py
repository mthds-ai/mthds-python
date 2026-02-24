from pathlib import Path

import pytest

from mthds.package.exceptions import PackageCacheError
from mthds.package.package_cache import (
    get_cached_package_path,
    get_default_cache_root,
    is_cached,
    remove_cached_package,
    store_in_cache,
)


class TestPackageCache:
    """Tests for the mthds.package.package_cache module — all use tmp_path."""

    # --- get_default_cache_root ---

    def test_get_default_cache_root(self):
        root = get_default_cache_root()
        assert root.parts[-2:] == (".mthds", "packages")

    # --- get_cached_package_path ---

    def test_get_cached_package_path_valid(self, tmp_path: Path):
        result = get_cached_package_path("github.com/org/repo", "1.0.0", tmp_path)
        assert result == (tmp_path / "github.com/org/repo" / "1.0.0").resolve()

    def test_get_cached_package_path_traversal_address(self, tmp_path: Path):
        with pytest.raises(PackageCacheError, match="Path traversal"):
            get_cached_package_path("../../etc/passwd", "1.0.0", tmp_path)

    def test_get_cached_package_path_traversal_version(self, tmp_path: Path):
        with pytest.raises(PackageCacheError, match="Path traversal"):
            get_cached_package_path("github.com/org/repo", "../../../../etc", tmp_path)

    # --- is_cached ---

    def test_is_cached_nonexistent(self, tmp_path: Path):
        assert is_cached("github.com/org/repo", "1.0.0", tmp_path) is False

    def test_is_cached_empty_dir(self, tmp_path: Path):
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        assert is_cached("github.com/org/repo", "1.0.0", tmp_path) is False

    def test_is_cached_dir_with_file(self, tmp_path: Path):
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        (pkg_path / "METHODS.toml").write_text("content")
        assert is_cached("github.com/org/repo", "1.0.0", tmp_path) is True

    # --- store_in_cache ---

    def test_store_in_cache_creates_cache(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        (source / "file.txt").write_text("hello")

        cache_root = tmp_path / "cache"
        result = store_in_cache(source, "github.com/org/repo", "1.0.0", cache_root)

        assert result.is_dir()
        assert (result / "file.txt").read_text() == "hello"

    def test_store_in_cache_strips_git(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        (source / "file.txt").write_text("hello")
        git_dir = source / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("git config")

        cache_root = tmp_path / "cache"
        result = store_in_cache(source, "github.com/org/repo", "1.0.0", cache_root)

        assert not (result / ".git").exists()
        assert (result / "file.txt").exists()

    def test_store_in_cache_idempotent(self, tmp_path: Path):
        """Second call overwrites without error."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "file.txt").write_text("v1")

        cache_root = tmp_path / "cache"
        store_in_cache(source, "github.com/org/repo", "1.0.0", cache_root)

        # Update source and store again
        (source / "file.txt").write_text("v2")
        result = store_in_cache(source, "github.com/org/repo", "1.0.0", cache_root)
        assert (result / "file.txt").read_text() == "v2"

    def test_store_in_cache_source_without_git(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        (source / "data.mthds").write_text("content")

        cache_root = tmp_path / "cache"
        result = store_in_cache(source, "github.com/org/repo", "2.0.0", cache_root)
        assert (result / "data.mthds").exists()

    # --- remove_cached_package ---

    def test_remove_cached_package_nonexistent(self, tmp_path: Path):
        result = remove_cached_package("github.com/org/repo", "1.0.0", tmp_path)
        assert result is False

    def test_remove_cached_package_existing(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        (source / "file.txt").write_text("data")
        cache_root = tmp_path / "cache"
        cached = store_in_cache(source, "github.com/org/repo", "1.0.0", cache_root)
        assert cached.exists()

        result = remove_cached_package("github.com/org/repo", "1.0.0", cache_root)
        assert result is True
        assert not cached.exists()
