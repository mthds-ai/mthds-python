import asyncio
import re
from typing import Any

import httpx
import pytest
from pytest_mock import MockerFixture
from typing_extensions import override

from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.user_agent import AppInfo, product_token
from mthds.version import __version__

_BASE_URL = "http://localhost:8081"
_VERSION_BODY: dict[str, str] = {"protocol_version": "0.6.0", "runner_version": "1.0.0"}
_INVALID_VALIDATION_BODY: dict[str, object] = {
    "is_valid": False,
    "validation_errors": [{"category": "pipe_validation", "message": "Unknown concept."}],
    "pending_signatures": [],
    "is_runnable": False,
    "message": "Validation found errors.",
}
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _WrapperClient(MthdsAPIClient):
    """A subclass shaped like `pipelex-sdk`'s: its own `__init__` without `super().__init__()`, its own `start_client`."""

    def __init__(self, api_key: str, base_url: str, app_info: AppInfo | None = None):  # pylint: disable=super-init-not-called
        self.init_user_agent(app_info)
        self.api_key = api_key
        self.base_url = base_url
        self.request_timeout_seconds = 30.0
        self.client = None

    @classmethod
    @override
    def user_agent_sdk_tokens(cls) -> tuple[str, ...]:
        return (product_token("pipelex-sdk-python", "0.11.0"), *super().user_agent_sdk_tokens())

    @override
    def start_client(self) -> MthdsAPIClient:
        # Deliberately omits User-Agent from the defaults: `_send` must still send it.
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {self.api_key}"})
        return self


class TestMthdsAPIClientUserAgent:
    @pytest.fixture(autouse=True)
    def _mock_config(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "mthds.runners.api.client.load_config",
            return_value={"api_key": "", "base_url": "", "runner": "api"},
        )

    @pytest.fixture
    def captured(self, mocker: MockerFixture) -> list[httpx.Request]:
        """Route every AsyncClient the client module builds through a MockTransport that records requests."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/validate"):
                return httpx.Response(200, json=_INVALID_VALIDATION_BODY)
            return httpx.Response(200, json=_VERSION_BODY)

        def make_client(**kwargs: Any) -> httpx.AsyncClient:
            return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

        mocker.patch("mthds.runners.api.client.httpx.AsyncClient", side_effect=make_client)
        return requests

    def test_lazy_start_sends_the_library_token(self, captured: list[httpx.Request]) -> None:
        """The first request lazily starts the client, and it already carries the header."""
        client = MthdsAPIClient(api_key="test-token", base_url=_BASE_URL)

        async def scenario() -> None:
            await client.version()
            await client.close()

        asyncio.run(scenario())
        user_agent = captured[0].headers["User-Agent"]
        assert re.fullmatch(rf"mthds-python/{re.escape(__version__)} python/\d+\.\d+\.\d+ \([^()]+\)", user_agent), user_agent
        assert captured[0].headers["Authorization"] == "Bearer test-token"

    def test_every_request_carries_the_header(self, captured: list[httpx.Request]) -> None:
        client = MthdsAPIClient(api_key="test-token", base_url=_BASE_URL)

        async def scenario() -> None:
            async with client:
                await client.version()
                await client.models()
                await client.validate(["domain = 'x'"])

        asyncio.run(scenario())
        assert len(captured) == 3
        assert {request.headers["User-Agent"] for request in captured} == {client.user_agent}
        assert not any("python-httpx" in request.headers["User-Agent"] for request in captured)

    def test_app_info_goes_first(self, captured: list[httpx.Request]) -> None:
        app_info = AppInfo(name="acme-invoicer", version="1.4.0", details=("batch",))
        client = MthdsAPIClient(api_key="test-token", base_url=_BASE_URL, app_info=app_info)

        async def scenario() -> None:
            async with client:
                await client.version()

        asyncio.run(scenario())
        assert client.app_info == app_info
        assert captured[0].headers["User-Agent"].startswith(f"acme-invoicer/1.4.0 (batch) mthds-python/{__version__} python/")

    def test_overlong_app_info_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="limit"):
            MthdsAPIClient(api_key="test-token", base_url=_BASE_URL, app_info=AppInfo(name="a" * 600))

    def test_invalid_app_info_is_refused_before_the_client_exists(self) -> None:
        with pytest.raises(ValueError, match="RFC 9110 token"):
            MthdsAPIClient(api_key="test-token", base_url=_BASE_URL, app_info=AppInfo(name="bad name"))

    def test_subclass_seam_prepends_its_token_without_super_init(self, captured: list[httpx.Request]) -> None:
        client = _WrapperClient(api_key="test-token", base_url=_BASE_URL, app_info=AppInfo(name="acme-invoicer", version="1.4.0"))

        async def scenario() -> None:
            await client.version()
            await client.close()

        asyncio.run(scenario())
        user_agent = captured[0].headers["User-Agent"]
        assert user_agent == client.user_agent
        assert user_agent.startswith(f"acme-invoicer/1.4.0 pipelex-sdk-python/0.11.0 mthds-python/{__version__} python/")
