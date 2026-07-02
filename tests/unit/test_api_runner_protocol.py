"""Tests for MthdsAPIClient's protocol discovery + validation surface (validate/models/version), httpx mocked."""

import asyncio
import inspect

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import InvalidValidationReport, ModelCategory, ModelDeck, ValidationReport, VersionInfo
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.client import MthdsAPIClient

_BASE_URL = "http://localhost:8081"


def _response(status_code: int, *, json: object = None, headers: dict[str, str] | None = None) -> httpx.Response:
    """Build a constructed httpx.Response with a request attached (so raise_for_status works)."""
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
        """The abstract interface has no implementation extensions — only basic args + the generic extra passthrough."""
        execute_params = set(inspect.signature(MTHDSProtocol.execute).parameters)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        start_params = set(inspect.signature(MTHDSProtocol.start).parameters)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        basic = {"self", "pipe_code", "mthds_contents", "inputs", "output_name", "output_multiplicity", "dynamic_output_concept_ref", "extra"}
        assert execute_params == basic
        assert start_params == basic

    # ── validate ─────────────────────────────────────────────────

    def test_validate_posts_contents_and_parses_valid_report(self, mocker: MockerFixture) -> None:
        """A 200 valid verdict posts mthds_contents + allow_signatures and parses the valid arm."""
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

        report = asyncio.run(client.validate(['domain = "answer"'], allow_signatures=True))
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/validate"
        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        # `to_json` emits compact JSON (no spaces after ':' / ',').
        assert '"mthds_contents":["domain = \\"answer\\""]' in sent
        assert '"allow_signatures":true' in sent
        # No extra passed → mthds_sources is omitted from the request body.
        assert "mthds_sources" not in sent
        assert isinstance(report, ValidationReport)
        assert report.is_valid is True
        # Implementation artifacts (bundle_blueprint, graph_spec, …) ride model_extra on the
        # neutral protocol arm — the `pipelex-sdk` subclass narrows them to typed fields.
        assert (report.model_extra or {})["bundle_blueprint"] == {"domain": "answer"}

    def test_validate_threads_mthds_sources(self, mocker: MockerFixture) -> None:
        """A server extension arg (mthds_sources) rides the generic `extra` passthrough into the request body."""
        client = self._client()
        body: dict[str, object] = {"is_valid": True, "message": "ok"}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        asyncio.run(client.validate(['domain = "answer"'], extra={"mthds_sources": ["answer.mthds"]}))
        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        assert '"mthds_sources":["answer.mthds"]' in sent

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

        report = asyncio.run(client.validate(["domain = "]))
        assert isinstance(report, InvalidValidationReport)
        assert report.is_valid is False
        # Neutral arm: `category` is a plain string and `pipe_code` rides model_extra — the
        # `pipelex-sdk` subclass narrows category to its closed enum and types the locators.
        assert report.validation_errors[0].category == "pipe_validation"
        assert (report.validation_errors[0].model_extra or {})["pipe_code"] == "summarize"

    def test_validate_no_verdict_response_raises_http_error(self, mocker: MockerFixture) -> None:
        """A request-shape 422 (no verdict could be produced) surfaces as an HTTP error, not a report.

        The 422 is the server's verdict on the request shape; this client does no local
        validation of the request beyond the `extra` protocol-arg guard.
        """
        client = self._client()
        body = {"type": "about:blank", "title": "Malformed request", "status": 422}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(422, json=body)))

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.validate(["domain = "]))

    def test_validate_extra_rejects_protocol_arg(self) -> None:
        """A protocol arg smuggled through `extra` is rejected client-side (mirrors the execute/start guard)."""
        client = self._client()
        with pytest.raises(PipelineRequestError):
            asyncio.run(client.validate(['domain = "answer"'], extra={"mthds_contents": ["x"]}))

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

    def test_models_category_filter_rides_querystring(self, mocker: MockerFixture) -> None:
        """A category filter is sent as ?type=<category>."""
        client = self._client()
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json={})))

        asyncio.run(client.models(ModelCategory.LLM))
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/models?type=llm"

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
