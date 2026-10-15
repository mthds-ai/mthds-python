import os
from pathlib import Path

import pytest

from mthds.package.discovery import find_package_manifest, read_package_manifest_at
from mthds.package.exceptions import ManifestError, ManifestReadError
from mthds.package.package_contents import make_package_from_directory

CONSUMER_MANIFEST = '[package]\naddress = "github.com/acme/consumer"\nversion = "1.0.0"\ndescription = "Consumer"\n'
DEPENDENCY_MANIFEST = '[package]\naddress = "github.com/acme/dependency"\nversion = "2.0.0"\ndescription = "Dependency"\n'


class TestPackageDiscovery:
    def test_manifest_at_a_package_root_is_read_there(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(DEPENDENCY_MANIFEST)
        manifest = read_package_manifest_at(tmp_path)
        assert manifest is not None
        assert manifest.address == "github.com/acme/dependency"

    def test_manifest_spelled_in_another_letter_case_is_no_manifest(self, tmp_path: Path):
        """A `methods.toml` is no manifest, even where the file system would also answer to `METHODS.toml`."""
        (tmp_path / "METHODS.toml").write_text(CONSUMER_MANIFEST)
        dependency = tmp_path / "deps" / "foo"
        dependency.mkdir(parents=True)
        (dependency / "methods.toml").write_text(DEPENDENCY_MANIFEST)
        assert read_package_manifest_at(dependency) is None
        with pytest.raises(ManifestError, match=r"No METHODS\.toml found"):
            make_package_from_directory(dependency)

    def test_manifest_that_is_a_symbolic_link_is_refused(self, tmp_path: Path):
        (tmp_path / "METHODS.toml").write_text(CONSUMER_MANIFEST)
        dependency = tmp_path / "deps" / "foo"
        dependency.mkdir(parents=True)
        (tmp_path / "real.toml").write_text(DEPENDENCY_MANIFEST)
        (dependency / "METHODS.toml").symlink_to(tmp_path / "real.toml")
        with pytest.raises(ManifestReadError, match="not a regular file"):
            read_package_manifest_at(dependency)

    def test_directory_that_cannot_be_listed_to_confirm_a_manifest(self, tmp_path: Path):
        """A directory answering to `METHODS.toml` that cannot be listed to confirm its exact name is a manifest error, not a tree error."""
        if os.geteuid() == 0:
            pytest.skip("permissions do not bind the superuser")
        locked = tmp_path / "locked"
        (locked / "method").mkdir(parents=True)
        (locked / "METHODS.toml").write_text(DEPENDENCY_MANIFEST)
        (locked / "method" / "main.mthds").write_text('domain = "letters"\n')
        locked.chmod(0o311)
        try:
            with pytest.raises(ManifestReadError, match=r"Cannot look for the METHODS\.toml"):
                find_package_manifest(locked / "method" / "main.mthds")
            with pytest.raises(ManifestReadError, match=r"Cannot look for METHODS\.toml"):
                read_package_manifest_at(locked)
        finally:
            locked.chmod(0o755)
