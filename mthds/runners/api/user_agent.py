"""Client identification — the `User-Agent` every `MthdsAPIClient` request carries.

Implements the workspace spec `docs/specs/client-identification.md`: the header is a
sequence of RFC 9110 product tokens, outermost first —

    [<app_info>] <sdk tokens...> python/<major.minor.micro> (<os>; <arch>)

`app_info` is the integrator's own name (Stripe's `appInfo`), the SDK tokens are the
libraries on the request's transport path (`mthds-python/<version>` for this package, with
a subclass such as `pipelex-sdk`'s `PipelexAPIClient` prepending its own), and the runtime
token closes the value. The header is self-declared and unauthenticated: it serves analytics
and diagnostics only, and must never carry a secret, a user identifier, an email or a hostname.
"""

from __future__ import annotations

import platform
import re
import sys
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, field_validator

from mthds.version import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence

#: This library's registered token name (the repo name, not the `mthds` dist name, which the npm twin shares).
MTHDS_PYTHON_TOKEN_NAME = "mthds-python"

#: The spec's ceiling on the whole header value.
MAX_USER_AGENT_LENGTH = 512

# RFC 9110 §5.6.2 `token = 1*tchar`.
_TCHAR_CLASS = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]"
_TOKEN_PATTERN = re.compile(rf"{_TCHAR_CLASS}+")
# A comment parameter: `token` or `token=value`, where `value = token / ( name "/" version )`.
_DETAIL_PATTERN = re.compile(rf"{_TCHAR_CLASS}+(={_TCHAR_CLASS}+(/{_TCHAR_CLASS}+)?)?")
# A URL rendered as `+url` inside a comment: visible ASCII (`!`..`~`) minus the comment's own delimiters
# `(`, `)`, `;` and `\`, so a non-ASCII or control character is refused here rather than failing at send time.
_URL_PATTERN = re.compile(r"[!-'*-:<-\[\]-~]+")


def _is_token(value: str) -> bool:
    return _TOKEN_PATTERN.fullmatch(value) is not None


class AppInfo(BaseModel):
    """The integrator's identity, placed in front of the SDK tokens (Stripe-style `appInfo`).

    Renders as `name/version (<details>; +url)`, dropping `/version` and the comment when
    they are empty. An empty `version` or `url` counts as absent (it is stored as None), and
    empty `details` render nothing. Every field is validated at construction: an invalid value raises
    `ValueError` (pydantic's `ValidationError` is a `ValueError`), and is never silently
    dropped or rewritten.

    Attributes:
        name: An RFC 9110 token, e.g. `acme-invoicer`.
        version: An optional token, e.g. `1.4.0`.
        url: An optional URL, rendered last in the comment as `+url`.
        details: Optional comment parameters, each `token` or `token=value`
            (`value` being a token or `name/version`), rendered before `+url`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str | None = None
    url: str | None = None
    details: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _is_token(value):
            msg = f"app_info.name must be an RFC 9110 token (tchar only, no spaces or '/'): {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str | None) -> str | None:
        if value == "":
            return None
        if value is not None and not _is_token(value):
            msg = f"app_info.version must be an RFC 9110 token (tchar only): {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        if value == "":
            return None
        if value is not None and _URL_PATTERN.fullmatch(value) is None:
            msg = f"app_info.url must be visible ASCII with no whitespace, '(', ')', ';' or '\\': {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for detail in value:
            if _DETAIL_PATTERN.fullmatch(detail) is None:
                msg = f"each app_info.details entry must be 'token' or 'token=value' (value a token or name/version): {detail!r}"
                raise ValueError(msg)
        return value


def product_token(name: str, version: str | None = None) -> str:
    """Render one product token, `name` or `name/version`.

    Args:
        name: The product name (an RFC 9110 token).
        version: The product version (a token), or None to omit it.

    Returns:
        The rendered product token.

    Raises:
        ValueError: If `name` or `version` is not a token.
    """
    if not _is_token(name):
        msg = f"product token name must be an RFC 9110 token: {name!r}"
        raise ValueError(msg)
    if version is None:
        return name
    if not _is_token(version):
        msg = f"product token version must be an RFC 9110 token: {version!r}"
        raise ValueError(msg)
    return f"{name}/{version}"


def render_app_info(app_info: AppInfo) -> str:
    """Render an `AppInfo` as `name/version (<details>; +url)`, dropping the empty parts."""
    rendered = product_token(app_info.name, app_info.version)
    params = list(app_info.details)
    if app_info.url is not None:
        params.append(f"+{app_info.url}")
    if params:
        rendered += f" ({'; '.join(params)})"
    return rendered


def mthds_python_token() -> str:
    """This library's own product token, `mthds-python/<package version>`."""
    return product_token(MTHDS_PYTHON_TOKEN_NAME, __version__)


def runtime_token() -> str:
    """The runtime token and its comment, `python/<major.minor.micro> (<os>; <arch>)`.

    `<os>` is `platform.system().lower()` and `<arch>` is `platform.machine()`; a part the
    platform cannot report is left out, and the comment with it when both are unknown.
    """
    version_info = sys.version_info
    rendered = f"python/{version_info.major}.{version_info.minor}.{version_info.micro}"
    platform_parts = [part for part in (platform.system().lower(), platform.machine()) if part]
    if platform_parts:
        rendered += f" ({'; '.join(platform_parts)})"
    return rendered


def build_user_agent(app_info: AppInfo | None, sdk_tokens: Sequence[str]) -> str:
    """Assemble the full `User-Agent` value: `[app_info] <sdk tokens...> <runtime>`.

    Args:
        app_info: The integrator's identity, or None.
        sdk_tokens: The SDK product tokens on the transport path, outermost first
            (e.g. `("pipelex-sdk-python/0.11.0", "mthds-python/0.15.0")`).

    Returns:
        The header value.

    Raises:
        ValueError: If the assembled value exceeds `MAX_USER_AGENT_LENGTH` characters.
    """
    parts: list[str] = []
    if app_info is not None:
        parts.append(render_app_info(app_info))
    parts.extend(sdk_tokens)
    parts.append(runtime_token())
    user_agent = " ".join(parts)
    if len(user_agent) > MAX_USER_AGENT_LENGTH:
        msg = f"User-Agent is {len(user_agent)} characters, over the {MAX_USER_AGENT_LENGTH}-character limit; shorten app_info"
        raise ValueError(msg)
    return user_agent
