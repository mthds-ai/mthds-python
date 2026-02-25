"""Pipelex runner — implements RunnerProtocol by delegating to the pipelex CLI."""

import json
import shutil
import subprocess  # noqa: S404
import tempfile
from pathlib import Path
from typing import Any

from typing_extensions import override

from mthds.client.models.pipe_output import DictPipeOutputAbstract, VariableMultiplicity
from mthds.client.models.pipeline_inputs import PipelineInputs
from mthds.client.models.stuff import StuffType
from mthds.client.models.working_memory import WorkingMemoryAbstract
from mthds.client.pipeline import DictPipelineExecuteResponse, DictPipelineStartResponse
from mthds.client.protocol import RunnerProtocol
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


def run_subprocess(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[bytes]:
    """Run a subprocess command with standard error handling.

    Args:
        cmd: Command to run.
        timeout: Timeout in seconds.

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


class PipelexRunner(RunnerProtocol[DictPipeOutputAbstract]):
    """Runner that implements RunnerProtocol by delegating to the pipelex CLI."""

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
    async def execute_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_content: str | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_code: str | None = None,
    ) -> DictPipelineExecuteResponse:
        """Execute a pipeline via the pipelex CLI subprocess.

        Writes mthds_content and inputs to temp files, runs `pipelex run`,
        and parses the output JSON back into a typed response.

        Args:
            pipe_code: The code identifying the pipeline to execute.
            mthds_content: Content of the pipeline bundle to execute.
            inputs: Inputs passed to the pipeline.
            output_name: Unused by pipelex CLI.
            output_multiplicity: Unused by pipelex CLI.
            dynamic_output_concept_code: Unused by pipelex CLI.

        Returns:
            Complete execution results including pipeline state and output.

        Raises:
            PipelexRunnerError: If pipelex execution fails.
        """
        _ = (output_name, output_multiplicity, dynamic_output_concept_code)
        pipelex_path = _ensure_pipelex()

        tmp_dir = Path(tempfile.mkdtemp(prefix="mthds-"))
        try:
            cmd: list[str] = [pipelex_path, *self._library_args(), "run"]

            if mthds_content:
                bundle_path = tmp_dir / "bundle.mthds"
                bundle_path.write_text(mthds_content, encoding="utf-8")
                cmd.append(str(bundle_path))
                if pipe_code:
                    cmd.extend(["--pipe", pipe_code])
            elif pipe_code:
                cmd.append(pipe_code)

            serialized_inputs = _serialize_inputs(inputs)
            if serialized_inputs is not None:
                inputs_path = tmp_dir / "inputs.json"
                inputs_path.write_text(json.dumps(serialized_inputs), encoding="utf-8")
                cmd.extend(["-i", str(inputs_path)])

            output_path = tmp_dir / "output.json"
            cmd.extend(["--output", str(output_path)])

            run_subprocess(cmd)

            raw: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
            return DictPipelineExecuteResponse.from_api_response(raw)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @override
    async def start_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_content: str | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_code: str | None = None,
    ) -> DictPipelineStartResponse:
        """Start a pipeline asynchronously — not supported by pipelex CLI.

        Args:
            pipe_code: Unused.
            mthds_content: Unused.
            inputs: Unused.
            output_name: Unused.
            output_multiplicity: Unused.
            dynamic_output_concept_code: Unused.

        Raises:
            NotImplementedError: Always, since pipelex CLI is synchronous.
        """
        _ = (pipe_code, mthds_content, inputs, output_name, output_multiplicity, dynamic_output_concept_code)
        msg = "start_pipeline is not supported by the pipelex CLI runner. Use execute_pipeline instead."
        raise NotImplementedError(msg)
