from typing import Any

import httpx
from typing_extensions import override

from mthds.client.exceptions import ClientAuthenticationError, PipelineRequestError
from mthds.client.models.pipe_output import DictPipeOutputAbstract, VariableMultiplicity
from mthds.client.models.pipeline_inputs import PipelineInputs
from mthds.client.models.stuff import StuffType
from mthds.client.models.working_memory import WorkingMemoryAbstract
from mthds.client.pipeline import DictPipelineExecuteResponse, DictPipelineStartResponse, PipelineRequest
from mthds.client.protocol import RunnerProtocol
from mthds.config.credentials import load_credentials


class MthdsAPIClient(RunnerProtocol[DictPipeOutputAbstract]):
    """A client for interacting with methods through the API."""

    def __init__(
        self,
        api_token: str | None = None,
        api_base_url: str | None = None,
    ):
        credentials = load_credentials()

        resolved_api_token = api_token or credentials["api_key"]
        if not resolved_api_token:
            msg = "API token is required for API execution. Set PIPELEX_API_KEY or run: mthds config set api-key <key>"
            raise ClientAuthenticationError(msg)
        self.api_token = resolved_api_token

        resolved_api_base_url = api_base_url or credentials["api_url"]
        if not resolved_api_base_url:
            msg = "API base URL is required for API execution. Set PIPELEX_API_URL or run: mthds config set api-url <url>"
            raise ClientAuthenticationError(msg)
        self.api_base_url = resolved_api_base_url

        self.client: httpx.AsyncClient | None = None

    def start_client(self) -> "MthdsAPIClient":
        """Initialize the HTTP client for API calls."""
        self.client = httpx.AsyncClient(base_url=self.api_base_url, headers={"Authorization": f"Bearer {self.api_token}"})
        return self

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _make_api_call(self, endpoint: str, pipeline_request: PipelineRequest | None = None) -> dict[str, Any]:
        """Make an API call to a method runner server.

        Args:
            endpoint: The API endpoint to call, relative to the base URL
            pipeline_request: A PipelineRequest object to send as the request body, or None if no body is needed
        Returns:
            dict[str, Any]: The JSON-decoded response from the server
        Raises:
            httpx.HTTPError: If the request fails or returns a non-200 status code

        """
        if not self.client:
            self.start_client()
            assert self.client is not None

        # Convert JSON string to UTF-8 bytes if not None
        content = pipeline_request.model_dump_json().encode("utf-8") if pipeline_request is not None else None
        response = await self.client.post(f"/{endpoint}", content=content, headers={"Content-Type": "application/json"}, timeout=1200)
        response.raise_for_status()
        response_data: dict[str, Any] = response.json()
        return response_data

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
        """Execute a pipeline synchronously and wait for its completion.

        Args:
            pipe_code: The code identifying the pipeline to execute
            mthds_content: Content of the pipeline bundle to execute
            inputs: Inputs passed to the pipeline
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_code: Override for the dynamic output concept code

        Returns:
            Complete execution results including pipeline state and output
        """
        if not pipe_code and not mthds_content:
            msg = "Either pipe_code or mthds_content must be provided to the API execute_pipeline."
            raise PipelineRequestError(msg)

        pipeline_request = PipelineRequest(
            pipe_code=pipe_code,
            mthds_content=mthds_content,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_code=dynamic_output_concept_code,
        )
        response = await self._make_api_call("v1/pipeline/execute", pipeline_request=pipeline_request)
        return DictPipelineExecuteResponse.from_api_response(response)

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
        """Start a pipeline execution asynchronously without waiting for completion.

        Args:
            pipe_code: The code identifying the pipeline to execute
            mthds_content: Content of the pipeline bundle to execute
            inputs: Inputs passed to the pipeline
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_code: Override for the dynamic output concept code

        Returns:
            Initial response with pipeline_run_id and created_at timestamp
        """
        if not pipe_code and not mthds_content:
            msg = "Either pipe_code or mthds_content must be provided to the API start_pipeline."
            raise PipelineRequestError(msg)

        pipeline_request = PipelineRequest(
            pipe_code=pipe_code,
            mthds_content=mthds_content,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_code=dynamic_output_concept_code,
        )
        response = await self._make_api_call("v1/pipeline/start", pipeline_request=pipeline_request)
        return DictPipelineStartResponse.from_api_response(response)
