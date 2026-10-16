"""Tests for MthdsAPIClient's protocol discovery + validation surface (validate/models/version), httpx mocked."""

import asyncio
import inspect
from typing import Any

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import InvalidValidationReport, ModelCategory, ModelDeck, ValidationReport, VersionInfo
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.exceptions import ApiResponseError
from tests.unit.test_data import ExecuteWireResponses, MethodFileMaps, ModelDeckWireBodies

_BASE_URL = "http://localhost:8081"


def _response(status_code: int, *, json: object = None, headers: dict[str, str] | None = None) -> httpx.Response:
    """Build a constructed httpx.Response with a request attached."""
    request = httpx.Request("GET", f"{_BASE_URL}/x")
    if json is None:
        return httpx.Response(status_code, headers=headers or {}, request=request)
    return httpx.Response(status_code, json=json, headers=headers or {}, request=request)


class TestMthdsAPIClientProtocol:
    """Tests for validate/models/version and the protocol conformance of the client."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, mocker: MockerFixture) -> None:
        """Keep construction hermetic — never touch the real config file/env."""
        mocker.patch(
            "mthds.runners.api.client.load_config",
            return_value={"api_key": "", "base_url": "", "runner": "api"},
        )

    def _client(self) -> MthdsAPIClient:
        return MthdsAPIClient(api_key="test-token", base_url=_BASE_URL)

    def test_client_satisfies_protocol(self) -> None:
        """MthdsAPIClient structurally satisfies MTHDSProtocol (runtime-checkable)."""
        client = self._client()
        assert isinstance(client, MTHDSProtocol)

    def test_protocol_interface_carries_basic_args_only(self) -> None:
        """The abstract interface has no implementation extensions — only basic args + the generic extra passthrough.

        The method travels as `files`, its whole tree, on the run and validate routes alike: protocol
        1.0.0 has no `mthds_contents`.
        """
        execute_params = set(inspect.signature(MTHDSProtocol.execute).parameters)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        start_params = set(inspect.signature(MTHDSProtocol.start).parameters)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        validate_params = set(inspect.signature(MTHDSProtocol.validate).parameters)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        basic = {"self", "pipe_code", "files", "inputs", "output_name", "output_multiplicity", "dynamic_output_concept_ref", "extra"}
        assert execute_params == basic
        assert start_params == basic
        assert validate_params == {"self", "files", "allow_signatures", "extra"}

    # ── construction ─────────────────────────────────────────────

    def test_request_timeout_seconds_defaults_to_ceiling(self) -> None:
        """With no override, the per-request timeout is the runner blocking-execute ceiling."""
        client = self._client()
        assert client.request_timeout_seconds == 1200.0

    @pytest.mark.parametrize("timeout_seconds", [30.0, 0.0])
    def test_request_timeout_seconds_override(self, timeout_seconds: float) -> None:
        """An explicit `request_timeout_seconds` sets the per-instance ceiling — including a
        falsy `0.0` (presence semantics, so the same-named parameter means the same thing
        here and in `pipelex-sdk`'s `PipelexAPIClient`).
        """
        client = MthdsAPIClient(api_key="test-token", base_url=_BASE_URL, request_timeout_seconds=timeout_seconds)
        assert client.request_timeout_seconds == timeout_seconds

    # ── validate ─────────────────────────────────────────────────

    def test_validate_posts_files_and_parses_valid_report(self, mocker: MockerFixture) -> None:
        """A 200 valid verdict posts files + allow_signatures and parses the valid arm."""
        client = self._client()
        body: dict[str, object] = {
            "is_valid": True,
            "bundle_blueprint": {"domain": "answer"},
            "graph_spec": {"nodes": []},
            "pipe_io_contracts": {},
            "validated_pipes": [],
            "pending_signatures": [],
            "is_runnable": True,
            "message": "Validation succeeded.",
        }
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        report = asyncio.run(client.validate(MethodFileMaps.ONE_BUNDLE, allow_signatures=True))
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/validate"
        # `to_json` emits compact JSON (no spaces after ':' / ','), and no extra means no other key.
        assert (
            send_mock.call_args.kwargs["content"]
            == b'{"files":{"main.mthds":"domain = \\"answer\\"\\nmain_pipe = \\"answer\\"\\n"},"allow_signatures":true}'
        )
        assert isinstance(report, ValidationReport)
        assert report.is_valid is True
        # Implementation artifacts (bundle_blueprint, graph_spec, …) ride model_extra on the
        # neutral protocol arm — the `pipelex-sdk` subclass narrows them to typed fields.
        assert (report.model_extra or {})["bundle_blueprint"] == {"domain": "answer"}

    def test_validate_threads_a_server_extension(self, mocker: MockerFixture) -> None:
        """A server extension arg (`render`) rides the generic `extra` passthrough into the request body."""
        client = self._client()
        body: dict[str, object] = {"is_valid": True, "message": "ok"}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        asyncio.run(client.validate(MethodFileMaps.ONE_BUNDLE, extra={"render": ["markdown"]}))
        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        assert sent.endswith(',"allow_signatures":false,"render":["markdown"]}')

    def test_validate_invalid_bundle_returns_200_invalid_report(self, mocker: MockerFixture) -> None:
        """An invalid bundle is a 200 diagnostic verdict — NOT a silent pass, NOT a raise.

        Regression guard for the 200-diagnostic reframe: the old client did
        `raise_for_status()` then parsed into an empty report, so a 200 invalid body
        would have been mistaken for valid.
        """
        client = self._client()
        body: dict[str, object] = {
            "is_valid": False,
            "validation_errors": [{"category": "pipe_validation", "message": "Unknown concept.", "pipe_code": "summarize"}],
            "pending_signatures": [],
            "is_runnable": False,
            "message": "Validation found errors.",
        }
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        report = asyncio.run(client.validate({"main.mthds": "domain = "}))
        assert isinstance(report, InvalidValidationReport)
        assert report.is_valid is False
        # Neutral arm: `category` is a plain string and `pipe_code` rides model_extra — the
        # `pipelex-sdk` subclass narrows category to its closed enum and types the locators.
        assert report.validation_errors[0].category == "pipe_validation"
        assert (report.validation_errors[0].model_extra or {})["pipe_code"] == "summarize"

    def test_validate_no_verdict_response_raises_api_response_error(self, mocker: MockerFixture) -> None:
        """A request-shape 422 (no verdict could be produced) surfaces as an ApiResponseError, not a report.

        The 422 is the server's verdict on the request shape; this client does no local
        validation of the request beyond the `extra` protocol-arg guard.
        """
        client = self._client()
        body = {"type": "about:blank", "title": "Malformed request", "status": 422}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(422, json=body)))

        with pytest.raises(ApiResponseError) as exc_info:
            asyncio.run(client.validate({"main.mthds": "domain = "}))
        assert exc_info.value.status == 422
        assert exc_info.value.title == "Malformed request"
        assert str(exc_info.value) == "API POST /v1/validate failed (422): Malformed request"

    @pytest.mark.parametrize("smuggled", [{"files": {"other.mthds": "x"}}, {"allow_signatures": True}])
    def test_validate_extra_rejects_protocol_arg(self, smuggled: dict[str, Any]) -> None:
        """A protocol arg smuggled through `extra` is rejected client-side (mirrors the execute/start guard)."""
        client = self._client()
        with pytest.raises(PipelineRequestError, match="pass them as named parameters"):
            asyncio.run(client.validate(MethodFileMaps.ONE_BUNDLE, extra=smuggled))

    # ── models ───────────────────────────────────────────────────

    def test_models_parses_deck(self, mocker: MockerFixture) -> None:
        """Models hits /v1/models and parses the deck shape."""
        client = self._client()
        body: dict[str, object] = {
            "models": [{"name": "gpt-test", "type": "llm"}],
            "aliases": {"best": "gpt-test"},
            "waterfalls": {"default": ["gpt-test"]},
        }
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        deck = asyncio.run(client.models())
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/models"
        assert isinstance(deck, ModelDeck)
        assert deck.models[0].name == "gpt-test"
        # Implementation routing metadata passes through as extensions, never named by the SDK.
        assert deck.model_extra is not None
        assert deck.model_extra["aliases"] == {"best": "gpt-test"}

    def test_models_keeps_a_category_it_does_not_know(self, mocker: MockerFixture) -> None:
        """A deck from a runner of a later protocol minor, carrying a category this package does not know,
        comes back whole instead of failing the call.
        """
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=ModelDeckWireBodies.MIXED_CATEGORIES)))

        deck = asyncio.run(client.models())
        assert [model.type for model in deck.models] == [ModelCategory.LLM, ModelCategory.JUDGMENT, "speech_to_text", None]

    @pytest.mark.parametrize(
        ("category", "expected_query"),
        [
            (ModelCategory.LLM, "type=llm"),
            (ModelCategory.EXTRACT, "type=extract"),
            (ModelCategory.IMG_GEN, "type=img_gen"),
            (ModelCategory.SEARCH, "type=search"),
            (ModelCategory.JUDGMENT, "type=judgment"),
        ],
    )
    def test_models_category_filter_rides_querystring(self, mocker: MockerFixture, category: ModelCategory, expected_query: str) -> None:
        """A category filter is sent as ?type=<category>."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json={})))

        asyncio.run(client.models(category))
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/models?{expected_query}"

    # ── version ──────────────────────────────────────────────────

    def test_version_parses_handshake(self, mocker: MockerFixture) -> None:
        """Version hits /v1/version and parses the VersionInfo handshake."""
        client = self._client()
        body = {
            "protocol_version": "0.6.0",
            "runner_version": "0.3.0",
            "some_vendor_name": "vendor-runner",
        }
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        info = asyncio.run(client.version())
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/version"
        assert isinstance(info, VersionInfo)
        assert info.protocol_version == "0.6.0"
        assert info.runner_version == "0.3.0"
        # Implementation identification passes through as extensions, never named by the SDK.
        assert info.model_extra == {"some_vendor_name": "vendor-runner"}

    # ── execute / start run sources ───────────────────────────────

    @pytest.mark.parametrize(
        ("route", "wire_response"),
        [("execute", ExecuteWireResponses.REDUCED), ("start", {"pipeline_run_id": "run_7f3a"})],
    )
    def test_run_requires_something_to_run(self, route: str, wire_response: dict[str, Any], mocker: MockerFixture) -> None:
        """Neither a pipe, nor files, nor an extension arg: the call is refused before any request.

        The transport stub answers with a well-formed body on purpose. Were the guard removed,
        the call would run to completion and this test would report the guard's absence — rather
        than a parse error from a stub that could never have produced a result anyway.
        """
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=wire_response)))
        with pytest.raises(PipelineRequestError, match=f"must be provided to the API {route}"):
            asyncio.run(getattr(client, route)())
        send_mock.assert_not_called()

    @pytest.mark.parametrize(
        ("route", "wire_response"),
        [("execute", ExecuteWireResponses.REDUCED), ("start", {"pipeline_run_id": "run_7f3a"})],
    )
    def test_run_forwards_extension_args_without_interpreting_them(self, route: str, wire_response: dict[str, Any], mocker: MockerFixture) -> None:
        """`extra` is the server's to define, so this client forwards its keys without judging them.

        The combination sent here — a method tree beside a zipped bundle and inline contents — is
        illegal on `pipelex-api`, which is the runner that defines `bundle_b64` and still takes
        `mthds_contents`. They are that runner's extension args and not the protocol's, and
        `MthdsAPIClient` is documented as a client for any MTHDS-compliant runner, so it is the
        addressed server that answers for the combination. Pre-empting the refusal is the business
        of a client that takes those arguments by name, from the shared definitions in
        `mthds.protocol.options`.
        """
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=wire_response)))

        asyncio.run(getattr(client, route)(files=MethodFileMaps.ONE_BUNDLE, extra={"bundle_b64": "UEsDBA==", "mthds_contents": ["x"]}))

        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        assert '"files":{"main.mthds":' in sent
        assert '"bundle_b64":"UEsDBA=="' in sent
        assert '"mthds_contents":["x"]' in sent

    def test_execute_accepts_an_extension_arg_as_the_only_run_source(self, mocker: MockerFixture) -> None:
        """A server's own run source in `extra` satisfies the precondition and merges into the body as a top-level property."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=ExecuteWireResponses.REDUCED)))

        asyncio.run(client.execute(extra={"method_ref": "github.com/acme/methods/answer@v1.0.0"}))
        assert send_mock.call_args.kwargs["content"] == b'{"method_ref":"github.com/acme/methods/answer@v1.0.0"}'
