"""Runner factory — creates the appropriate runner based on type or configuration."""

import shutil

from mthds.client.models.pipe_output import DictPipeOutputAbstract
from mthds.client.protocol import RunnerProtocol
from mthds.config.credentials import load_credentials
from mthds.runners.api_runner import ApiRunner
from mthds.runners.pipelex_runner import PipelexRunner
from mthds.runners.types import RunnerType


def create_runner(
    runner_type: RunnerType | None = None,
    library_dirs: list[str] | None = None,
) -> RunnerProtocol[DictPipeOutputAbstract]:
    """Create a runner instance based on the given type or configuration.

    When no runner_type is provided, reads the default from credentials.
    For pipelex, falls back to API if pipelex is not installed.

    Args:
        runner_type: Runner type to create. None means auto-detect.
        library_dirs: Directories to pass via -L to pipelex for library search.

    Returns:
        A RunnerProtocol instance.
    """
    if runner_type is None:
        credentials = load_credentials()
        configured = credentials["runner"]
        try:
            runner_type = RunnerType(configured)
        except ValueError:
            runner_type = RunnerType.API

    match runner_type:
        case RunnerType.API:
            return ApiRunner()
        case RunnerType.PIPELEX:
            if shutil.which("pipelex") is not None:
                return PipelexRunner(library_dirs=library_dirs)
            return ApiRunner()
