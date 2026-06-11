"""Pipelex runner — implements MTHDSProtocol by delegating to the pipelex CLI."""

# TODO: refacto

import json
import re
import shutil
import subprocess  # noqa: S404
import tempfile
from pathlib import Path
from typing import Any, cast

from typing_extensions import override

from mthds.protocol.models import ModelCategory, ModelDeck, ValidationReport, VersionInfo
from mthds.protocol.pipe_output import VariableMultiplicity
from mthds.protocol.pipeline_inputs import PipelineInputs
from mthds.protocol.protocol import MTHDSProtocol
from mthds.protocol.stuff import StuffType
from mthds.protocol.working_memory import WorkingMemoryAbstract
from mthds.runners.api.models import MAIN_STUFF_NAME, DictPipeOutputAbstract, DictRunResult, DictWorkingMemoryAbstract
from mthds.runners.types import RunnerType


class PipelexRunnerError(Exception):
    """Error raised when the pipelex runner encounters an issue."""


def _ensure_pipelex() -> str:
    """Ensure pipelex is on PATH and return its path.

    Returns:
        Path to the pipelex executable.

    Raises:
        PipelexRunnerError: If pipelex is not found on PATH.
    """
    path = shutil.which("pipelex")
    if path is None:
        msg = (
            "'pipelex' not found on PATH.\n"
            "Install pipelex: curl -sSL https://pipelex.com/install.sh | sh\n"
            "Or use --runner api to run via the MTHDS API instead."
        )
        raise PipelexRunnerError(msg)
    return path


def run_subprocess(cmd: list[str], *, timeout: int = 600, capture_output: bool = False) -> subprocess.CompletedProcess[bytes]:
    """Run a subprocess command with standard error handling.

    Args:
        cmd: Command to run.
        timeout: Timeout in seconds.
        capture_output: Capture stdout/stderr instead of inheriting them.

    Returns:
        Completed process result.

    Raises:
        PipelexRunnerError: If the command fails or times out.
    """
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            check=False,
            timeout=timeout,
            capture_output=capture_output,
        )
        if result.returncode != 0:
            msg = f"pipelex exited with code {result.returncode}"
            raise PipelexRunnerError(msg)
        return result
    except FileNotFoundError as exc:
        msg = "'pipelex' not found on PATH."
        raise PipelexRunnerError(msg) from exc
    except subprocess.TimeoutExpired as exc:
        msg = "Execution timed out (10 min limit)."
        raise PipelexRunnerError(msg) from exc


def _run_result_from_working_memory_dump(raw_memory: dict[str, Any]) -> DictRunResult:
    """Map the CLI's working-memory dump onto the SDK's DictRunResult shape.

    `pipelex run ... --working-memory-path` writes the runtime's full working
    memory (`{root: {name: {stuff_code, stuff_name, concept: {...}, content}},
    aliases}`). The SDK's wire shape keeps only `{concept: <ref string>,
    content}` per stuff — the same reduction the API runner performs
    server-side.

    Args:
        raw_memory: The parsed working-memory JSON written by the CLI.

    Returns:
        DictRunResult for the completed local run (no run id — local runs are
        not tracked).
    """
    dict_root: dict[str, dict[str, Any]] = {}
    raw_root_obj = raw_memory.get("root", {})
    raw_root: dict[str, Any] = cast("dict[str, Any]", raw_root_obj) if isinstance(raw_root_obj, dict) else {}
    for stuff_name, stuff_raw in raw_root.items():
        stuff: dict[str, Any] = cast("dict[str, Any]", stuff_raw) if isinstance(stuff_raw, dict) else {}
        concept_raw = stuff.get("concept")
        concept_ref: str
        if isinstance(concept_raw, dict):
            concept_dict = cast("dict[str, Any]", concept_raw)
            code = str(concept_dict.get("code", ""))
            domain_code = concept_dict.get("domain_code")
            concept_ref = f"{domain_code}.{code}" if domain_code else code
        else:
            concept_ref = str(concept_raw)
        dict_root[stuff_name] = {"concept": concept_ref, "content": stuff.get("content")}

    aliases_obj = raw_memory.get("aliases", {})
    aliases: dict[str, str] = cast("dict[str, str]", aliases_obj) if isinstance(aliases_obj, dict) else {}
    working_memory = DictWorkingMemoryAbstract.model_validate({"root": dict_root, "aliases": aliases})
    # `main_stuff_name` is a pipelex extension field — validated construction
    # keeps it in `model_extra` without naming it a typed parameter.
    return DictRunResult.model_validate(
        {
            "pipeline_run_id": "",
            "pipe_output": DictPipeOutputAbstract(working_memory=working_memory, pipeline_run_id=""),
            "main_stuff_name": aliases.get(MAIN_STUFF_NAME, MAIN_STUFF_NAME),
        }
    )


def _serialize_inputs(inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None) -> dict[str, Any] | None:
    """Serialize pipeline inputs to a JSON-serializable dict.

    Args:
        inputs: Pipeline inputs in any supported format.

    Returns:
        A JSON-serializable dict, or None if no inputs.
    """
    if inputs is None:
        return None

    if isinstance(inputs, dict):
        return inputs

    # WorkingMemoryAbstract — serialize via Pydantic
    return inputs.model_dump(serialize_as_any=True)  # type: ignore[union-attr]


class PipelexRunner(MTHDSProtocol[DictPipeOutputAbstract]):
    """Runner that implements MTHDSProtocol by delegating to the pipelex CLI."""

    def __init__(self, library_dirs: list[str] | None = None) -> None:
        """Initialize the pipelex runner.

        Args:
            library_dirs: Directories to pass via -L to pipelex for library search.
        """
        self._library_dirs = library_dirs or []

    def _library_args(self) -> list[str]:
        """Build -L arguments for pipelex commands.

        Returns:
            List of CLI arguments (e.g. ["-L", "/path1", "-L", "/path2"]) or empty list.
        """
        args: list[str] = []
        for lib_dir in self._library_dirs:
            args.extend(["-L", lib_dir])
        return args

    @property
    def runner_type(self) -> RunnerType:
        """Return the runner type."""
        return RunnerType.PIPELEX

    @override
    async def execute(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DictRunResult:
        """Execute a method via the pipelex CLI subprocess.

        Writes mthds_contents and inputs to temp files, runs `pipelex run`,
        and parses the output JSON back into a typed response.

        Args:
            pipe_code: The code identifying the pipeline to execute.
            mthds_contents: List of MTHDS bundle contents to load.
            inputs: Inputs passed to the pipeline.
            output_name: Unused by pipelex CLI.
            output_multiplicity: Unused by pipelex CLI.
            dynamic_output_concept_ref: Unused by pipelex CLI.
            extra: Rejected — the CLI runner defines no extension args.

        Returns:
            Complete execution results including pipeline state and output.

        Raises:
            PipelexRunnerError: If pipelex execution fails, or if extension
                args are passed (the CLI runner accepts none).
        """
        _ = (output_name, output_multiplicity, dynamic_output_concept_ref)
        if extra:
            msg = f"The pipelex CLI runner defines no extension args; got {sorted(extra)}."
            raise PipelexRunnerError(msg)
        pipelex_path = _ensure_pipelex()

        tmp_dir = Path(tempfile.mkdtemp(prefix="mthds-"))
        try:
            cmd: list[str] = [pipelex_path, *self._library_args(), "run"]

            if mthds_contents:
                for idx, content in enumerate(mthds_contents):
                    bundle_path = tmp_dir / f"bundle_{idx}.mthds"
                    bundle_path.write_text(content, encoding="utf-8")
                target = tmp_dir / "bundle_0.mthds" if len(mthds_contents) == 1 else tmp_dir
                cmd.extend(["bundle", str(target)])
                if pipe_code:
                    cmd.extend(["--pipe", pipe_code])
            elif pipe_code:
                cmd.extend(["pipe", pipe_code])

            serialized_inputs = _serialize_inputs(inputs)
            if serialized_inputs is not None:
                inputs_path = tmp_dir / "inputs.json"
                inputs_path.write_text(json.dumps(serialized_inputs), encoding="utf-8")
                cmd.extend(["-i", str(inputs_path)])

            working_memory_path = tmp_dir / "working_memory.json"
            cmd.extend(["--working-memory-path", str(working_memory_path)])
            cmd.extend(["-o", str(tmp_dir / "results")])
            cmd.append("--no-pretty-print")

            run_subprocess(cmd)

            raw_memory: dict[str, Any] = json.loads(working_memory_path.read_text(encoding="utf-8"))
            return _run_result_from_working_memory_dump(raw_memory)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @override
    async def start(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DictRunResult:
        """Start a method asynchronously — not supported by the pipelex CLI.

        Args:
            pipe_code: Unused.
            mthds_contents: Unused.
            inputs: Unused.
            output_name: Unused.
            output_multiplicity: Unused.
            dynamic_output_concept_ref: Unused.
            extra: Unused.

        Raises:
            NotImplementedError: Always, since the pipelex CLI is synchronous.
        """
        _ = (
            pipe_code,
            mthds_contents,
            inputs,
            output_name,
            output_multiplicity,
            dynamic_output_concept_ref,
            extra,
        )
        msg = "start is not supported by the pipelex CLI runner. Use execute instead."
        raise NotImplementedError(msg)

    @override
    async def validate(
        self,
        mthds_contents: list[str],
        allow_signatures: bool = False,
    ) -> ValidationReport:
        """Validate MTHDS bundles via `pipelex validate`.

        The CLI reports validity through its exit code; it does not emit the
        protocol's structural artifacts, so a passing validation returns an
        empty `ValidationReport`.

        Args:
            mthds_contents: MTHDS contents to load (always a list, even for one file).
            allow_signatures: Tolerate unimplemented pipe signatures.

        Returns:
            An empty ValidationReport when the bundle is valid.

        Raises:
            PipelexRunnerError: If validation fails or pipelex is unavailable.
        """
        pipelex_path = _ensure_pipelex()

        if not mthds_contents:
            msg = "mthds_contents must contain at least one bundle to validate."
            raise PipelexRunnerError(msg)

        tmp_dir = Path(tempfile.mkdtemp(prefix="mthds-"))
        try:
            # `pipelex validate bundle` takes ONE path — a bundle file or a directory.
            # Write all contents into the temp dir and validate the directory, which
            # covers both the single- and multi-bundle cases.
            for idx, content in enumerate(mthds_contents):
                bundle_path = tmp_dir / f"bundle_{idx}.mthds"
                bundle_path.write_text(content, encoding="utf-8")
            target = tmp_dir / "bundle_0.mthds" if len(mthds_contents) == 1 else tmp_dir
            cmd: list[str] = [pipelex_path, *self._library_args(), "validate", "bundle", str(target)]
            if allow_signatures:
                cmd.append("--allow-signatures")

            run_subprocess(cmd)
            return ValidationReport()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @override
    async def models(self, category: ModelCategory | None = None) -> ModelDeck:
        """The model deck — not supported by the pipelex CLI runner.

        Args:
            category: Unused.

        Raises:
            NotImplementedError: The CLI has no machine-readable deck output; use the API runner.
        """
        _ = category
        msg = "models is not supported by the pipelex CLI runner. Use the API runner instead."
        raise NotImplementedError(msg)

    @override
    async def version(self) -> VersionInfo:
        """Protocol + runner versions, from `pipelex --version`.

        Returns:
            VersionInfo with the local pipelex version as the runner version.

        Raises:
            PipelexRunnerError: If pipelex is unavailable or the output is unparsable.
        """
        pipelex_path = _ensure_pipelex()
        result = run_subprocess([pipelex_path, "--version"], timeout=60, capture_output=True)
        output = result.stdout.decode("utf-8").strip()
        match = re.search(r"(\d+\.\d+\.\d+\S*)", output)
        if match is None:
            msg = f"Could not parse a version from `pipelex --version` output: {output!r}"
            raise PipelexRunnerError(msg)
        local_version = match.group(1)
        return VersionInfo(
            protocol_version="0.1.0",
            runner_version=local_version,
        )
