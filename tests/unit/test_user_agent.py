import re

import pytest
from pytest_mock import MockerFixture

from mthds.runners.api.user_agent import (
    MAX_USER_AGENT_LENGTH,
    AppInfo,
    build_user_agent,
    mthds_python_token,
    product_token,
    render_app_info,
    runtime_token,
)
from mthds.version import __version__

_RUNTIME_PATTERN = re.compile(r"python/\d+\.\d+\.\d+ \([a-z0-9_-]+; [A-Za-z0-9_.-]+\)")


class TestUserAgent:
    @pytest.mark.parametrize(
        ("topic", "app_info", "expected"),
        [
            ("name only", AppInfo(name="acme-invoicer"), "acme-invoicer"),
            ("name and version", AppInfo(name="acme-invoicer", version="1.4.0"), "acme-invoicer/1.4.0"),
            ("an rc version is a token", AppInfo(name="pipelex-app", version="0.2.16-rc.01"), "pipelex-app/0.2.16-rc.01"),
            ("url only", AppInfo(name="acme", url="https://acme.example"), "acme (+https://acme.example)"),
            (
                "details as the MCP workshop passes them",
                AppInfo(name="pipelex-mcp", version="0.17.0", details=("workshop", "host=claude-code/2.1.4")),
                "pipelex-mcp/0.17.0 (workshop; host=claude-code/2.1.4)",
            ),
            (
                "details come before the url",
                AppInfo(name="acme", version="1.0.0", details=("beta", "tier=pro"), url="https://acme.example/bot"),
                "acme/1.0.0 (beta; tier=pro; +https://acme.example/bot)",
            ),
        ],
    )
    def test_render_app_info(self, topic: str, app_info: AppInfo, expected: str) -> None:
        assert render_app_info(app_info) == expected, topic

    def test_details_accepts_a_list(self) -> None:
        """Pydantic coerces a list to the frozen tuple, so callers can pass either."""
        app_info = AppInfo.model_validate({"name": "acme", "details": ["one", "two=2"]})
        assert app_info.details == ("one", "two=2")

    @pytest.mark.parametrize(
        ("topic", "fields"),
        [
            ("empty name", {"name": ""}),
            ("space in name", {"name": "acme invoicer"}),
            ("slash in name", {"name": "acme/1.0"}),
            ("parenthesis in name", {"name": "acme(x)"}),
            ("non-ascii name", {"name": "acmé"}),
            ("empty version", {"name": "acme", "version": ""}),
            ("space in version", {"name": "acme", "version": "1.0 beta"}),
            ("slash in version", {"name": "acme", "version": "1/0"}),
            ("empty url", {"name": "acme", "url": ""}),
            ("space in url", {"name": "acme", "url": "https://acme.example/a b"}),
            ("parenthesis in url", {"name": "acme", "url": "https://acme.example/(x)"}),
            ("semicolon in url", {"name": "acme", "url": "https://acme.example/;x"}),
            ("empty detail", {"name": "acme", "details": [""]}),
            ("space in detail", {"name": "acme", "details": ["a b"]}),
            ("semicolon in detail", {"name": "acme", "details": ["a;b"]}),
            ("empty detail value", {"name": "acme", "details": ["host="]}),
            ("two slashes in detail value", {"name": "acme", "details": ["host=a/b/c"]}),
            ("unknown field", {"name": "acme", "homepage": "x"}),
        ],
    )
    def test_invalid_app_info_is_refused(self, topic: str, fields: dict[str, object]) -> None:
        with pytest.raises(ValueError):  # ruff: ignore[pytest-raises-too-broad] — pydantic's ValidationError is the spec's ValueError
            AppInfo.model_validate(fields)
        assert topic

    def test_app_info_is_frozen(self) -> None:
        app_info = AppInfo(name="acme")
        with pytest.raises(ValueError):  # ruff: ignore[pytest-raises-too-broad] — pydantic raises ValidationError (a ValueError) on a frozen assignment
            app_info.name = "other"  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("name", "version", "expected"),
        [
            ("mthds-python", "0.15.0", "mthds-python/0.15.0"),
            ("n8n-nodes-pipelex", None, "n8n-nodes-pipelex"),
        ],
    )
    def test_product_token(self, name: str, version: str | None, expected: str) -> None:
        assert product_token(name, version) == expected

    @pytest.mark.parametrize(("name", "version"), [("bad name", "1.0.0"), ("good", "1 0"), ("", None)])
    def test_product_token_refuses_non_tokens(self, name: str, version: str | None) -> None:
        with pytest.raises(ValueError, match="RFC 9110 token"):
            product_token(name, version)

    def test_mthds_python_token_uses_the_package_version(self) -> None:
        assert mthds_python_token() == f"mthds-python/{__version__}"

    def test_runtime_token_format(self) -> None:
        assert _RUNTIME_PATTERN.fullmatch(runtime_token()), runtime_token()

    def test_runtime_token_reads_the_platform(self, mocker: MockerFixture) -> None:
        mocker.patch("mthds.runners.api.user_agent.platform.system", return_value="Linux")
        mocker.patch("mthds.runners.api.user_agent.platform.machine", return_value="x86_64")
        assert runtime_token().endswith(" (linux; x86_64)")

    @pytest.mark.parametrize(
        ("system", "machine", "suffix"),
        [
            ("", "arm64", " (arm64)"),
            ("Darwin", "", " (darwin)"),
            ("", "", ""),
        ],
    )
    def test_runtime_token_omits_unknown_platform_parts(self, mocker: MockerFixture, system: str, machine: str, suffix: str) -> None:
        mocker.patch("mthds.runners.api.user_agent.platform.system", return_value=system)
        mocker.patch("mthds.runners.api.user_agent.platform.machine", return_value=machine)
        rendered = runtime_token()
        assert re.fullmatch(r"python/\d+\.\d+\.\d+", rendered.removesuffix(suffix)), rendered
        assert rendered.endswith(suffix)

    def test_build_user_agent_orders_app_then_sdks_then_runtime(self, mocker: MockerFixture) -> None:
        mocker.patch("mthds.runners.api.user_agent.runtime_token", return_value="python/3.12.4 (linux; x86_64)")
        user_agent = build_user_agent(
            AppInfo(name="acme-invoicer", version="1.4.0"),
            ("pipelex-sdk-python/0.11.0", "mthds-python/0.15.0"),
        )
        assert user_agent == "acme-invoicer/1.4.0 pipelex-sdk-python/0.11.0 mthds-python/0.15.0 python/3.12.4 (linux; x86_64)"

    def test_build_user_agent_without_app_info(self, mocker: MockerFixture) -> None:
        mocker.patch("mthds.runners.api.user_agent.runtime_token", return_value="python/3.12.4 (darwin; arm64)")
        assert build_user_agent(None, ("mthds-python/0.15.0",)) == "mthds-python/0.15.0 python/3.12.4 (darwin; arm64)"

    def test_build_user_agent_refuses_an_overlong_value(self) -> None:
        app_info = AppInfo(name="a" * MAX_USER_AGENT_LENGTH)
        with pytest.raises(ValueError, match="limit"):
            build_user_agent(app_info, (mthds_python_token(),))
