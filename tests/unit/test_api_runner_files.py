import asyncio
from collections import UserDict
from types import MappingProxyType
from typing import Any

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.method_tree.file_entry import FileEntry, MethodFiles
from mthds.protocol.exceptions import PipelineRequestError
from mthds.runners.api.client import MthdsAPIClient
from tests.unit.test_data import ExecuteWireResponses, MethodFileMaps

_BASE_URL = "http://localhost:8081"

# Each run route, with the success status and body a compliant runner answers.
_RUN_ROUTES: list[tuple[str, int, dict[str, Any]]] = [
    ("execute", 200, ExecuteWireResponses.REDUCED),
    ("start", 202, {"pipeline_run_id": "run_7f3a"}),
]


def _response(status_code: int, *, json: object) -> httpx.Response:
    return httpx.Response(status_code, json=json, request=httpx.Request("POST", f"{_BASE_URL}/x"))


class TestMthdsAPIClientFiles:
    @pytest.fixture(autouse=True)
    def _mock_config(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "mthds.runners.api.client.load_config",
            return_value={"api_key": "", "base_url": "", "runner": "api"},
        )

    def _client(self) -> MthdsAPIClient:
        return MthdsAPIClient(api_key="test-token", base_url=_BASE_URL)

    @pytest.mark.parametrize(("route", "status", "wire_response"), _RUN_ROUTES)
    @pytest.mark.parametrize(
        ("pipe_code", "expected_body"),
        [
            pytest.param("answer", '{"pipe_code":"answer","files":' + MethodFileMaps.MIXED_WIRE + "}", id="a named pipe"),
            pytest.param(None, '{"files":' + MethodFileMaps.MIXED_WIRE + "}", id="the method's main pipe"),
        ],
    )
    def test_run_sends_the_method_as_files(
        self,
        mocker: MockerFixture,
        route: str,
        status: int,
        wire_response: dict[str, Any],
        pipe_code: str | None,
        expected_body: str,
    ) -> None:
        """A run carries the method as `files`, each entry in its wire form, in the order given, and nothing else."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(status, json=wire_response)))

        asyncio.run(getattr(client, route)(pipe_code=pipe_code, files=MethodFileMaps.MIXED))

        assert send_mock.call_args.args == ("POST", f"{_BASE_URL}/v1/{route}")
        assert send_mock.call_args.kwargs["content"].decode("utf-8") == expected_body

    def test_validate_sends_the_method_as_files(self, mocker: MockerFixture) -> None:
        """A validation carries the method as `files` beside `allow_signatures`, and nothing else."""
        client = self._client()
        body: dict[str, object] = {"is_valid": True, "is_runnable": True, "pending_signatures": []}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        asyncio.run(client.validate(MethodFileMaps.MIXED))

        assert send_mock.call_args.args == ("POST", f"{_BASE_URL}/v1/validate")
        assert send_mock.call_args.kwargs["content"].decode("utf-8") == '{"files":' + MethodFileMaps.MIXED_WIRE + ',"allow_signatures":false}'

    @pytest.mark.parametrize(
        ("route", "status", "wire_response", "expected_tail"),
        [
            ("execute", 200, ExecuteWireResponses.REDUCED, "}"),
            ("start", 202, {"pipeline_run_id": "run_7f3a"}, "}"),
            ("validate", 200, {"is_valid": True, "is_runnable": True, "pending_signatures": []}, ',"allow_signatures":false}'),
        ],
    )
    @pytest.mark.parametrize(
        "files",
        [
            pytest.param(MappingProxyType(MethodFileMaps.MIXED), id="a read-only mapping proxy"),
            pytest.param(UserDict[str, FileEntry](MethodFileMaps.MIXED), id="a UserDict"),
        ],
    )
    def test_any_mapping_travels_as_the_same_files_map(
        self,
        mocker: MockerFixture,
        route: str,
        status: int,
        wire_response: dict[str, Any],
        expected_tail: str,
        files: MethodFiles,
    ) -> None:
        """`files` is typed as any `Mapping`, so a mapping that is no dict travels exactly as the dict holding the same entries."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(status, json=wire_response)))

        asyncio.run(getattr(client, route)(files=files))

        assert send_mock.call_args.kwargs["content"].decode("utf-8") == '{"files":' + MethodFileMaps.MIXED_WIRE + expected_tail

    @pytest.mark.parametrize("route", ["execute", "start", "validate"])
    def test_an_empty_files_map_is_refused_before_any_request(self, mocker: MockerFixture, route: str) -> None:
        """A method tree holds at least one file, so an empty map is refused here rather than sent for a 422."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock())

        with pytest.raises(PipelineRequestError, match="files holds no file") as exc_info:
            asyncio.run(getattr(client, route)(files={}))

        send_mock.assert_not_called()
        assert exc_info.value.problem.code == "client.argument_invalid"
        assert exc_info.value.problem.as_wire()["params"] == {"argument": "files", "reason": "empty"}

    @pytest.mark.parametrize(("route", "status", "wire_response"), _RUN_ROUTES)
    def test_files_smuggled_through_extra_is_refused(self, mocker: MockerFixture, route: str, status: int, wire_response: dict[str, Any]) -> None:
        """`files` is the protocol's own run source now, so it is passed by name and never through `extra`."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(status, json=wire_response)))

        with pytest.raises(PipelineRequestError, match=r"extra carries protocol args \['files'\]"):
            asyncio.run(getattr(client, route)(pipe_code="answer", extra={"files": MethodFileMaps.ONE_BUNDLE}))

        send_mock.assert_not_called()

    @pytest.mark.parametrize(("route", "status", "wire_response"), _RUN_ROUTES)
    def test_inline_contents_are_no_protocol_arg(self, mocker: MockerFixture, route: str, status: int, wire_response: dict[str, Any]) -> None:
        """`mthds_contents` left the protocol: a runner that still takes it as its own extension receives it through `extra`, untouched."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(status, json=wire_response)))

        asyncio.run(getattr(client, route)(extra={"mthds_contents": [MethodFileMaps.BUNDLE]}))

        assert send_mock.call_args.kwargs["content"] == b'{"mthds_contents":["domain = \\"answer\\"\\nmain_pipe = \\"answer\\"\\n"]}'
