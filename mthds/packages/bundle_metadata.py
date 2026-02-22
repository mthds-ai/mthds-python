"""Pure metadata extraction from .mthds file TOML headers.

Provides lightweight metadata extraction without requiring a full interpreter.
"""

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from mthds._utils.toml_utils import TomlError, load_toml_from_content


class BundleMetadata(BaseModel):
    """Metadata extracted from a .mthds file header."""

    model_config = ConfigDict(frozen=True)

    domain: str
    main_pipe: str | None = None
    pipe_codes: list[str] = Field(default_factory=list)
    source: str = ""
    pipe_references: list[tuple[str, str]] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


def extract_bundle_metadata(path: Path) -> BundleMetadata:
    """Extract metadata from a .mthds file by parsing its TOML header.

    Parses the [header] section and [pipe.*] sections to extract domain,
    main_pipe, pipe codes, and pipe references.

    Args:
        path: Path to the .mthds file.

    Returns:
        BundleMetadata with extracted information.

    Raises:
        ValueError: If the file cannot be parsed or has no domain.
    """
    content = path.read_text(encoding="utf-8")

    try:
        data: dict[str, Any] = load_toml_from_content(content)
    except TomlError as exc:
        msg = f"Failed to parse TOML in {path}: {exc}"
        raise ValueError(msg) from exc

    # Extract header fields — .mthds files may have domain at top level or under [header]
    header_raw = data.get("header")
    header: dict[str, Any] = cast("dict[str, Any]", header_raw) if isinstance(header_raw, dict) else data
    domain: str = str(header.get("domain", ""))
    if not domain:
        msg = f"No domain found in {path}"
        raise ValueError(msg)

    main_pipe_raw = header.get("main_pipe")
    main_pipe: str | None = str(main_pipe_raw) if main_pipe_raw is not None else None

    # Extract pipe codes and references
    pipe_codes: list[str] = []
    pipe_references: list[tuple[str, str]] = []

    pipe_section_raw = data.get("pipe")
    if isinstance(pipe_section_raw, dict):
        pipe_section = cast("dict[str, Any]", pipe_section_raw)
        for pipe_code in pipe_section:
            pipe_codes.append(pipe_code)
            pipe_data_raw = pipe_section[pipe_code]
            if isinstance(pipe_data_raw, dict):
                pipe_data = cast("dict[str, Any]", pipe_data_raw)
                pipe_references.extend(_collect_refs_from_pipe(pipe_code, pipe_data))

    return BundleMetadata(
        domain=domain,
        main_pipe=main_pipe,
        pipe_codes=pipe_codes,
        source=str(path),
        pipe_references=pipe_references,
    )


def _collect_refs_from_pipe(pipe_code: str, pipe_data: dict[str, Any]) -> list[tuple[str, str]]:
    """Collect pipe references from a single pipe's TOML data.

    Looks for pipe references in controller fields like steps, branches,
    branch_pipe_code, and sub-pipes.

    Args:
        pipe_code: The code of the pipe being scanned.
        pipe_data: The TOML dict for this pipe section.

    Returns:
        List of (pipe_ref_string, context_description) tuples.
    """
    refs: list[tuple[str, str]] = []

    # Sequence steps
    steps_raw = pipe_data.get("steps")
    if isinstance(steps_raw, list):
        steps = cast("list[Any]", steps_raw)
        for step_index, step_raw in enumerate(steps):
            if isinstance(step_raw, dict):
                step = cast("dict[str, Any]", step_raw)
                pipe_ref = step.get("pipe")
                if isinstance(pipe_ref, str):
                    refs.append((pipe_ref, f"pipe.{pipe_code}.steps[{step_index}].pipe"))

    # Batch branch_pipe_code
    branch_pipe_code = pipe_data.get("branch_pipe_code")
    if isinstance(branch_pipe_code, str):
        refs.append((branch_pipe_code, f"pipe.{pipe_code}.branch_pipe_code"))

    # Condition branches
    branches_raw = pipe_data.get("branches")
    if isinstance(branches_raw, list):
        branches = cast("list[Any]", branches_raw)
        for branch_index, branch_raw in enumerate(branches):
            if isinstance(branch_raw, dict):
                branch = cast("dict[str, Any]", branch_raw)
                pipe_ref = branch.get("pipe")
                if isinstance(pipe_ref, str):
                    refs.append((pipe_ref, f"pipe.{pipe_code}.branches[{branch_index}].pipe"))

    # Parallel sub-pipes
    sub_pipes_raw = pipe_data.get("sub_pipes")
    if isinstance(sub_pipes_raw, list):
        sub_pipes = cast("list[Any]", sub_pipes_raw)
        for sub_index, sub_pipe_raw in enumerate(sub_pipes):
            if isinstance(sub_pipe_raw, dict):
                sub_pipe = cast("dict[str, Any]", sub_pipe_raw)
                pipe_ref = sub_pipe.get("pipe")
                if isinstance(pipe_ref, str):
                    refs.append((pipe_ref, f"pipe.{pipe_code}.sub_pipes[{sub_index}].pipe"))

    return refs


def collect_pipe_references(metadata: BundleMetadata) -> list[tuple[str, str]]:
    """Return the pipe references from bundle metadata.

    Args:
        metadata: The bundle metadata.

    Returns:
        List of (pipe_ref_string, context_description) tuples.
    """
    return list(metadata.pipe_references)
