import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from mthds.package.dependency_resolver import PackageDependency, ResolvedDependency
from mthds.package.exceptions import IntegrityError, LockFileError
from mthds.package.lock_file import (
    LockedPackage,
    LockFile,
    compute_directory_hash,
    generate_lock_file,
    parse_lock_file,
    serialize_lock_file,
    verify_lock_file,
    verify_locked_package,
)
from mthds.package.manifest.schema import MethodsManifest


class TestLockFile:
    """Tests for the mthds.package.lock_file module."""

    # --- LockedPackage validation ---

    def test_locked_package_valid(self):
        locked = LockedPackage(
            version="1.0.0",
            hash="sha256:" + "a" * 64,
            source="https://github.com/org/repo",
        )
        assert locked.version == "1.0.0"

    @pytest.mark.parametrize(
        "bad_hash",
        [
            "sha256:" + "a" * 63,
            "sha256:" + "A" * 64,
            "md5:" + "a" * 64,
            "tooshort",
        ],
    )
    def test_locked_package_invalid_hash(self, bad_hash: str):
        with pytest.raises(ValidationError, match="hash"):
            LockedPackage(version="1.0.0", hash=bad_hash, source="https://example.com")

    def test_locked_package_invalid_source(self):
        with pytest.raises(ValidationError, match="source"):
            LockedPackage(version="1.0.0", hash="sha256:" + "a" * 64, source="http://not-https.com")

    def test_locked_package_invalid_version(self):
        with pytest.raises(ValidationError, match="version"):
            LockedPackage(version="^1.0.0", hash="sha256:" + "a" * 64, source="https://example.com")

    # --- compute_directory_hash ---

    def test_compute_directory_hash_known_content(self, tmp_path: Path):
        (tmp_path / "file.txt").write_text("hello")
        hash1 = compute_directory_hash(tmp_path)
        assert hash1.startswith("sha256:")
        assert len(hash1) == len("sha256:") + 64

        # Same content -> same hash
        hash2 = compute_directory_hash(tmp_path)
        assert hash1 == hash2

    def test_compute_directory_hash_excludes_git(self, tmp_path: Path):
        (tmp_path / "file.txt").write_text("hello")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("git stuff")

        hash_with_git = compute_directory_hash(tmp_path)

        # Remove .git and compute again
        shutil.rmtree(git_dir)
        hash_without_git = compute_directory_hash(tmp_path)

        assert hash_with_git == hash_without_git

    def test_compute_directory_hash_nonexistent_dir(self, tmp_path: Path):
        with pytest.raises(LockFileError, match="does not exist"):
            compute_directory_hash(tmp_path / "nonexistent")

    def test_compute_directory_hash_empty_dir(self, tmp_path: Path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = compute_directory_hash(empty_dir)
        assert result.startswith("sha256:")

    # --- parse_lock_file ---

    def test_parse_lock_file_empty(self):
        result = parse_lock_file("")
        assert result.packages == {}

    def test_parse_lock_file_whitespace_only(self):
        result = parse_lock_file("   \n  \n  ")
        assert result.packages == {}

    def test_parse_lock_file_valid(self):
        toml_content = '["github.com/org/repo"]\nversion = "1.0.0"\nhash = "sha256:' + "a" * 64 + '"\nsource = "https://github.com/org/repo"\n'
        result = parse_lock_file(toml_content)
        assert "github.com/org/repo" in result.packages
        assert result.packages["github.com/org/repo"].version == "1.0.0"

    def test_parse_lock_file_non_dict_entry(self):
        toml_content = '"github.com/org/repo" = "not a table"\n'
        with pytest.raises(LockFileError, match="must be a table"):
            parse_lock_file(toml_content)

    def test_parse_lock_file_invalid_hash(self):
        toml_content = '["github.com/org/repo"]\nversion = "1.0.0"\nhash = "bad_hash"\nsource = "https://github.com/org/repo"\n'
        with pytest.raises(LockFileError, match="Invalid lock file entry"):
            parse_lock_file(toml_content)

    def test_parse_lock_file_bad_toml_syntax(self):
        with pytest.raises(LockFileError, match="Invalid TOML"):
            parse_lock_file("[broken\ntoml")

    # --- serialize_lock_file ---

    def test_serialize_lock_file_sorted(self):
        packages = {
            "github.com/z/repo": LockedPackage(
                version="2.0.0",
                hash="sha256:" + "b" * 64,
                source="https://github.com/z/repo",
            ),
            "github.com/a/repo": LockedPackage(
                version="1.0.0",
                hash="sha256:" + "a" * 64,
                source="https://github.com/a/repo",
            ),
        }
        lock = LockFile(packages=packages)
        serialized = serialize_lock_file(lock)

        # 'a' should appear before 'z' in output
        pos_a = serialized.index("github.com/a/repo")
        pos_z = serialized.index("github.com/z/repo")
        assert pos_a < pos_z

    def test_serialize_lock_file_round_trip(self):
        packages = {
            "github.com/org/repo": LockedPackage(
                version="1.0.0",
                hash="sha256:" + "c" * 64,
                source="https://github.com/org/repo",
            ),
        }
        lock = LockFile(packages=packages)
        serialized = serialize_lock_file(lock)
        restored = parse_lock_file(serialized)
        assert restored.packages["github.com/org/repo"].version == "1.0.0"
        assert restored.packages["github.com/org/repo"].hash == "sha256:" + "c" * 64

    # --- generate_lock_file ---

    def test_generate_lock_file_skips_local(self, tmp_path: Path):
        """Local deps (with path) are excluded from the lock file."""
        (tmp_path / "file.txt").write_text("content")

        manifest = MethodsManifest(
            address="github.com/acme/root",
            version="1.0.0",
            description="test",
        )
        # Inject dependencies via object.__setattr__ since the field was removed
        # from the schema but generate_lock_file still reads it via getattr().
        # Pydantic's __setattr__ would reject unknown fields, so we bypass it.
        object.__setattr__(  # noqa: PLC2801
            manifest,
            "dependencies",
            {
                "local_dep": PackageDependency(address="github.com/acme/local", version="0.1.0", path="../local"),
            },
        )

        remote_manifest = MethodsManifest(
            address="github.com/acme/remote",
            version="2.0.0",
            description="remote dep",
        )
        resolved = [
            ResolvedDependency(
                alias="remote_dep",
                address="github.com/acme/remote",
                manifest=remote_manifest,
                package_root=tmp_path,
                mthds_files=[],
                exported_pipe_codes=None,
            ),
        ]
        lock = generate_lock_file(manifest, resolved)
        assert "github.com/acme/remote" in lock.packages
        assert "github.com/acme/local" not in lock.packages

    def test_generate_lock_file_remote_without_manifest(self, tmp_path: Path):
        manifest = MethodsManifest(
            address="github.com/acme/root",
            version="1.0.0",
            description="test",
        )
        resolved = [
            ResolvedDependency(
                alias="bad_dep",
                address="github.com/acme/bad",
                manifest=None,
                package_root=tmp_path,
                mthds_files=[],
                exported_pipe_codes=None,
            ),
        ]
        with pytest.raises(LockFileError, match="no manifest"):
            generate_lock_file(manifest, resolved)

    # --- verify_locked_package ---

    def test_verify_locked_package_cache_miss(self, tmp_path: Path):
        locked = LockedPackage(
            version="1.0.0",
            hash="sha256:" + "a" * 64,
            source="https://github.com/org/repo",
        )
        with pytest.raises(IntegrityError, match="not found"):
            verify_locked_package(locked, "github.com/org/repo", tmp_path)

    def test_verify_locked_package_hash_mismatch(self, tmp_path: Path):
        # Create cached dir with content
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        (pkg_path / "file.txt").write_text("hello")

        actual_hash = compute_directory_hash(pkg_path)
        wrong_hash = "sha256:" + "0" * 64

        locked = LockedPackage(
            version="1.0.0",
            hash=wrong_hash,
            source="https://github.com/org/repo",
        )
        # Only fail if actual hash differs (it should, since 000... is fake)
        if actual_hash != wrong_hash:
            with pytest.raises(IntegrityError, match="Integrity check failed"):
                verify_locked_package(locked, "github.com/org/repo", tmp_path)

    def test_verify_locked_package_correct(self, tmp_path: Path):
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        (pkg_path / "file.txt").write_text("hello")

        actual_hash = compute_directory_hash(pkg_path)
        locked = LockedPackage(
            version="1.0.0",
            hash=actual_hash,
            source="https://github.com/org/repo",
        )
        # Should not raise
        verify_locked_package(locked, "github.com/org/repo", tmp_path)

    # --- verify_lock_file ---

    def test_verify_lock_file_all_pass(self, tmp_path: Path):
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        (pkg_path / "file.txt").write_text("hello")
        actual_hash = compute_directory_hash(pkg_path)

        lock = LockFile(
            packages={
                "github.com/org/repo": LockedPackage(
                    version="1.0.0",
                    hash=actual_hash,
                    source="https://github.com/org/repo",
                ),
            }
        )
        # Should not raise
        verify_lock_file(lock, tmp_path)

    def test_verify_lock_file_first_entry_fails(self, tmp_path: Path):
        lock = LockFile(
            packages={
                "github.com/org/missing": LockedPackage(
                    version="1.0.0",
                    hash="sha256:" + "a" * 64,
                    source="https://github.com/org/missing",
                ),
            }
        )
        with pytest.raises(IntegrityError):
            verify_lock_file(lock, tmp_path)
