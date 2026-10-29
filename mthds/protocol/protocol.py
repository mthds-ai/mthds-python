from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Final, Generic, Protocol

from typing_extensions import runtime_checkable

from mthds.protocol.models import PipeOutputT

if TYPE_CHECKING:
    from mthds.method_tree.file_entry import MethodFiles
    from mthds.protocol.models import ModelCategory, ModelDeck, RunResultExecute, RunResultStart, ValidationResult, VersionInfo
    from mthds.protocol.pipe_output import VariableMultiplicity
    from mthds.protocol.pipeline_inputs import PipelineInputs
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract


PROTOCOL_VERSION: Final[str] = "2.0.1"
"""The MTHDS Protocol version this SDK implements.

This is a copy of a cut made by the standard, and the only place this library
states it. Every runner reports exactly this value as `protocol_version` in its
`version()` handshake — runners do not get to override or interpret it, because
the protocol version is a property of the standard rather than of any individual
runner.

It versions the HTTP runner contract only — the routes and the shapes they
exchange — and it moves on its own cadence: a release of the standard that
leaves those alone leaves this number exactly where it is, so it never tracks
`MTHDS_STANDARD_VERSION`. See https://mthds.ai/latest/spec/versioning/ ("The Protocol
Version") for what bumps it.
"""

CORE_ERROR_REGISTRY_VERSION: Final[str] = "8.0.1"
"""The version of the MTHDS core error registry this SDK reads problems against.

The registry is published with each release of the standard and carries that release's
number, so this is the standard version whose registry is vendored under
`vendor/mthds-error-registry/` and generated into `mthds.protocol.problem.registry`. A new
code moves no protocol number, so this moves on its own: following a registry release is a
re-vendor (`make vendor-error-registry`), a regeneration (`make generate-error-registry`)
and this one edit, and `tests/unit/test_error_registry_vendored.py` fails until all three
agree.
"""


@runtime_checkable
class MTHDSProtocol(Protocol, Generic[PipeOutputT]):
    """The MTHDS Protocol — the contract every MTHDS runner implements.

    Mirrors the standard's required routes (`mthds-protocol.openapi.yaml`):
    `execute`, `start`, `validate`, `models`, `version`. A runner is just a
    runner: it executes and validates methods, each sent as its whole method
    tree in `files`, and reports its model deck and version. The optional blob
    routes are served only by a runner that keeps a blob store, so they are not
    part of this interface: `MthdsAPIClient` carries them. Run polling is NOT
    part of the protocol — it is a hosted-API extension that `pipelex-sdk` carries.

    This interface carries the protocol's **basic** arguments only. An
    implementation may accept additional request properties; those are
    **extension args**, passed through the generic `extra` mapping and merged
    into the request body. The server that defines an extension arg is the one
    that handles it — extension args never appear in this SDK.
    """

    @abstractmethod
    async def execute(
        self,
        pipe_code: str | None = None,
        files: MethodFiles | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunResultExecute[PipeOutputT]:
        """Execute a method synchronously and wait for its completion.

        Args:
            pipe_code: The code identifying the pipe to execute: a pipe the runner
                already holds, or one declared in a bundle of `files`. Without it, the
                run starts at the method's `main_pipe`.
            files: The method to load, as its whole method tree: a map from tree
                path to file entry (its text, `{base64}` or `{sha256, size}`)
            inputs: Inputs passed to the method
            output_name: Target output slot name
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for dynamic output concept
            extra: Implementation-defined extension args, merged into the
                request body as top-level properties. The server is the source
                of truth for what it accepts.

        Returns:
            RunResultExecute — the completed run: `pipeline_run_id` + `pipe_output`.

        Raises:
            PipelineRequestError: From the API runner, for every failure of the call,
                carrying it as a problem document under a registered code
                (`exc.problem`): `RunStillRunningError` when the server answers 202
                (the protocol's optional async degrade) instead of a final result,
                `ApiResponseError` when it answers non-2xx or a success the client
                cannot read, and `ApiTransportError` when no answer came back. Each
                implementation names its own errors: the local `PipelexRunner` raises
                `PipelexRunnerError`, which carries no problem yet.
        """
        ...

    @abstractmethod
    async def start(
        self,
        pipe_code: str | None = None,
        files: MethodFiles | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunResultStart:
        """Start a method asynchronously without waiting for completion.

        How completion is later delivered (webhooks, polling, anything else) is
        implementation-defined and outside the protocol.

        Args:
            pipe_code: The code identifying the pipe to execute: a pipe the runner
                already holds, or one declared in a bundle of `files`. Without it, the
                run starts at the method's `main_pipe`.
            files: The method to load, as its whole method tree: a map from tree
                path to file entry (its text, `{base64}` or `{sha256, size}`)
            inputs: Inputs passed to the method
            output_name: Target output slot name
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for dynamic output concept
            extra: Implementation-defined extension args, merged into the
                request body as top-level properties. The server is the source
                of truth for what it accepts.

        Returns:
            RunResultStart — the authoritative server-generated `pipeline_run_id`
            (no output yet)

        Raises:
            PipelineRequestError: From the API runner, for every failure of the call,
                carrying it as a problem document under a registered code
                (`exc.problem`): `ApiResponseError` when the server answers non-2xx or
                a success the client cannot read, and `ApiTransportError` when no
                answer came back. Each implementation names its own errors: the local
                `PipelexRunner` does not start runs and raises `NotImplementedError`.
        """
        ...

    @abstractmethod
    async def validate(
        self,
        files: MethodFiles,
        allow_signatures: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Parse, validate, and dry-run a method: every bundle of its tree, and every file a bundle names.

        Args:
            files: The method to validate, as its whole method tree: a map from tree
                path to file entry, holding at least one file
            allow_signatures: When True, the validation sweep tolerates
                unimplemented pipe signatures. Strict by default.
            extra: Implementation-defined extension args, merged into the
                request body as top-level properties. The server is the source
                of truth for what it accepts.

        Returns:
            The 200-diagnostic verdict union, discriminated on `is_valid`: a
            `ValidationReport` (`is_valid: true`, structural artifacts) or an
            `InvalidValidationReport` (`is_valid: false`, its faults in `errors[]`).
            An invalid bundle is a produced verdict, NOT a raised 422 — non-2xx is
            reserved for "no verdict could be produced". (The local CLI runner is the
            documented exception: it surfaces an invalid bundle as a raised
            `PipelexRunnerError` from the CLI's exit code.)
        """
        ...

    @abstractmethod
    async def models(self, category: ModelCategory | None = None) -> ModelDeck:
        """The model deck this runner can route to.

        Args:
            category: Optional deck filter (`llm`, `extract`, `img_gen`,
                `search`, `judgment`). The filter is closed: a runner answers a
                category it does not define with a `422`.

        Returns:
            ModelDeck with the models this runner can route to (base fields
            + any implementation extensions). An entry whose category this
            package does not recognize is kept with its raw `type` string.
        """
        ...

    @abstractmethod
    async def version(self) -> VersionInfo:
        """Protocol and runner versions (always public on API runners).

        Returns:
            VersionInfo — the handshake clients use for feature detection.
        """
        ...
