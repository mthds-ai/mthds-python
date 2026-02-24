from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Generic, Protocol

from typing_extensions import runtime_checkable

from mthds.client.pipeline import PipeOutputT

if TYPE_CHECKING:
    from mthds.client.models.pipe_output import VariableMultiplicity
    from mthds.client.models.pipeline_inputs import PipelineInputs
    from mthds.client.models.stuff import StuffType
    from mthds.client.models.working_memory import WorkingMemoryAbstract
    from mthds.client.pipeline import PipelineExecuteResponse, PipelineStartResponse


@runtime_checkable
class RunnerProtocol(Protocol, Generic[PipeOutputT]):
    """Protocol defining the contract for a method runner."""

    @abstractmethod
    async def execute_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_content: str | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_code: str | None = None,
    ) -> PipelineExecuteResponse[PipeOutputT]:
        """Execute a pipeline synchronously and wait for its completion.

        Args:
            pipe_code (str): The code identifying the pipeline to execute
            mthds_content (str | None): Content of the pipeline bundle to execute
            inputs (PipelineInputs | WorkingMemoryAbstract | None): Inputs passed to the pipeline
            output_name (str | None): Target output slot name
            output_multiplicity (PipeOutputMultiplicity | None): Output multiplicity setting
            dynamic_output_concept_code (str | None): Override for dynamic output concept
        Returns:
            PipelineResponse: Complete execution results including pipeline state and output

        Raises:
            HTTPException: On execution failure or error
            ClientAuthenticationError: If API token is missing for API execution

        """
        ...

    @abstractmethod
    async def start_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_content: str | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_code: str | None = None,
    ) -> PipelineStartResponse[PipeOutputT]:
        """Start a pipeline execution asynchronously without waiting for completion.

        Args:
            pipe_code (str): The code identifying the pipeline to execute
            mthds_content (str | None): Content of the pipeline bundle to execute
            inputs (PipelineInputs | WorkingMemory | None): Inputs passed to the pipeline
            output_name (str | None): Target output slot name
            output_multiplicity (VariableMultiplicity | None): Output multiplicity setting
            dynamic_output_concept_code (str | None): Override for dynamic output concept

        Returns:
            PipelineResponse: Initial response with pipeline_run_id and created_at timestamp

        Raises:
            HTTPException: On pipeline start failure
            ClientAuthenticationError: If API token is missing for API execution

        """
        ...
