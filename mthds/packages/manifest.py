import re
import unicodedata
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mthds._compat import Self
from mthds._utils.pydantic_utils import empty_list_factory_of
from mthds._utils.string_utils import is_snake_case
from mthds.packages.validation import is_domain_code_valid, is_pipe_code_valid

# Semver regex: MAJOR.MINOR.PATCH with optional pre-release and build metadata
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

# Version constraint pattern: supports standard range syntax used by Poetry/uv.
# A single constraint is: optional operator + semver (with optional wildcard minor/patch).
# Multiple constraints can be comma-separated (e.g., ">=1.0.0, <2.0.0").
# Supported forms: "1.0.0", "^1.0.0", "~1.0.0", ">=1.0.0", "<=1.0.0", ">1.0.0", "<1.0.0",
# "==1.0.0", "!=1.0.0", ">=1.0.0, <2.0.0", "*", "1.*", "1.0.*"
_SINGLE_CONSTRAINT = (
    r"(?:"
    r"\*"  # wildcard: *
    r"|(?:(?:\^|~|>=?|<=?|==|!=)?(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*|\*))?(?:\.(?:0|[1-9]\d*|\*))?)"  # [op]MAJOR[.MINOR[.PATCH]]
    r"(?:-(?:(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?)"  # optional prerelease
)
VERSION_CONSTRAINT_PATTERN = re.compile(rf"^{_SINGLE_CONSTRAINT}(?:\s*,\s*{_SINGLE_CONSTRAINT})*$")

# Address pattern: must contain at least one dot before a slash (hostname pattern)
# e.g. "github.com/org/repo", "example.io/pkg"
ADDRESS_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+/[a-zA-Z0-9._/-]+$")

RESERVED_DOMAINS: frozenset[str] = frozenset({"native", "mthds", "pipelex"})

MTHDS_STANDARD_VERSION: str = "1.0.0"


def is_reserved_domain_path(domain_path: str) -> bool:
    """Check if a domain path starts with a reserved domain segment."""
    first_segment = domain_path.split(".", maxsplit=1)[0]
    return first_segment in RESERVED_DOMAINS


def is_valid_semver(version: str) -> bool:
    """Check if a version string is valid semver."""
    return SEMVER_PATTERN.match(version) is not None


def is_valid_version_constraint(constraint: str) -> bool:
    """Check if a version constraint string is valid.

    Supports standard range syntax used by Poetry/uv:
    - Exact: "1.0.0"
    - Caret: "^1.0.0" (compatible release)
    - Tilde: "~1.0.0" (approximately compatible)
    - Comparison: ">=1.0.0", "<=1.0.0", ">1.0.0", "<1.0.0", "==1.0.0", "!=1.0.0"
    - Compound: ">=1.0.0, <2.0.0"
    - Wildcard: "*", "1.*", "1.0.*"
    """
    return VERSION_CONSTRAINT_PATTERN.match(constraint.strip()) is not None


def is_valid_address(address: str) -> bool:
    """Check if an address contains at least one dot before a slash (hostname pattern)."""
    return ADDRESS_PATTERN.match(address) is not None


class PackageDependency(BaseModel):
    """A dependency on another MTHDS package."""

    model_config = ConfigDict(extra="forbid")

    address: str
    version: str
    alias: str
    path: str | None = None

    @field_validator("address")
    @classmethod
    def validate_address(cls, address: str) -> str:
        if not is_valid_address(address):
            msg = f"Invalid package address '{address}'. Address must follow hostname/path pattern (e.g. 'github.com/org/repo')."
            raise ValueError(msg)
        return address

    @field_validator("version")
    @classmethod
    def validate_version(cls, version: str) -> str:
        if not is_valid_version_constraint(version):
            msg = f"Invalid version constraint '{version}'. Must be a valid version range (e.g. '1.0.0', '^1.0.0', '>=1.0.0, <2.0.0')."
            raise ValueError(msg)
        return version

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, alias: str) -> str:
        if not is_snake_case(alias):
            msg = f"Invalid dependency alias '{alias}'. Must be snake_case."
            raise ValueError(msg)
        return alias


class DomainExports(BaseModel):
    """Exports for a single domain within a package."""

    model_config = ConfigDict(extra="forbid")

    domain_path: str
    pipes: list[str] = Field(default_factory=list)

    @field_validator("domain_path")
    @classmethod
    def validate_domain_path(cls, domain_path: str) -> str:
        if not is_domain_code_valid(domain_path):
            msg = f"Invalid domain path '{domain_path}' in [exports]. Domain paths must be dot-separated snake_case segments."
            raise ValueError(msg)
        if is_reserved_domain_path(domain_path):
            first_segment = domain_path.split(".", maxsplit=1)[0]
            msg = (
                f"Domain path '{domain_path}' uses reserved domain '{first_segment}'. "
                f"Reserved domains ({', '.join(sorted(RESERVED_DOMAINS))}) cannot be used in package exports."
            )
            raise ValueError(msg)
        return domain_path

    @field_validator("pipes")
    @classmethod
    def validate_pipes(cls, pipes: list[str]) -> list[str]:
        for pipe_name in pipes:
            if not is_pipe_code_valid(pipe_name):
                msg = f"Invalid pipe name '{pipe_name}' in [exports]. Pipe names must be in snake_case."
                raise ValueError(msg)
        return pipes


def _walk_exports_table(table: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    """Recursively walk nested exports sub-tables to reconstruct dotted domain paths.

    Given a TOML structure like:
        [exports.legal.contracts]
        pipes = ["extract_clause"]

    This produces {"domain_path": "legal.contracts", "pipes": ["extract_clause"]}.
    """
    result: list[dict[str, Any]] = []

    for key, value in table.items():
        current_path = f"{prefix}.{key}" if prefix else str(key)

        if isinstance(value, dict):
            value_dict = cast("dict[str, Any]", value)
            if "pipes" in value_dict:
                pipes_value: Any = value_dict["pipes"]
                if not isinstance(pipes_value, list):
                    msg = f"'pipes' in domain '{current_path}' must be a list, got {type(pipes_value).__name__}"
                    raise ValueError(msg)
                pipes_list = cast("list[str]", pipes_value)
                result.append({"domain_path": current_path, "pipes": pipes_list})

                # Also recurse into remaining sub-tables (a domain can have both pipes and sub-domains)
                for sub_key, sub_value in value_dict.items():
                    if sub_key != "pipes" and isinstance(sub_value, dict):
                        sub_dict = cast("dict[str, Any]", {sub_key: sub_value})
                        result.extend(_walk_exports_table(sub_dict, prefix=current_path))
            else:
                result.extend(_walk_exports_table(value_dict, prefix=current_path))

    return result


_KNOWN_TOP_LEVEL_KEYS = frozenset({"package", "dependencies", "exports"})


class MthdsPackageManifest(BaseModel):
    """The METHODS.toml package manifest model.

    Can be constructed in two ways:
    - From raw TOML dict: ``MthdsPackageManifest.model_validate(raw_toml_dict)``
    - Directly: ``MthdsPackageManifest(address=..., version=..., ...)``
    """

    model_config = ConfigDict(extra="forbid")

    address: str
    display_name: str | None = None
    version: str
    description: str
    authors: list[str] = Field(default_factory=list)
    license: str | None = None
    mthds_version: str | None = None

    dependencies: list[PackageDependency] = Field(default_factory=empty_list_factory_of(PackageDependency))
    exports: list[DomainExports] = Field(default_factory=empty_list_factory_of(DomainExports))

    @model_validator(mode="before")
    @classmethod
    def _from_raw_toml(cls, data: Any) -> Any:
        """Accept raw TOML dict shape and reshape it for field validation.

        Detects raw TOML format (has a ``package`` dict key) vs. direct
        construction (has ``address`` key directly) and handles both.
        """
        if not isinstance(data, dict):
            return data
        raw = cast("dict[str, Any]", data)

        # If "package" is a dict, we're dealing with raw TOML input
        pkg_section: Any = raw.get("package")
        if not isinstance(pkg_section, dict):
            return raw

        # Reject unknown top-level sections
        unknown = set(raw.keys()) - _KNOWN_TOP_LEVEL_KEYS
        if unknown:
            msg = f"Unknown sections in METHODS.toml: {', '.join(sorted(unknown))}"
            raise ValueError(msg)

        # Flatten [package] section to top-level fields
        result: dict[str, Any] = dict(cast("dict[str, Any]", pkg_section))

        # Transform [dependencies] from {alias: {address, version, ...}} to list
        deps_section: Any = raw.get("dependencies", {})
        if isinstance(deps_section, dict):
            deps_dict = cast("dict[str, Any]", deps_section)
            deps_list: list[dict[str, Any]] = []
            for alias, dep_data in deps_dict.items():
                if not isinstance(dep_data, dict):
                    msg = f"Invalid dependency '{alias}': expected a table with 'address' and 'version' keys, got {type(dep_data).__name__}"
                    raise ValueError(msg)  # noqa: TRY004 — must be ValueError for Pydantic to wrap it
                dep_entry: dict[str, Any] = dict(cast("dict[str, Any]", dep_data))
                dep_entry["alias"] = str(alias)
                deps_list.append(dep_entry)
            result["dependencies"] = deps_list

        # Walk nested [exports] tables into flat list
        exports_section: Any = raw.get("exports", {})
        if isinstance(exports_section, dict):
            result["exports"] = _walk_exports_table(cast("dict[str, Any]", exports_section))

        return result

    @field_validator("address")
    @classmethod
    def validate_address(cls, address: str) -> str:
        if not is_valid_address(address):
            msg = f"Invalid package address '{address}'. Address must follow hostname/path pattern (e.g. 'github.com/org/repo')."
            raise ValueError(msg)
        return address

    @field_validator("version")
    @classmethod
    def validate_version(cls, version: str) -> str:
        if not is_valid_semver(version):
            msg = f"Invalid version '{version}'. Must be valid semver (e.g. '1.0.0', '2.1.3-beta.1')."
            raise ValueError(msg)
        return version

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, display_name: str | None) -> str | None:
        if display_name is None:
            return None
        stripped = display_name.strip()
        if not stripped:
            msg = "Display name must not be empty or whitespace when provided."
            raise ValueError(msg)
        if len(stripped) > 128:
            msg = f"Display name must not exceed 128 characters (got {len(stripped)})."
            raise ValueError(msg)
        if any(unicodedata.category(char) == "Cc" for char in stripped):
            msg = "Display name must not contain control characters."
            raise ValueError(msg)
        return stripped

    @field_validator("description")
    @classmethod
    def validate_description(cls, description: str) -> str:
        stripped = description.strip()
        if not stripped:
            msg = "Package description must not be empty."
            raise ValueError(msg)
        return stripped

    @field_validator("authors")
    @classmethod
    def validate_authors(cls, authors: list[str]) -> list[str]:
        for index_author, author in enumerate(authors):
            if not author.strip():
                msg = f"Author at index {index_author} must not be empty or whitespace."
                raise ValueError(msg)
        return authors

    @field_validator("license")
    @classmethod
    def validate_license(cls, license_value: str | None) -> str | None:
        if license_value is not None and not license_value.strip():
            msg = "License must not be empty or whitespace when provided."
            raise ValueError(msg)
        return license_value

    @field_validator("mthds_version")
    @classmethod
    def validate_mthds_version(cls, mthds_version: str | None) -> str | None:
        if mthds_version is not None and not is_valid_version_constraint(mthds_version):
            msg = f"Invalid mthds_version constraint '{mthds_version}'. Must be a valid version constraint (e.g. '1.0.0', '^1.0.0', '>=1.0.0')."
            raise ValueError(msg)
        return mthds_version

    @model_validator(mode="after")
    def validate_unique_dependency_aliases(self) -> Self:
        """Ensure all dependency aliases are unique."""
        seen_aliases: set[str] = set()
        for dep in self.dependencies:
            if dep.alias in seen_aliases:
                msg = f"Duplicate dependency alias '{dep.alias}'. Each dependency must have a unique alias."
                raise ValueError(msg)
            seen_aliases.add(dep.alias)
        return self
