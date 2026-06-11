from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Protocol

from typing_extensions import runtime_checkable

from mthds.client.pipeline import PipeOutputT

if TYPE_CHECKING:
    from mthds.client.pipeline import RunResult, StartAck
    from mthds.client.protocol_models import ModelCategory, ModelDeck, ValidationReport, VersionInfo
    from mthds.models.pipe_output import VariableMultiplicity
    from mthds.models.pipeline_inputs import PipelineInputs
    from mthds.models.stuff import StuffType
    from mthds.models.working_memory import WorkingMemoryAbstract


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
            RunStillRunningError: If the server answers `202 + StartAck` (the
                protocol's optional async degrade) instead of a final result.
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
        pipeline_run_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> StartAck[PipeOutputT]:
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
            pipeline_run_id: Client-supplied run identifier — bare runners only.
                The hosted API always generates the id server-side and rejects a
                client-supplied one with 422 (never silently ignores it).
            extra: Implementation-defined extension args, merged into the
                request body as top-level properties. The server is the source
                of truth for what it accepts.

        Returns:
            StartAck with the authoritative `pipeline_run_id` and `created_at` timestamp

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
            ModelDeck with presets, aliases, and routing waterfalls.
        """
        ...

    @abstractmethod
    async def version(self) -> VersionInfo:
        """Protocol and implementation versions (always public on API runners).

        Returns:
            VersionInfo — the handshake clients use for feature detection.
        """
        ...
