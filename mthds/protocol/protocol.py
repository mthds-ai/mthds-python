from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Protocol

from typing_extensions import runtime_checkable

from mthds.protocol.models import PipeOutputT

if TYPE_CHECKING:
    from mthds.protocol.models import ModelCategory, ModelDeck, RunResult, ValidationReport, VersionInfo
    from mthds.protocol.pipe_output import VariableMultiplicity
    from mthds.protocol.pipeline_inputs import PipelineInputs
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract


@runtime_checkable
class MTHDSProtocol(Protocol, Generic[PipeOutputT]):
    """The MTHDS Protocol — the contract every MTHDS runner implements.

    Mirrors the standard's five routes (`mthds-protocol.openapi.yaml`):
    `execute`, `start`, `validate`, `models`, `version`. A runner is just a
    runner: it executes and validates methods, and reports its model deck and
    version. Run polling is NOT part of the protocol — it is a hosted-API
    extension carried by `MthdsAPIClient` only.

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
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunResult[PipeOutputT]:
        """Execute a method synchronously and wait for its completion.

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
            inputs: Inputs passed to the method
            output_name: Target output slot name
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for dynamic output concept
            extra: Implementation-defined extension args, merged into the
                request body as top-level properties. The server is the source
                of truth for what it accepts.

        Returns:
            Complete execution results including run state and output

        Raises:
            RunStillRunningError: If the server answers 202 (the protocol's
                optional async degrade) instead of a final result.
            ClientAuthenticationError: If an API token is missing for API execution.
        """
        ...

    @abstractmethod
    async def start(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunResult[PipeOutputT]:
        """Start a method asynchronously without waiting for completion.

        How completion is later delivered (webhooks, polling, anything else) is
        implementation-defined and outside the protocol.

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
            inputs: Inputs passed to the method
            output_name: Target output slot name
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for dynamic output concept
            extra: Implementation-defined extension args, merged into the
                request body as top-level properties. The server is the source
                of truth for what it accepts.

        Returns:
            RunResult with the authoritative server-generated `pipeline_run_id`
            (`pipe_output` absent)

        Raises:
            ClientAuthenticationError: If an API token is missing for API execution.
        """
        ...

    @abstractmethod
    async def validate(
        self,
        mthds_contents: list[str],
        allow_signatures: bool = False,
    ) -> ValidationReport:
        """Parse, validate, and dry-run an MTHDS bundle.

        Args:
            mthds_contents: MTHDS contents to load (always a list, even for one file)
            allow_signatures: When True, the validation sweep tolerates
                unimplemented pipe signatures. Strict by default.

        Returns:
            ValidationReport with the structural artifacts of a VALID bundle.
            Invalid bundles raise (HTTP 422 problem on API runners).
        """
        ...

    @abstractmethod
    async def models(self, category: ModelCategory | None = None) -> ModelDeck:
        """The model deck this runner can route to.

        Args:
            category: Optional deck filter (`llm`, `extract`, `img_gen`, `search`).

        Returns:
            ModelDeck with the models this runner can route to (base fields
            + any implementation extensions).
        """
        ...

    @abstractmethod
    async def version(self) -> VersionInfo:
        """Protocol and runner versions (always public on API runners).

        Returns:
            VersionInfo — the handshake clients use for feature detection.
        """
        ...
