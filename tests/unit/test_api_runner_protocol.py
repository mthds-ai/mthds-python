"""Tests for MthdsAPIClient's protocol discovery + validation surface (validate/models/version), httpx mocked."""

import asyncio
import inspect

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.protocol.models import ModelCategory, ModelDeck, ValidationReport, VersionInfo
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
    def _mock_credentials(self, mocker: MockerFixture) -> None:
        """Keep construction hermetic — never touch the real credentials file/env."""
        mocker.patch(
            "mthds.runners.api.client.load_credentials",
            return_value={"api_key": "", "api_url": "", "runner": "api", "telemetry": "0"},
        )

    def _client(self) -> MthdsAPIClient:
        return MthdsAPIClient(api_token="test-token", api_base_url=_BASE_URL)

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

    def test_validate_posts_contents_and_parses_report(self, mocker: MockerFixture) -> None:
        """Validate posts to /v1/validate with mthds_contents + allow_signatures and parses the report."""
        client = self._client()
        body: dict[str, object] = {"blueprint": {"domain": "answer"}, "graph_spec": {"nodes": []}, "pipe_structures": {}}  # implementation artifacts
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        report = asyncio.run(client.validate(['domain = "answer"'], allow_signatures=True))
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/validate"
        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        assert '"allow_signatures": true' in sent
        assert isinstance(report, ValidationReport)
        # The protocol declares no body fields — implementation artifacts pass through as extensions.
        assert report.model_extra is not None
        assert report.model_extra["blueprint"] == {"domain": "answer"}

    def test_validate_invalid_bundle_raises_http_error(self, mocker: MockerFixture) -> None:
        """A 422 problem (invalid bundle) surfaces as an HTTP error, not a report."""
        client = self._client()
        body = {"type": "about:blank", "title": "Validation failed", "status": 422}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(422, json=body)))

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.validate(["domain = "]))

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
            "protocol_version": "0.1.0",
            "runner_version": "0.3.0",
            "some_vendor_name": "vendor-runner",
        }
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        info = asyncio.run(client.version())
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/version"
        assert isinstance(info, VersionInfo)
        assert info.protocol_version == "0.1.0"
        assert info.runner_version == "0.3.0"
        # Implementation identification passes through as extensions, never named by the SDK.
        assert info.model_extra == {"some_vendor_name": "vendor-runner"}
