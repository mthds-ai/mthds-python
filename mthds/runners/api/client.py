from __future__ import annotations

import asyncio
import math
import re
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, NamedTuple, NoReturn, Self, TypeVar, cast
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from pydantic import TypeAdapter, ValidationError
from pydantic_core import to_json
from typing_extensions import override

from mthds.config import load_config
from mthds.method_tree.digest import sha256_hex, tree_digest, tree_files_from_contents
from mthds.method_tree.exceptions import TreeSourceError
from mthds.method_tree.file_entry import FileEntry, HashFileEntry, encode_file_entry
from mthds.protocol.exceptions import PipelineRequestError, make_argument_invalid_error
from mthds.protocol.models import (
    BlobRef,
    MissingBlob,
    MissingBlobsRequest,
    MissingBlobsResult,
    ModelCategory,
    ModelDeck,
    RunResultStart,
    UploadTarget,
    ValidationResult,
    VersionInfo,
)
from mthds.protocol.problem.answers import RETRY_AFTER_HEADER, decode_json, parse_retry_after, unreadable_answer
from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.registry import CoreCode
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.exceptions import ApiResponseError, ApiTransportError, BlobUploadError, ClientNotConfiguredError, RunStillRunningError
from mthds.runners.api.models import DictPipeOutputAbstract, DictRunResultExecute
from mthds.runners.api.problem import answer_excerpt, answer_request_id, lower_case_headers, read_error_answer, transport_failure_problem
from mthds.runners.api.user_agent import AppInfo, build_user_agent, mthds_python_token
from mthds.runners.types import RunnerType

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from mthds.method_tree.file_entry import MethodFiles
    from mthds.method_tree.models import MethodTree, TreeFile
    from mthds.protocol.pipe_output import VariableMultiplicity
    from mthds.protocol.pipeline_inputs import PipelineInputs
    from mthds.protocol.problem.models import Problem
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract


DEFAULT_INLINE_TREE_MAX_BYTES: Final[int] = 256 * 1024
"""The largest size, in bytes, of a tree's inline `files` map that `prepare_files` sends without asking the runner first.

The size is what the request spends on the map: the map written as JSON with no whitespace, in
UTF-8, so a text entry counts with its escapes and a Base64 entry as its encoded text, about a
third more than the file's bytes. That is how the hosted Pipelex API counts its inline limit.

The protocol leaves the choice between an inline entry and a hash entry to the sender and names
no threshold, so this is this client's own policy. A tree this small travels whole in the request,
which spares the `version` handshake and the `missing_blobs` round trip; a larger one travels by
hash wherever the runner keeps a blob store, so a second run of an unchanged method uploads nothing.
It is the threshold the hosted Pipelex API asks its senders to use. A runner bounds the inline
entries of a request by its own limits, which a caller with a stricter runner passes as
`inline_max_bytes`.
"""

# How many uploads `prepare_files` runs at once.
_MAX_CONCURRENT_UPLOADS: Final[int] = 8


class MthdsAPIClient(MTHDSProtocol[DictPipeOutputAbstract]):
    """Client for any MTHDS runner — the MTHDS Protocol surface over HTTP.

    One base URL (`MTHDS_BASE_URL`); every endpoint is `<base>/v1/<endpoint>`. The
    protocol's required routes (`execute` / `start` / `validate` / `models` / `version`)
    work against any MTHDS-compliant runner, hosted or bare, each run or validation
    carrying the method as its whole method tree in `files`. The optional blob routes
    (`missing_blobs`, `upload_blob`) work against a runner whose `version()` declares
    `blob_store`, and `prepare_files` builds the `files` map from a listed tree, inline
    or by hash. The durable run lifecycle (polling a run to completion by id) is a
    hosted-API extension that lives in `pipelex-sdk` (`PipelexAPIClient`), not in this
    protocol base.

    Every failure of every route raises a `PipelineRequestError` carrying it as a problem
    document under a registered code (`exc.problem`): the runtime's own problem, or the one
    the client reads from an answer that is none, from a request that got no answer, or from
    an argument it refuses before sending (see `mthds.runners.api.exceptions`). The client
    never repeats a request by itself; a caller that does repeats only a failure whose
    `problem.is_retryable` is true.
    """

    # The client composes every endpoint from one origin (MTHDS_BASE_URL): `{base}/v1/{endpoint}`.
    # It targets the open-source pipelex-api runner (default http://localhost:8081/v1), but the
    # same paths are served by any MTHDS-Protocol server — the protocol surface is identical;
    # server-specific extensions (e.g. the hosted durable run lifecycle) are detectable via GET /version.
    # `_API_PREFIX` is the protocol surface identity (it tracks the protocol major version),
    # not per-call configuration — it stays a class constant; the timeout below is the default
    # for the overridable per-instance `request_timeout_seconds`.
    _API_PREFIX: ClassVar[str] = "v1"

    # TODO: restore differentiated timeouts — lightweight endpoints (`start`, `models`, `version`)
    # used to fail fast with a dedicated 30s poll timeout; they now inherit this 1200s default and
    # can hang for 20 minutes on an unresponsive server. Pass a short timeout explicitly for those
    # calls, or accept endpoint-category overrides in the constructor.
    _DEFAULT_REQUEST_TIMEOUT_SECONDS: ClassVar[float] = 1200.0  # runner blocking-execute ceiling

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        request_timeout_seconds: float | None = None,
        app_info: AppInfo | None = None,
    ):
        """Build a client from explicit arguments, falling back to `~/.mthds/config` / env.

        Args:
            api_key: Bearer token; defaults to `MTHDS_API_KEY`.
            base_url: Origin of the runner; defaults to `MTHDS_BASE_URL`.
            request_timeout_seconds: Per-request ceiling; defaults to the blocking-execute ceiling.
            app_info: The integrator's identity, placed in front of this library's token in
                the `User-Agent` (see `mthds.runners.api.user_agent`).

        Raises:
            ClientNotConfiguredError: If no API key or base URL can be resolved, the API key
                holds a character an HTTP header cannot carry, such as a line break or a space at
                its end, or `request_timeout_seconds` is no finite number of seconds, never
                negative (`client.not_configured`, naming the setting; the key is never quoted).
            ValueError: If the assembled `User-Agent` is over the length limit.
        """
        self.init_user_agent(app_info)
        config = load_config()

        resolved_api_key = api_key or config["api_key"]
        if not resolved_api_key:
            msg = "API key is required for API execution. Set MTHDS_API_KEY or run: mthds config set api-key <key>"
            raise ClientNotConfiguredError(msg, problem=make_client_problem(CoreCode.CLIENT_NOT_CONFIGURED, params={"setting": "api_key"}))
        if _SENDABLE_API_KEY.fullmatch(resolved_api_key) is None:
            # httpx would refuse the header at every request, which no repeat changes; the message never quotes the key.
            msg = "The API key holds a character an HTTP header cannot carry, such as a line break or a space at its end. Set it to the key alone."
            raise ClientNotConfiguredError(msg, problem=make_client_problem(CoreCode.CLIENT_NOT_CONFIGURED, params={"setting": "api_key"}))
        self.api_key = resolved_api_key

        resolved_base_url = base_url or config["base_url"]
        if not resolved_base_url:
            msg = "API base URL is required for API execution. Set MTHDS_BASE_URL or run: mthds config set base-url <url>"
            raise ClientNotConfiguredError(msg, problem=make_client_problem(CoreCode.CLIENT_NOT_CONFIGURED, params={"setting": "base_url"}))
        self.base_url = resolved_base_url.rstrip("/")

        # Presence semantics (`is not None`), not truthiness: an explicit `0.0` is honored as
        # the real per-request ceiling instead of silently falling back to the default —
        # the same-named parameter means the same thing in `pipelex-sdk`'s `PipelexAPIClient`.
        self.request_timeout_seconds = request_timeout_seconds if request_timeout_seconds is not None else self._DEFAULT_REQUEST_TIMEOUT_SECONDS

        self.client: httpx.AsyncClient | None = None

    @property
    def request_timeout_seconds(self) -> float:
        """The time limit of each request, in seconds: a finite number, never negative."""
        return self._request_timeout_seconds

    @request_timeout_seconds.setter
    def request_timeout_seconds(self, seconds: float) -> None:
        """Set the time limit of each request, refusing one that `client.timeout` could not state.

        Every assignment is checked, a subclass's own `__init__` included, so that a request that
        times out always reads as `client.timeout` naming its limit.

        Raises:
            ClientNotConfiguredError: If `seconds` is not a finite number, never negative, such as
                `-1`, `NaN`, an infinity, a boolean, a string or an integer past the range of a float
                (`client.not_configured`, naming `request_timeout_seconds`).
        """
        if not _states_seconds(seconds):
            msg = f"The request time limit must be a finite number of seconds, never negative; got {seconds!r}."
            raise ClientNotConfiguredError(
                msg, problem=make_client_problem(CoreCode.CLIENT_NOT_CONFIGURED, params={"setting": "request_timeout_seconds"})
            )
        self._request_timeout_seconds = seconds

    @property
    def runner_type(self) -> RunnerType:
        """The runner type (the API client IS the API runner — parity D8)."""
        return RunnerType.API

    # ── Client identification ──────────────────────────────────────────

    @classmethod
    def user_agent_sdk_tokens(cls) -> tuple[str, ...]:
        """The SDK product tokens this client puts in its `User-Agent`, outermost first.

        A subclass wrapping this transport prepends its own token and keeps the base's:
        `return (product_token("pipelex-sdk-python", __version__), *super().user_agent_sdk_tokens())`.
        """
        return (mthds_python_token(),)

    def init_user_agent(self, app_info: AppInfo | None) -> None:
        """Set `app_info` and the `User-Agent` value every request of this client carries.

        Called by `__init__`; a subclass whose own `__init__` does not call `super().__init__()`
        calls this instead, so the header is still built (and `app_info` checked) at construction.

        Raises:
            ValueError: If the assembled `User-Agent` is over the length limit.
        """
        self.app_info = app_info
        self.user_agent = build_user_agent(app_info, self.user_agent_sdk_tokens())

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start_client(self) -> MthdsAPIClient:
        """Initialize the HTTP client for API calls."""
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": self.user_agent})
        return self

    async def close(self) -> None:
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def __aenter__(self) -> Self:
        self.start_client()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # ── URL resolution ─────────────────────────────────────────────────

    def _url(self, endpoint: str) -> str:
        """Build an API URL: `<base>/v1/<endpoint>`."""
        return f"{self.base_url}/{self._API_PREFIX}/{endpoint}"

    # ── Transport ──────────────────────────────────────────────────────

    async def _send(self, method: str, url: str, *, content: bytes | None, request_timeout: float) -> httpx.Response:
        """Issue one HTTP request and return the raw response (status interpretation is the caller's).

        The body is read whole before returning, so an answer whose body cannot be read, such as one
        whose content encoding cannot be decoded (a broken gzip stream), raises rather than returns.

        Args:
            method: HTTP method ("GET" or "POST").
            url: Fully-resolved absolute URL.
            content: JSON-encoded request body, or None for a bodyless request.
            request_timeout: Per-request timeout in seconds.

        Returns:
            The httpx.Response, without status-code interpretation.

        Raises:
            httpx.TransportError: If no answer came back; `_request` reads it as a problem.
            httpx.DecodingError: If the answer's body cannot be decoded, which is no usable answer either;
                `_request` reads it as a problem too.
        """
        if not self.client:
            self.start_client()
            assert self.client is not None

        # `User-Agent` is set per request too, so a subclass overriding `start_client` cannot drop it.
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if content is not None:
            headers["Content-Type"] = "application/json"
        return await self.client.request(method, url, content=content, headers=headers, timeout=request_timeout)

    async def _request(self, method: str, endpoint: str, *, content: bytes | None, creates_run: bool) -> httpx.Response:
        """Send one request through `_send`, reading a request that got no answer as a problem.

        Every route sends through this, so a request that got no answer raises an
        `ApiTransportError` on every route: `client.unreachable` when nothing left,
        `client.timeout` when a call that creates nothing got no answer in time, and
        `client.outcome_unknown` when a request that creates a run left and no answer came
        back. An answer whose body cannot be read, such as one whose content encoding cannot be
        decoded, is no usable answer either, and the request had left: it reads as a connection
        lost, `client.unreachable`, or `client.outcome_unknown` on a route that creates a run, as
        the TypeScript client reads it. A documented protected extension seam: a client built on
        this one sends its own routes through it too.

        Args:
            method: HTTP method ("GET" or "POST").
            endpoint: The endpoint below the protocol prefix, query included (`execute`, `models?type=llm`).
            content: JSON-encoded request body, or None for a bodyless request.
            creates_run: Whether the request may create a run, as `POST /execute` and `POST /start` do.

        Returns:
            The answer, whatever its status.

        Raises:
            ApiTransportError: If no answer came back, or its body cannot be read.
            ClientNotConfiguredError: If the base URL does not make a valid URL, or names no scheme the
                client sends to, `http` or `https` (`client.not_configured`).
        """
        url = self._url(endpoint)
        try:
            return await self._send(method, url, content=content, request_timeout=self.request_timeout_seconds)
        except httpx.UnsupportedProtocol as exc:
            # A transport error by its class, but a setting by its cause: the base URL names no scheme the
            # client sends to, so no repeat can succeed, and it must not read as an unreachable runtime.
            msg = f"API base URL '{self.base_url}' does not start with http:// or https://: {exc}"
            raise ClientNotConfiguredError(msg, problem=make_client_problem(CoreCode.CLIENT_NOT_CONFIGURED, params={"setting": "base_url"})) from exc
        except (httpx.TransportError, httpx.DecodingError) as exc:
            # `httpx.DecodingError` is no `httpx.TransportError`, so it is named beside it.
            problem = transport_failure_problem(exc, creates_run=creates_run, base_url=self.base_url, timeout_seconds=self.request_timeout_seconds)
            msg = f"API {method} /{self._API_PREFIX}/{endpoint} failed: {problem.detail}"
            raise ApiTransportError(msg, problem=problem, api_url=self.base_url, request_url=url) from exc
        except httpx.InvalidURL as exc:
            msg = f"API base URL '{self.base_url}' does not make a valid URL: {exc}"
            raise ClientNotConfiguredError(msg, problem=make_client_problem(CoreCode.CLIENT_NOT_CONFIGURED, params={"setting": "base_url"})) from exc

    def _parse_answer(
        self,
        *,
        method: str,
        endpoint: str,
        response: httpx.Response,
        creates_run: bool,
        parse: Callable[[Any], AnswerT],
    ) -> AnswerT:
        """Parse a route's success answer, raising an `ApiResponseError` for any other.

        A non-2xx raises through `_raise_api_response_error` with the problem the answer reads
        as, and a success whose body is not JSON, or does not validate as the route's answer,
        raises it with `client.response_unreadable`, except on a route that creates a run: there
        the runtime said it accepted the request, so the run may exist, and the answer reads as
        `client.outcome_unknown`, naming the run when the body gives its `pipeline_run_id` as a
        non-empty string, in the problem's parameters and as its member. A success body is decoded by the rules every
        body is (`mthds.protocol.problem.answers.decode_json`): `NaN`, `Infinity` and a number past
        the range of a double are not JSON. Its numbers are kept as written, so that a pipe output's
        `10.0` stays a float. A documented protected extension seam: a client built on this one
        parses its own routes' answers through it too.

        Args:
            method: The HTTP method of the request, for the message.
            endpoint: The endpoint below the protocol prefix, query included.
            response: The runner's answer.
            creates_run: Whether the request may have created a run.
            parse: Validates the decoded JSON body into the route's answer, raising
                `pydantic.ValidationError` when it does not fit.

        Returns:
            The route's answer.

        Raises:
            ApiResponseError: If the answer is a non-2xx, or a success the client cannot read.
        """
        if not response.is_success:
            reading = read_error_answer(response, creates_run=creates_run)
            self._raise_api_response_error(
                method=method, endpoint=endpoint, response=response, problem=reading.problem, problem_from_body=reading.from_body
            )
        decoded = decode_json(response.text, numbers_as_written=True)
        if not decoded.is_json:
            self._raise_unreadable_success(method=method, endpoint=endpoint, response=response, creates_run=creates_run, body=None)
        try:
            return parse(decoded.value)
        except ValidationError:
            self._raise_unreadable_success(method=method, endpoint=endpoint, response=response, creates_run=creates_run, body=decoded.value)

    def _raise_unreadable_success(self, *, method: str, endpoint: str, response: httpx.Response, creates_run: bool, body: object) -> NoReturn:
        """Raise the `ApiResponseError` of a success whose body is not the route's answer.

        On a route that creates nothing it is `client.response_unreadable`. On a route that creates a
        run the runtime said it accepted the request, so the run may exist: `client.outcome_unknown`,
        naming the run when the body gives its id.

        Args:
            method: The HTTP method of the request, for the message.
            endpoint: The endpoint below the protocol prefix, query included.
            response: The runner's answer.
            creates_run: Whether the request may have created a run.
            body: The decoded body, `None` when it is not JSON or names no run the client can read.
        """
        problem = _outcome_unknown(started_run_id=_started_run_id(body)) if creates_run else unreadable_answer(response.status_code)
        self._raise_api_response_error(method=method, endpoint=endpoint, response=response, problem=problem, problem_from_body=False)

    # ── Protocol surface ─────────────────────────────────────────────────

    @override
    async def execute(
        self,
        pipe_code: str | None = None,
        files: MethodFiles | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DictRunResultExecute:
        """Execute a method synchronously and wait for its completion — `POST /v1/execute`.

        Args:
            pipe_code: The code identifying the pipe to execute: a pipe the runner
                already holds, or one declared in a bundle of `files`. Without it, the
                run starts at the method's `main_pipe`.
            files: The method to load, as its whole method tree: a map from tree path
                to file entry, holding at least one file. `prepare_files` builds it
                from a listed tree.
            inputs: Inputs passed to the method
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref
            extra: Server-specific extension args, merged into the request body
                as top-level properties — the server you call defines and handles
                them; this SDK only passes them through. Protocol args must be
                passed as named parameters, not through `extra` (raises
                `PipelineRequestError`).

        Returns:
            Complete execution results including run state and output

        Raises:
            PipelineRequestError: If nothing to run was named, if `files` holds no file,
                or if `extra` carries a protocol arg (`client.argument_invalid`).
            RunStillRunningError: If the server answers 202 (the protocol's optional
                async degrade) — the run continues server-side; resume by `run_id`
                (`client.follow_failed`). A 202 naming no run raises `ApiResponseError`
                carrying `client.outcome_unknown`, since the run may exist.
            ApiResponseError: If the server answers non-2xx — a refusal to run an invalid
                method (`method.invalid`, its faults on `problem.errors`), a hash entry the
                runner does not hold (`request.blobs_missing`, naming each in
                `problem.params.missing_blobs`), a failed run, auth, or a server fault — or a
                success the client cannot read, which leaves the outcome unknown
                (`client.outcome_unknown`, naming the run when the body does).
            ApiTransportError: If no answer came back; a request that left reads as
                `client.outcome_unknown`, since the run may exist.
        """
        _assert_run_sources(pipe_code=pipe_code, files=files, extra=extra, route="execute")

        body = _build_run_body(
            pipe_code=pipe_code,
            files=files,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
            extra=extra,
            exclude_none=True,
        )
        content = to_json(body)
        response = await self._request("POST", "execute", content=content, creates_run=True)
        self._raise_if_execute_degraded(response)
        return self._parse_answer(method="POST", endpoint="execute", response=response, creates_run=True, parse=DictRunResultExecute.model_validate)

    @override
    async def start(
        self,
        pipe_code: str | None = None,
        files: MethodFiles | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunResultStart:
        """Start a method asynchronously — `POST /v1/start` (202: `pipeline_run_id` only).

        Args:
            pipe_code: The code identifying the pipe to execute: a pipe the runner
                already holds, or one declared in a bundle of `files`. Without it, the
                run starts at the method's `main_pipe`.
            files: The method to load, as its whole method tree: a map from tree path
                to file entry, holding at least one file. `prepare_files` builds it
                from a listed tree.
            inputs: Inputs passed to the method
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref
            extra: Server-specific extension args, merged into the request body
                as top-level properties — the server you call defines and handles
                them; this SDK only passes them through. Protocol args must be
                passed as named parameters, not through `extra` (raises
                `PipelineRequestError`).

        Returns:
            RunResultStart — the authoritative server-generated `pipeline_run_id`
            (no output yet). On a hosted deployment the id is durable — poll the
            durable run lifecycle (a hosted extension, exposed by `pipelex-sdk`).

        Raises:
            PipelineRequestError: If nothing to run was named, if `files` holds no file,
                or if `extra` carries a protocol arg (`client.argument_invalid`).
            ApiResponseError: If the server answers non-2xx — a refusal to run an invalid
                method (`method.invalid`, its faults on `problem.errors`), a hash entry the
                runner does not hold (`request.blobs_missing`, naming each in
                `problem.params.missing_blobs`), auth, or a server fault — or a success the
                client cannot read, an empty `pipeline_run_id` included, which leaves the
                outcome unknown (`client.outcome_unknown`, naming the run when the body
                names one the client can read).
            ApiTransportError: If no answer came back; a request that left reads as
                `client.outcome_unknown`, since the run may exist.
        """
        _assert_run_sources(pipe_code=pipe_code, files=files, extra=extra, route="start")

        body = _build_run_body(
            pipe_code=pipe_code,
            files=files,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
            extra=extra,
            exclude_none=True,
        )
        content = to_json(body)
        response = await self._request("POST", "start", content=content, creates_run=True)
        started = self._parse_answer(method="POST", endpoint="start", response=response, creates_run=True, parse=RunResultStart.model_validate)
        if _usable_run_id(started.pipeline_run_id) is None:
            # The answer has the route's shape but names no run the client can read, such as an empty id:
            # the runtime accepted the request, so the run may exist, as after a 202 on execute naming none.
            self._raise_unreadable_success(method="POST", endpoint="start", response=response, creates_run=True, body=None)
        return started

    async def _post_validate(self, files: MethodFiles, allow_signatures: bool, extra: dict[str, Any] | None) -> httpx.Response:
        """POST a `/validate` request and return the raw 200-diagnostic response.

        The shared transport + body-building seam for `validate`: builds the request body
        (the protocol's basic args plus the generic `extra` extension passthrough, guarded
        against a smuggled protocol arg), sends it, and raises `ApiResponseError` on a
        no-verdict non-2xx. The 200 body — a produced verdict discriminated on `is_valid` —
        is left for the caller to parse into its own verdict union through `_parse_answer`
        (the protocol-neutral `ValidationResult` here; the `pipelex-sdk` subclass narrows it to
        its Pipelex-branded report types). A documented protected extension seam, alongside
        `_send` / `_request` / `_parse_answer` / `_url` / `_build_run_body`.

        Raises:
            PipelineRequestError: if `files` holds no file, or if `extra` carries a protocol
                arg (`files` or `allow_signatures`) — pass it as a named parameter instead
                (`client.argument_invalid`).
            ApiResponseError: a no-verdict response (request-shape 422, 401/403, or 5xx).
            ApiTransportError: if no answer came back.
        """
        _refuse_empty_files(files)
        # A plain dict, since `to_json` serializes no other mapping, a `MappingProxyType` or a `UserDict` among them.
        body: dict[str, Any] = {"files": dict(files), "allow_signatures": allow_signatures}
        body.update(_build_extensions(extra, protocol_args=_VALIDATE_REQUEST_ARGS))
        content = to_json(body)
        response = await self._request("POST", "validate", content=content, creates_run=False)
        if not response.is_success:
            reading = read_error_answer(response, creates_run=False)
            self._raise_api_response_error(
                method="POST", endpoint="validate", response=response, problem=reading.problem, problem_from_body=reading.from_body
            )
        return response

    @override
    async def validate(
        self,
        files: MethodFiles,
        allow_signatures: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Parse, validate, and dry-run a method — `POST /v1/validate`.

        The runner judges the whole tree: every bundle, and every file a bundle names by
        file reference or by a `PipeFunc`'s import path.

        `/validate` is 200-diagnostic: a produced verdict — valid or invalid — rides a
        200 body discriminated on `is_valid`. A non-2xx response means no verdict could
        be produced (request shape, auth, server fault) and surfaces as an
        `ApiResponseError`; an invalid bundle does NOT raise.

        Args:
            files: The method to validate, as its whole method tree: a map from tree
                path to file entry, holding at least one file. `prepare_files` builds
                it from a listed tree.
            allow_signatures: Tolerate unimplemented pipe signatures (strict by default)
            extra: Server-specific extension args, merged into the request body
                as top-level properties — the server you call defines and handles
                them; this SDK only passes them through. For example, a server may
                accept `extra={"render": ["markdown"]}` to render the verdict as a
                view beside it. Protocol args (`files`, `allow_signatures`) must be
                passed as named parameters, not through `extra` (raises
                `PipelineRequestError`).

        Returns:
            The protocol-neutral 200-diagnostic union (`ValidationResult`): a
            `ValidationReport` (`is_valid: true`) or an `InvalidValidationReport`
            (`is_valid: false`, with its faults in `errors`). Both arms carry the advisory
            `warnings`, and every fault and warning is a `ProblemItem`.
            Implementation-specific artifacts (e.g. pipelex's structural artifacts,
            `rendered_markdown`) ride `model_extra`; the `pipelex-sdk` subclass narrows
            this to its typed `PipelexValidationReport` / `PipelexInvalidReport`.

        Raises:
            PipelineRequestError: if `files` holds no file, or if `extra` carries a
                protocol arg (`files` or `allow_signatures`) — pass it as a named
                parameter instead (`client.argument_invalid`).
            ApiResponseError: a no-verdict response (request-shape 422, 401/403,
                or 5xx) — never an invalid bundle, which is a 200 `InvalidValidationReport` —
                or a malformed 200 body, missing or non-boolean `is_valid` or a tagged arm
                missing a required field, which reads as `client.response_unreadable`
                rather than being mistaken for a verdict.
            ApiTransportError: if no answer came back.
        """
        response = await self._post_validate(files, allow_signatures, extra)
        return self._parse_answer(
            method="POST", endpoint="validate", response=response, creates_run=False, parse=_VALIDATION_RESULT_ADAPTER.validate_python
        )

    @override
    async def models(self, category: ModelCategory | None = None) -> ModelDeck:
        """The model deck the runner can route to — `GET /v1/models[?type=]`.

        Args:
            category: Optional filter (`llm`, `extract`, `img_gen`, `search`,
                `judgment`). A runner of an earlier protocol version answers a
                category it does not define with a `422`.

        Returns:
            ModelDeck with the models this runner can route to (base fields
            + any implementation extensions). An entry whose category this
            package does not recognize is kept with its raw `type` string
            rather than failing the call.

        Raises:
            ApiResponseError: If the server answers non-2xx, or a success the client cannot read.
            ApiTransportError: If no answer came back.
        """
        endpoint = f"models?type={quote(category, safe='')}" if category is not None else "models"
        response = await self._request("GET", endpoint, content=None, creates_run=False)
        return self._parse_answer(method="GET", endpoint=endpoint, response=response, creates_run=False, parse=ModelDeck.model_validate)

    @override
    async def version(self) -> VersionInfo:
        """Protocol + runner versions — `GET /v1/version` (public).

        Returns:
            VersionInfo — the handshake for feature detection (hosted extensions or not).

        Raises:
            ApiResponseError: If the server answers non-2xx, or a success the client cannot read.
            ApiTransportError: If no answer came back.
        """
        response = await self._request("GET", "version", content=None, creates_run=False)
        return self._parse_answer(method="GET", endpoint="version", response=response, creates_run=False, parse=VersionInfo.model_validate)

    # ── Sending files by hash (the optional blob routes) ─────────────────

    async def missing_blobs(self, blobs: Sequence[BlobRef], digest: str | None = None) -> MissingBlobsResult:
        """Which of these blobs the runner lacks, and where to upload each — `POST /v1/blobs/missing`.

        An optional route, served by a runner whose `version()` declares `blob_store`. The request is
        sent as given: list each hash once, as the protocol asks.

        Args:
            blobs: The blobs about to be sent by hash, each named by its SHA-256 and its size.
            digest: The tree digest of the method tree the blobs make up, so a runner that holds
                that tree in full may answer with an empty list at once; None to leave it out.

        Returns:
            MissingBlobsResult — every blob of the request the runner does not hold, each with its
            upload target; an empty `missing` means there is nothing to upload.

        Raises:
            ApiResponseError: If the runner answers non-2xx — a hash listed twice with different
                sizes, a blob past the runner's limits, a runner that serves no blob routes, auth,
                or a server fault — or a success the client cannot read (`client.response_unreadable`).
            ApiTransportError: If no answer came back.
        """
        request = MissingBlobsRequest(blobs=list(blobs), digest=digest)
        content = request.model_dump_json(exclude_none=True).encode("utf-8")
        response = await self._request("POST", "blobs/missing", content=content, creates_run=False)
        return self._parse_answer(
            method="POST", endpoint="blobs/missing", response=response, creates_run=False, parse=MissingBlobsResult.model_validate
        )

    async def upload_blob(self, blob: MissingBlob, data: bytes) -> None:
        """Upload one blob's bytes to the target `missing_blobs` named for it.

        The bytes are the whole body of a request with the target's method to its URL, carrying
        exactly the target's headers and nothing of this client's: the target may be another server
        than the runner, such as an object store behind a presigned URL, so neither the API key nor
        the `User-Agent` goes with it. A `412` from a target whose headers ask for a create-only
        write (`If-None-Match`) means the bytes are already stored, and counts as uploaded.

        Args:
            blob: A blob of a `missing_blobs` answer, with its upload target.
            data: The blob's bytes.

        Raises:
            PipelineRequestError: If `data` is not the blob named: another SHA-256 or another size
                (`client.argument_invalid`).
            BlobUploadError: If the target answers non-2xx, other than a create-only target's `412`,
                carrying the problem its answer reads as.
        """
        data_sha256 = await asyncio.to_thread(sha256_hex, data)
        if len(data) != blob.size or data_sha256 != blob.sha256:
            msg = f"The bytes given for blob {blob.sha256} are not that blob: they hash to {data_sha256} and hold {len(data)} bytes, not {blob.size}."
            raise make_argument_invalid_error(msg, argument="data", reason="not_the_blob")
        async with self._make_upload_client() as upload_client:
            await self._upload_blob_with(upload_client=upload_client, blob=blob, data=data)

    async def prepare_files(self, tree: MethodTree, *, inline_max_bytes: int = DEFAULT_INLINE_TREE_MAX_BYTES) -> dict[str, FileEntry]:
        """The `files` map that sends a tree listed from a directory: inline, or by hash once the runner holds every blob.

        A tree whose inline map is at most `inline_max_bytes` travels inline whole, with no round
        trip; the map is measured as the request spends it, written as JSON with no whitespace, in
        UTF-8, so a Base64 entry counts as its encoded text. A larger tree travels inline too when
        the runner keeps no blob store, as `version()` reports; otherwise `missing_blobs` is asked
        which blobs the runner lacks, naming the tree's digest, each missing blob is uploaded once,
        and every file travels by hash. Each file is read from disk, off the event loop, and checked
        against the hash the listing recorded, so what travels is the tree the digest names.

        Args:
            tree: A tree listed from a directory, as `list_method_tree` returns it.
            inline_max_bytes: The largest size, in bytes, of an inline map sent without asking the
                runner whether it keeps a blob store.

        Returns:
            The map of file entries, keyed by tree path in tree path order, ready for `files`.

        Raises:
            PipelineRequestError: If the tree was not listed from a directory or holds no file
                (`client.argument_invalid`), or the runner asks for a blob the tree does not hold
                (`client.response_unreadable`).
            TreeSourceError: If a file cannot be read, or changed after the tree was listed.
            ApiResponseError: If the runner answers `version` or `missing_blobs` with a failure.
            ApiTransportError: If `version` or `missing_blobs` got no answer.
            BlobUploadError: If an upload target answers non-2xx.
        """
        if tree.directory is None:
            msg = "This tree was not listed from a directory, so its files cannot be read from disk: send its bytes with prepare_files_from_contents."
            raise make_argument_invalid_error(msg, argument="tree", reason="not_listed_from_a_directory")
        return await self._prepare_files(
            tree_files=tree.files,
            digest=tree.digest,
            read=lambda tree_file: _read_listed_file(tree, tree_file=tree_file),
            inline_max_bytes=inline_max_bytes,
            argument="tree",
        )

    async def prepare_files_from_contents(
        self, contents: Mapping[str, bytes], *, inline_max_bytes: int = DEFAULT_INLINE_TREE_MAX_BYTES
    ) -> dict[str, FileEntry]:
        """The `files` map that sends a tree whose bytes are at hand, keyed by tree path, by the rule of `prepare_files`.

        Args:
            contents: Each file's bytes, by tree path. The keys are sent as they are, and the runner
                refuses one that is not a tree path.
            inline_max_bytes: The largest size, in bytes, of an inline map sent without asking the
                runner whether it keeps a blob store.

        Returns:
            The map of file entries, keyed by tree path in tree path order, ready for `files`.

        Raises:
            PipelineRequestError: If `contents` holds no file (`client.argument_invalid`), or the
                runner asks for a blob the tree does not hold (`client.response_unreadable`).
            ApiResponseError: If the runner answers `version` or `missing_blobs` with a failure.
            ApiTransportError: If `version` or `missing_blobs` got no answer.
            BlobUploadError: If an upload target answers non-2xx.
        """
        tree_files = await asyncio.to_thread(tree_files_from_contents, contents)
        return await self._prepare_files(
            tree_files=tree_files,
            digest=tree_digest(tree_files),
            read=lambda tree_file: contents[tree_file.path],
            inline_max_bytes=inline_max_bytes,
            argument="contents",
        )

    async def _prepare_files(
        self, *, tree_files: list[TreeFile], digest: str, read: Callable[[TreeFile], bytes], inline_max_bytes: int, argument: str
    ) -> dict[str, FileEntry]:
        """Choose inline or hash entries for a tree's files, uploading what the runner lacks before naming anything by hash.

        `read` returns a file's bytes already checked against its listing, so they are not hashed again
        here. Reading, hashing and encoding run off the event loop. `argument` names the caller's
        argument the tree came from, for the refusal of a tree that holds no file.
        """
        if not tree_files:
            msg = "The tree holds no file, and a method tree holds at least one."
            raise make_argument_invalid_error(msg, argument=argument, reason="empty")
        inline_tree: _InlineTree | None = None
        # An inline map is never smaller than the bytes it carries, since escapes and Base64 only add,
        # so a tree whose bytes alone pass the threshold is not read in full just to be measured.
        if sum(tree_file.size for tree_file in tree_files) <= inline_max_bytes:
            inline_tree = await asyncio.to_thread(_encode_inline, tree_files=tree_files, read=read)
            if inline_tree.encoded_size <= inline_max_bytes:
                return inline_tree.files
        version_info = await self.version()
        if not version_info.blob_store:
            if inline_tree is None:
                inline_tree = await asyncio.to_thread(_encode_inline, tree_files=tree_files, read=read)
            return inline_tree.files
        # One blob per distinct hash: two files with the same bytes are one blob, listed and uploaded once.
        file_of_blob: dict[str, TreeFile] = {}
        for tree_file in tree_files:
            file_of_blob.setdefault(tree_file.sha256, tree_file)
        blobs = [BlobRef(sha256=tree_file.sha256, size=tree_file.size) for tree_file in file_of_blob.values()]
        answer = await self.missing_blobs(blobs, digest=digest)
        # Bytes already read to be measured are uploaded from memory rather than read a second time.
        upload_read = read if inline_tree is None else inline_tree.held_bytes
        await self._upload_missing(answer.missing, file_of_blob=file_of_blob, read=upload_read)
        return {tree_file.path: HashFileEntry(sha256=tree_file.sha256, size=tree_file.size) for tree_file in tree_files}

    async def _upload_missing(self, missing: list[MissingBlob], *, file_of_blob: dict[str, TreeFile], read: Callable[[TreeFile], bytes]) -> None:
        """Upload every missing blob, a bounded number at a time, reading each one's bytes only when its turn comes.

        Every upload runs to its end before the first failure is raised, so no upload is left
        running against a closed connection; a blob uploaded beside a failed one is stored, which
        is harmless since a blob is named by its bytes. A blob is named by its hash and its size, so
        one the tree holds under the same hash at another size is a blob the tree does not hold.
        An answer naming such a blob is not the route's answer, which lists only blobs of the
        request, so it reads as `client.response_unreadable`, naming the route's `200`.
        """
        unknown: set[str] = set()
        for blob in missing:
            tree_file = file_of_blob.get(blob.sha256)
            if tree_file is None or tree_file.size != blob.size:
                unknown.add(blob.sha256)
        if unknown:
            msg = f"The runner asked for blobs this tree does not hold: {', '.join(sorted(unknown))}."
            raise PipelineRequestError(msg, problem=unreadable_answer(_MISSING_BLOBS_SUCCESS_STATUS))
        if not missing:
            return
        slots = asyncio.Semaphore(_MAX_CONCURRENT_UPLOADS)
        async with self._make_upload_client() as upload_client:

            async def upload_one(blob: MissingBlob) -> None:
                async with slots:
                    data = await asyncio.to_thread(read, file_of_blob[blob.sha256])
                    await self._upload_blob_with(upload_client=upload_client, blob=blob, data=data)

            outcomes = await asyncio.gather(*(upload_one(blob) for blob in missing), return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                raise outcome

    def _make_upload_client(self) -> httpx.AsyncClient:
        """The HTTP client blob uploads go through, apart from the API client: no default header, no auth, no event hook."""
        return httpx.AsyncClient()

    async def _upload_blob_with(self, *, upload_client: httpx.AsyncClient, blob: MissingBlob, data: bytes) -> None:
        """Upload one blob's bytes, already checked to be that blob, through `upload_client` with exactly its target's headers; see `upload_blob`."""
        target = blob.upload
        # A request built outside the client carries exactly the target's headers (httpx adds only
        # `Host` and `Content-Length`), where `client.request` would merge the client's defaults in.
        request = httpx.Request(
            target.method,
            target.url,
            content=data,
            headers=target.headers,
            extensions={"timeout": httpx.Timeout(self.request_timeout_seconds).as_dict()},
        )
        response = await upload_client.send(request)
        if response.is_success or (response.status_code == 412 and _is_create_only(target)):
            return
        upload_url = _url_without_query(target.url)
        # The target's answer reads as any failed answer does: its own problem document when it is one,
        # such as a runner's `PUT /blobs/{sha256}` refusal, else the problem its status names.
        reading = read_error_answer(response, creates_run=False)
        msg = f"Uploading blob {blob.sha256} to {upload_url} failed ({response.status_code}): {reading.problem.detail}"
        excerpt = answer_excerpt(response, problem_from_body=reading.from_body)
        if excerpt is not None:
            msg = f"{msg}\nThe server answered: {excerpt}"
        raise BlobUploadError(
            msg,
            problem=reading.problem,
            sha256=blob.sha256,
            status=response.status_code,
            status_text=response.reason_phrase,
            response_body=response.text,
            upload_url=upload_url,
        )

    def _raise_api_response_error(
        self, *, method: str, endpoint: str, response: httpx.Response, problem: Problem, problem_from_body: bool
    ) -> NoReturn:
        """Raise the `ApiResponseError` of an answer that is a failure, carrying the problem it reads as.

        Every route calls this for a non-2xx answer and for a success it cannot read, so it is the one
        place an answer becomes an error. When the body is not the problem the error carries, the
        message quotes its start on its own line (`mthds.runners.api.problem.answer_excerpt`), so that
        a person sees what the server said while the problem keeps the registry's words. A documented
        protected extension seam: a client built on this one overrides it to raise its own subclass of
        `ApiResponseError`, and every inherited route then raises that subclass.

        Args:
            method: The HTTP method of the request, for the message (`POST`).
            endpoint: The endpoint below the protocol prefix, query included, exactly as the route sent it
                (`execute`, `models?type=llm`): it names the request in the message and gives `request_url`.
            response: The runner's answer.
            problem: The problem the answer reads as (`mthds.runners.api.problem.read_error_answer`
                for a non-2xx, `mthds.protocol.problem.answers.unreadable_answer` for a success it cannot read).
            problem_from_body: Whether `problem` is the body's own problem document, as the reading of the
                answer says; when it is not, the message quotes the body.

        Raises:
            ApiResponseError: Always.
        """
        msg = f"API {method} /{self._API_PREFIX}/{endpoint} failed ({response.status_code}): {problem.detail}"
        excerpt = answer_excerpt(response, problem_from_body=problem_from_body)
        if excerpt is not None:
            msg = f"{msg}\nThe server answered: {excerpt}"
        raise ApiResponseError(
            msg,
            problem=problem,
            api_url=self.base_url,
            status=response.status_code,
            status_text=response.reason_phrase,
            response_body=response.text,
            headers=lower_case_headers(response.headers),
            request_url=self._url(endpoint),
            request_id=answer_request_id(response, problem=problem),
        )

    def _raise_if_execute_degraded(self, response: httpx.Response) -> None:
        """Map the protocol's optional 202 execute degrade to a typed error.

        Hosted does not emit 202 today, but the protocol permits it. The run has started and this
        client does not follow it, so the answer reads as `client.follow_failed` naming the run, with
        the `Location` and `Retry-After` hints on the error. A 202 that names no run still says the
        runtime accepted the request, so the run may exist under an id the client never learned: it
        reads as `client.outcome_unknown`, which no caller repeats automatically.

        Raises:
            RunStillRunningError: If the answer is a 202 naming its run.
            ApiResponseError: If the answer is a 202 naming no run (`client.outcome_unknown`).
        """
        if response.status_code != 202:
            return
        started_run_id = _started_run_id(decode_json(response.text).value)
        if started_run_id is None:
            self._raise_api_response_error(
                method="POST", endpoint="execute", response=response, problem=_outcome_unknown(started_run_id=None), problem_from_body=False
            )
        problem = make_client_problem(CoreCode.CLIENT_FOLLOW_FAILED, params={"pipeline_run_id": started_run_id}, pipeline_run_id=started_run_id)
        msg = (
            f"execute() was accepted asynchronously (202): run {started_run_id} is still running server-side. "
            "Poll its results (hosted) or use start()."
        )
        raise RunStillRunningError(
            msg,
            problem=problem,
            run_id=started_run_id,
            retry_after_seconds=parse_retry_after(response.headers.get(RETRY_AFTER_HEADER)),
            location=response.headers.get("location"),
        )


# ── Module helpers ──────────────────────────────────────────────────────


def _states_seconds(value: object) -> bool:
    """Whether `value` is a time limit `client.timeout` can state: an int or a float, never a boolean, finite and never negative."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:  # an int too large for a float
        return False


# An API key HTTP can carry in the `Authorization` header as written: visible ASCII characters only, so no
# whitespace at either end, no line break and nothing past ASCII, which httpx refuses to write.
_SENDABLE_API_KEY = re.compile(r"[!-~]+")

# The protocol's basic request args — the named parameters of execute()/start().
# Anything else a caller passes is an extension arg: it rides `extra` and merges
# into the body as a top-level property. A protocol arg smuggled through `extra`
# is rejected (it must be passed as a named parameter).
_PROTOCOL_REQUEST_ARGS: frozenset[str] = frozenset(
    {"pipe_code", "files", "inputs", "output_name", "output_multiplicity", "dynamic_output_concept_ref"}
)

# The protocol's `/validate` request args — the named parameters of validate().
# Same guard as execute()/start(): a validate protocol arg smuggled through
# `extra` is rejected; it must be passed as a named parameter.
_VALIDATE_REQUEST_ARGS: frozenset[str] = frozenset({"files", "allow_signatures"})

# Built once at import (TypeAdapter construction is expensive): the single parse path for a
# 200 `/validate` body into the protocol-neutral verdict union, discriminated on `is_valid`.
# The `pipelex-sdk` subclass parses the same body into its Pipelex-branded narrowing instead.
_VALIDATION_RESULT_ADAPTER: TypeAdapter[ValidationResult] = TypeAdapter(ValidationResult)

# The answer a route parses its success body into.
AnswerT = TypeVar("AnswerT")


def _usable_run_id(value: object) -> str | None:
    """A run id the client can read a run by: `value` when it is a non-empty string, which a run id must be, else `None`."""
    if not isinstance(value, str) or not value:
        return None
    return value


def _started_run_id(body: object) -> str | None:
    """The run a decoded success body names: its `pipeline_run_id` when it is a usable run id (`_usable_run_id`).

    Args:
        body: The decoded body, `None` when the body is not JSON.

    Returns:
        The run's id, or `None` when the body names no run the client can read.
    """
    if not isinstance(body, dict):
        return None
    return _usable_run_id(cast("dict[str, Any]", body).get("pipeline_run_id"))


def _outcome_unknown(*, started_run_id: str | None) -> Problem:
    """`client.outcome_unknown`, naming the run in its parameters and as its member when the client learned its id."""
    if started_run_id is None:
        return make_client_problem(CoreCode.CLIENT_OUTCOME_UNKNOWN)
    return make_client_problem(CoreCode.CLIENT_OUTCOME_UNKNOWN, params={"pipeline_run_id": started_run_id}, pipeline_run_id=started_run_id)


def _assert_run_sources(
    *, pipe_code: str | None, files: MethodFiles | None, extra: dict[str, Any] | None, route: Literal["execute", "start"]
) -> None:
    """Guard the run-source arguments of one `/execute` | `/start` call, before any body is built.

    Two checks: a `files` map, when given, holds at least one file, as a method tree does; and
    something to run must have been named — a pipe, a method tree, or a server-specific
    extension arg. Which extension arg names a run source, and which of them
    exclude each other, is the server's own contract: this client serves any MTHDS-compliant
    runner, so it counts the keys inside `extra` without interpreting them, and the runner
    answers for the combination it was sent. A client that takes those arguments by name can
    pre-empt the refusal from the shared definitions in `mthds.protocol.options`.

    The extension mapping is built here rather than only in `_build_run_body` so that a protocol
    arg smuggled through `extra` is refused at this boundary, before any body exists.

    Args:
        pipe_code: The pipe selector, or None.
        files: The method's tree as a map of file entries, or None.
        extra: Server-specific extension args from the caller, or None.
        route: The protocol route being called, for the error message (`execute` / `start`).

    Raises:
        PipelineRequestError: If `files` holds no file, if nothing to run was named, or if `extra`
            carries a protocol arg (`client.argument_invalid`).
    """
    extensions = _build_extensions(extra)
    _refuse_empty_files(files)
    if not pipe_code and files is None and not extensions:
        msg = f"Either pipe_code, files or a server-specific extension arg (extra) must be provided to the API {route}."
        raise make_argument_invalid_error(msg, argument="pipe_code", reason="nothing_to_run")


def _refuse_empty_files(files: MethodFiles | None) -> None:
    """Refuse a `files` map holding no file: a method tree holds at least one, and a runner answers an empty map with a 422.

    Raises:
        PipelineRequestError: If `files` is an empty map (`client.argument_invalid`).
    """
    if files is not None and not files:
        msg = "files holds no file, and a method tree holds at least one: send every file of the method's tree."
        raise make_argument_invalid_error(msg, argument="files", reason="empty")


def _build_run_body(
    *,
    pipe_code: str | None,
    files: MethodFiles | None,
    inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None,
    output_name: str | None,
    output_multiplicity: VariableMultiplicity | None,
    dynamic_output_concept_ref: str | None,
    extra: dict[str, Any] | None,
    exclude_none: bool = False,
) -> dict[str, Any]:
    """Assemble the `/execute` | `/start` request body — the protocol has no request model.

    The body is a plain mapping of the protocol's basic args plus any
    server-specific extension args (merged as top-level properties). `inputs`
    may carry pydantic objects (StuffContent, working memory) and `files` the
    typed file entries, so the caller serializes the returned mapping with
    `pydantic_core.to_json`, which handles both. With `exclude_none`, absent
    fields are pruned from the wire body.

    Raises:
        PipelineRequestError: If `extra` carries a protocol arg.
    """
    extensions = _build_extensions(extra)
    body: dict[str, Any] = {
        "pipe_code": pipe_code,
        # A plain dict, since `to_json` serializes no other mapping, a `MappingProxyType` or a `UserDict` among them.
        "files": None if files is None else dict(files),
        "inputs": inputs,
        "output_name": output_name,
        "output_multiplicity": output_multiplicity,
        "dynamic_output_concept_ref": dynamic_output_concept_ref,
        **extensions,
    }
    if exclude_none:
        body = {key: value for key, value in body.items() if value is not None}
    return body


def _build_extensions(extra: dict[str, Any] | None, *, protocol_args: frozenset[str] = _PROTOCOL_REQUEST_ARGS) -> dict[str, Any]:
    """Validate and copy the generic `extra` passthrough.

    Extension args ride the request body as top-level properties; the protocol's
    own args must be passed as named parameters, never smuggled through `extra`.

    Args:
        extra: Server-specific extension args from the caller, or None.
        protocol_args: The endpoint's protocol request args — a key in `extra`
            overlapping this set is rejected (it must be passed as a named
            parameter). Defaults to the `execute`/`start` arg set.

    Returns:
        A mutable copy of `extra` safe to merge into the body.

    Raises:
        PipelineRequestError: If `extra` carries a protocol arg.
    """
    extensions: dict[str, Any] = dict(extra or {})
    protocol_overlap = extensions.keys() & protocol_args
    if protocol_overlap:
        msg = f"extra carries protocol args {sorted(protocol_overlap)} — pass them as named parameters instead."
        raise make_argument_invalid_error(msg, argument="extra", reason="protocol_argument")
    return extensions


# The status of the `POST /blobs/missing` success, which a `missing_blobs` answer naming a blob the tree
# does not hold is read under, as `client.response_unreadable`.
_MISSING_BLOBS_SUCCESS_STATUS = 200


class _InlineTree(NamedTuple):
    """A tree's files read into memory, their inline entries, and the size the request spends on that map."""

    contents: dict[str, bytes]
    files: dict[str, FileEntry]
    encoded_size: int

    def held_bytes(self, tree_file: TreeFile) -> bytes:
        """A file's bytes, as read when the tree was encoded."""
        return self.contents[tree_file.path]


def _encode_inline(*, tree_files: list[TreeFile], read: Callable[[TreeFile], bytes]) -> _InlineTree:
    """Read every file of a tree and encode it inline, its text when its bytes are UTF-8 and else its Base64, measuring the map.

    The map is measured as the request spends it: written as JSON with no whitespace, in UTF-8. This
    reads, hashes and encodes, so a coroutine runs it in a thread.
    """
    contents = {tree_file.path: read(tree_file) for tree_file in tree_files}
    files = {tree_path: encode_file_entry(data) for tree_path, data in contents.items()}
    return _InlineTree(contents=contents, files=files, encoded_size=len(to_json(files)))


def _read_listed_file(tree: MethodTree, *, tree_file: TreeFile) -> bytes:
    """A listed file's bytes, read from disk and checked against the hash and size its listing recorded.

    Raises:
        TreeSourceError: If the file cannot be read, or its bytes are no longer those listed.
    """
    location = tree.file_location(tree_file.path)
    try:
        data = location.read_bytes()
    except OSError as exc:
        msg = f"The file {tree_file.path!r} of the tree rooted at {tree.directory} cannot be read: {exc}"
        raise TreeSourceError(msg) from exc
    if len(data) != tree_file.size or sha256_hex(data) != tree_file.sha256:
        msg = f"The file {tree_file.path!r} of the tree rooted at {tree.directory} changed after the tree was listed: list the tree again."
        raise TreeSourceError(msg)
    return data


def _is_create_only(target: UploadTarget) -> bool:
    """Whether an upload target asks for a create-only write, whose `412` means the bytes are already stored."""
    return any(name.lower() == "if-none-match" for name in target.headers)


def _url_without_query(url: str) -> str:
    """The URL without anything that may grant the write: its userinfo, its query and its fragment.

    A presigned query carries a signature, and a `user:password@` in the authority is a credential.
    """
    parts = urlsplit(url)
    host_and_port = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host_and_port, parts.path, "", ""))
