import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from mthds.package.dependency_resolver import ResolvedDependency
from mthds.package.exceptions import IntegrityError, LockFileError
from mthds.package.lock_file import (
    LockedPackage,
    LockFile,
    compute_package_digest,
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
            digest="sha256:" + "a" * 64,
            source="https://github.com/org/repo",
        )
        assert locked.version == "1.0.0"

    @pytest.mark.parametrize(
        "bad_digest",
        [
            "sha256:" + "a" * 63,
            "sha256:" + "A" * 64,
            "md5:" + "a" * 64,
            "tooshort",
        ],
    )
    def test_locked_package_invalid_digest(self, bad_digest: str):
        with pytest.raises(ValidationError, match="digest"):
            LockedPackage(version="1.0.0", digest=bad_digest, source="https://example.com")

    def test_locked_package_invalid_source(self):
        with pytest.raises(ValidationError, match="source"):
            LockedPackage(version="1.0.0", digest="sha256:" + "a" * 64, source="http://not-https.com")

    def test_locked_package_invalid_version(self):
        with pytest.raises(ValidationError, match="version"):
            LockedPackage(version="^1.0.0", digest="sha256:" + "a" * 64, source="https://example.com")

    # --- compute_package_digest ---

    def test_compute_package_digest_is_the_tree_digest(self, tmp_path: Path):
        """The digest is the SHA-256 of the tree's sha256sum listing, as the standard defines the tree digest."""
        (tmp_path / "file.txt").write_text("hello")
        listing = f"{hashlib.sha256(b'hello').hexdigest()}  file.txt\n".encode()
        assert compute_package_digest(tmp_path) == "sha256:" + hashlib.sha256(listing).hexdigest()

    def test_compute_package_digest_tells_apart_what_the_old_hash_confused(self, tmp_path: Path):
        """`ab` holding `c` and `a` holding `bc` concatenate alike, which made the pre-7.0.0 hash ambiguous; their digests differ."""
        first = tmp_path / "first"
        first.mkdir()
        (first / "ab").write_text("c")
        second = tmp_path / "second"
        second.mkdir()
        (second / "a").write_text("bc")
        assert compute_package_digest(first) != compute_package_digest(second)

    def test_compute_package_digest_reads_the_copy_as_written(self, tmp_path: Path):
        """A written tree is read back with every file at its path: the membership rule is not applied again."""
        (tmp_path / "file.txt").write_text("hello")
        without_dotfile = compute_package_digest(tmp_path)
        (tmp_path / ".extra").write_text("written")
        assert compute_package_digest(tmp_path) != without_dotfile

    def test_compute_package_digest_nonexistent_dir(self, tmp_path: Path):
        with pytest.raises(LockFileError, match="does not exist"):
            compute_package_digest(tmp_path / "nonexistent")

    def test_compute_package_digest_empty_dir(self, tmp_path: Path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(LockFileError, match="holds no file"):
            compute_package_digest(empty_dir)

    # --- parse_lock_file ---

    def test_parse_lock_file_empty(self):
        result = parse_lock_file("")
        assert result.packages == {}

    def test_parse_lock_file_whitespace_only(self):
        result = parse_lock_file("   \n  \n  ")
        assert result.packages == {}

    def test_parse_lock_file_valid(self):
        toml_content = '["github.com/org/repo"]\nversion = "1.0.0"\ndigest = "sha256:' + "a" * 64 + '"\nsource = "https://github.com/org/repo"\n'
        result = parse_lock_file(toml_content)
        assert "github.com/org/repo" in result.packages
        assert result.packages["github.com/org/repo"].version == "1.0.0"

    def test_parse_lock_file_non_dict_entry(self):
        toml_content = '"github.com/org/repo" = "not a table"\n'
        with pytest.raises(LockFileError, match="must be a table"):
            parse_lock_file(toml_content)

    def test_parse_lock_file_invalid_digest(self):
        toml_content = '["github.com/org/repo"]\nversion = "1.0.0"\ndigest = "bad_digest"\nsource = "https://github.com/org/repo"\n'
        with pytest.raises(LockFileError, match="Invalid lock file entry"):
            parse_lock_file(toml_content)

    def test_parse_lock_file_refuses_a_lock_written_before_tree_digests(self):
        """An entry carrying the pre-7.0.0 `hash` is refused at parse, telling to run `lock`, and is never verified."""
        toml_content = '["github.com/org/repo"]\nversion = "1.0.0"\nhash = "sha256:' + "a" * 64 + '"\nsource = "https://github.com/org/repo"\n'
        with pytest.raises(LockFileError, match=r"predates tree digests.*Run `lock` to regenerate it"):
            parse_lock_file(toml_content)

    def test_parse_lock_file_bad_toml_syntax(self):
        with pytest.raises(LockFileError, match="Invalid TOML"):
            parse_lock_file("[broken\ntoml")

    # --- serialize_lock_file ---

    def test_serialize_lock_file_sorted(self):
        packages = {
            "github.com/z/repo": LockedPackage(
                version="2.0.0",
                digest="sha256:" + "b" * 64,
                source="https://github.com/z/repo",
            ),
            "github.com/a/repo": LockedPackage(
                version="1.0.0",
                digest="sha256:" + "a" * 64,
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
                digest="sha256:" + "c" * 64,
                source="https://github.com/org/repo",
            ),
        }
        lock = LockFile(packages=packages)
        serialized = serialize_lock_file(lock)
        restored = parse_lock_file(serialized)
        assert restored.packages["github.com/org/repo"].version == "1.0.0"
        assert restored.packages["github.com/org/repo"].digest == "sha256:" + "c" * 64
        assert 'digest = "sha256:' in serialized
        assert "hash" not in serialized

    # --- generate_lock_file ---

    def test_generate_lock_file_remote_only(self, tmp_path: Path):
        """Only remote deps (passed by caller) appear in the lock file."""
        (tmp_path / "file.txt").write_text("content")

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
        lock = generate_lock_file(resolved)
        assert "github.com/acme/remote" in lock.packages

    def test_generate_lock_file_remote_without_manifest(self, tmp_path: Path):
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
            generate_lock_file(resolved)

    # --- verify_locked_package ---

    def test_verify_locked_package_cache_miss(self, tmp_path: Path):
        locked = LockedPackage(
            version="1.0.0",
            digest="sha256:" + "a" * 64,
            source="https://github.com/org/repo",
        )
        with pytest.raises(IntegrityError, match="not found"):
            verify_locked_package(locked, "github.com/org/repo", tmp_path)

    def test_verify_locked_package_digest_mismatch(self, tmp_path: Path):
        # Create cached dir with content
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        (pkg_path / "file.txt").write_text("hello")

        wrong_digest = "sha256:" + "0" * 64

        locked = LockedPackage(
            version="1.0.0",
            digest=wrong_digest,
            source="https://github.com/org/repo",
        )
        with pytest.raises(IntegrityError, match="Integrity check failed"):
            verify_locked_package(locked, "github.com/org/repo", tmp_path)

    def test_verify_locked_package_correct(self, tmp_path: Path):
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        (pkg_path / "file.txt").write_text("hello")

        actual_digest = compute_package_digest(pkg_path)
        locked = LockedPackage(
            version="1.0.0",
            digest=actual_digest,
            source="https://github.com/org/repo",
        )
        # Should not raise
        verify_locked_package(locked, "github.com/org/repo", tmp_path)

    # --- verify_lock_file ---

    def test_verify_lock_file_all_pass(self, tmp_path: Path):
        pkg_path = tmp_path / "github.com" / "org" / "repo" / "1.0.0"
        pkg_path.mkdir(parents=True)
        (pkg_path / "file.txt").write_text("hello")
        actual_digest = compute_package_digest(pkg_path)

        lock = LockFile(
            packages={
                "github.com/org/repo": LockedPackage(
                    version="1.0.0",
                    digest=actual_digest,
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
                    digest="sha256:" + "a" * 64,
                    source="https://github.com/org/missing",
                ),
            }
        )
        with pytest.raises(IntegrityError):
            verify_lock_file(lock, tmp_path)
