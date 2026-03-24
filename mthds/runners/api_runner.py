"""API runner — implements RunnerProtocol by delegating to MthdsAPIClient."""

from typing_extensions import override

from mthds.client.client import MthdsAPIClient
from mthds.client.pipeline import DictPipelineExecuteResponse, DictPipelineStartResponse
from mthds.client.protocol import RunnerProtocol
from mthds.models.pipe_output import DictPipeOutputAbstract, VariableMultiplicity
from mthds.models.pipeline_inputs import PipelineInputs
from mthds.models.stuff import StuffType
from mthds.models.working_memory import WorkingMemoryAbstract
from mthds.runners.types import RunnerType


class ApiRunner(RunnerProtocol[DictPipeOutputAbstract]):
    """Runner that delegates to the MTHDS API via MthdsAPIClient."""

    @property
    def runner_type(self) -> RunnerType:
        """Return the runner type."""
        return RunnerType.API

    @override
    async def execute_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_code: str | None = None,
    ) -> DictPipelineExecuteResponse:
        """Execute a pipeline synchronously via the MTHDS API.

        Args:
            pipe_code: The code identifying the pipeline to execute.
            mthds_contents: List of MTHDS bundle contents to load.
            inputs: Inputs passed to the pipeline.
            output_name: Name of the output slot to write to.
            output_multiplicity: Output multiplicity setting.
            dynamic_output_concept_code: Override for the dynamic output concept code.

        Returns:
            Complete execution results including pipeline state and output.
        """
        client = MthdsAPIClient()
        try:
            client.start_client()
            return await client.execute_pipeline(
                pipe_code=pipe_code,
                mthds_contents=mthds_contents,
                inputs=inputs,
                output_name=output_name,
                output_multiplicity=output_multiplicity,
                dynamic_output_concept_code=dynamic_output_concept_code,
            )
        finally:
            await client.close()

    @override
    async def start_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_code: str | None = None,
    ) -> DictPipelineStartResponse:
        """Start a pipeline execution asynchronously via the MTHDS API.

        Args:
            pipe_code: The code identifying the pipeline to execute.
            mthds_contents: List of MTHDS bundle contents to load.
            inputs: Inputs passed to the pipeline.
            output_name: Name of the output slot to write to.
            output_multiplicity: Output multiplicity setting.
            dynamic_output_concept_code: Override for the dynamic output concept code.

        Returns:
            Initial response with pipeline_run_id and created_at timestamp.
        """
        client = MthdsAPIClient()
        try:
            client.start_client()
            return await client.start_pipeline(
                pipe_code=pipe_code,
                mthds_contents=mthds_contents,
                inputs=inputs,
                output_name=output_name,
                output_multiplicity=output_multiplicity,
                dynamic_output_concept_code=dynamic_output_concept_code,
            )
        finally:
            await client.close()
