import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.problem.registry import CORE_CODE_SPECS
from mthds.protocol.protocol import CORE_ERROR_REGISTRY_VERSION
from mthds.runners.api.client import MthdsAPIClient
from tests.unit.test_data import ProblemReadingCases

_DEFAULT_BASE_URL = "http://localhost:8081"
# The route a case that names none is sent on: one that creates nothing.
_DEFAULT_ROUTE = "GET /models"

_ROUTE_CALLS: dict[str, Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]] = {
    "POST /execute": lambda client: client.execute(pipe_code="summarize", mthds_contents=['domain = "legal"']),
    "POST /start": lambda client: client.start(pipe_code="summarize", mthds_contents=['domain = "legal"']),
    "POST /validate": lambda client: client.validate(['domain = "legal"']),
    "GET /models": lambda client: client.models(),
    "GET /version": lambda client: client.version(),
}


def _canonical(value: Any) -> str:
    """The canonical JSON both clients compare, which tells `2` from `2.0`."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def _handler(case_input: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """A transport handler that answers, or fails to answer, as the case says."""

    def handle(request: httpx.Request) -> httpx.Response:
        match case_input["kind"]:
            case "response":
                return httpx.Response(case_input["status"], content=case_input["body"].encode(), headers=case_input.get("headers", {}))
            case "unreachable":
                msg = "All connection attempts failed"
                raise httpx.ConnectError(msg, request=request)
            case "timeout":
                msg = "The read operation timed out"
                raise httpx.ReadTimeout(msg, request=request)
            case "lost_after_send":
                msg = "Server disconnected without sending a response."
                raise httpx.RemoteProtocolError(msg, request=request)
            case other:
                msg = f"The case file names an input kind '{other}' this test does not know."
                raise AssertionError(msg)

    return handle


class TestProblemReadingCases:
    @pytest.fixture(autouse=True)
    def _mock_config(self, mocker: MockerFixture) -> None:
        """Keep construction hermetic — never touch the real config file/env."""
        mocker.patch("mthds.runners.api.client.load_config", return_value={"api_key": "", "base_url": "", "runner": "api"})

    def test_the_case_file_targets_the_registry_this_package_reads(self) -> None:
        """The shared cases were built from the registry the package declares, so a registry upgrade rebuilds them."""
        assert ProblemReadingCases.DOCUMENT["registry_version"] == CORE_ERROR_REGISTRY_VERSION
        assert ProblemReadingCases.CASES

    @pytest.mark.parametrize("case", ProblemReadingCases.CASES, ids=[case["name"] for case in ProblemReadingCases.CASES])
    def test_every_answer_reads_as_a_problem(self, case: dict[str, Any]) -> None:
        """Whatever the client meets, an answer of any body, no answer or a lost connection, the call raises the case's problem."""
        case_input: dict[str, Any] = case["input"]
        client = MthdsAPIClient(
            api_key="test-token",
            base_url=case_input.get("base_url", _DEFAULT_BASE_URL),
            request_timeout_seconds=float(case_input.get("seconds", 1200)),
        )
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(_handler(case_input)))
        call = _ROUTE_CALLS[case_input.get("route", _DEFAULT_ROUTE)]

        async def scenario() -> None:
            try:
                await call(client)
            finally:
                await client.close()

        with pytest.raises(PipelineRequestError) as exc_info:
            asyncio.run(scenario())

        problem = exc_info.value.problem
        assert _canonical(problem.as_wire()) == _canonical(case["expected"]), case["description"]
        # A problem the client states itself is always under a code the core registry holds.
        if problem.code.startswith("client."):
            assert problem.code in CORE_CODE_SPECS
