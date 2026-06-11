"""Runner factory — creates the appropriate runner based on type or configuration."""

import shutil

from mthds.config.credentials import load_credentials
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.models import DictPipeOutputAbstract
from mthds.runners.exceptions import ClientAuthenticationError
from mthds.runners.pipelex_runner import PipelexRunner, PipelexRunnerError
from mthds.runners.types import RunnerType


def create_runner(
    runner_type: RunnerType | None = None,
    library_dirs: list[str] | None = None,
) -> MTHDSProtocol[DictPipeOutputAbstract]:
    """Create a runner instance based on the given type or configuration.

    When no runner_type is provided, reads the default from credentials.
    For pipelex, falls back to API if pipelex is not installed.

    The API runner IS the client: `MthdsAPIClient` implements the protocol
    directly (plus the hosted run-lifecycle extension), so there is no
    separate wrapper class.

    Args:
        runner_type: Runner type to create. None means auto-detect.
        library_dirs: Directories to pass via -L to pipelex for library search.

    Returns:
        An MTHDSProtocol instance.
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
            return MthdsAPIClient()
        case RunnerType.PIPELEX:
            if shutil.which("pipelex") is not None:
                return PipelexRunner(library_dirs=library_dirs)
            # Fallback to the API client. Its constructor resolves credentials
            # eagerly — in a credential-less environment that asked for the
            # LOCAL runner, surface one combined, actionable error instead of
            # a bare authentication failure.
            try:
                return MthdsAPIClient()
            except ClientAuthenticationError as exc:
                msg = (
                    "The pipelex runner was requested but 'pipelex' is not on PATH, and the API "
                    "fallback has no credentials configured. Install pipelex "
                    "(curl -sSL https://pipelex.com/install.sh | sh) or set MTHDS_API_KEY."
                )
                raise PipelexRunnerError(msg) from exc
