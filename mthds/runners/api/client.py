from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NoReturn, Self, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError
from pydantic_core import to_json
from typing_extensions import override

from mthds.config import load_config
from mthds.protocol.exceptions import make_argument_invalid_error
from mthds.protocol.models import ModelCategory, ModelDeck, RunResultStart, ValidationResult, VersionInfo
from mthds.protocol.problem.answers import RETRY_AFTER_HEADER, parse_retry_after, unreadable_answer
from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.registry import CoreCode
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.exceptions import ApiResponseError, ApiTransportError, ClientNotConfiguredError, RunStillRunningError
from mthds.runners.api.models import DictPipeOutputAbstract, DictRunResultExecute
from mthds.runners.api.problem import answer_excerpt, answer_request_id, lower_case_headers, read_response_problem, transport_failure_problem
from mthds.runners.api.user_agent import AppInfo, build_user_agent, mthds_python_token
from mthds.runners.types import RunnerType

if TYPE_CHECKING:
    from collections.abc import Callable

    from mthds.protocol.pipe_output import VariableMultiplicity
    from mthds.protocol.pipeline_inputs import PipelineInputs
    from mthds.protocol.problem.models import Problem
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract


class MthdsAPIClient(MTHDSProtocol[DictPipeOutputAbstract]):
    """Client for any MTHDS runner — the MTHDS Protocol surface over HTTP.

    One base URL (`MTHDS_BASE_URL`); every endpoint is `<base>/v1/<endpoint>`. The
    five protocol routes (`execute` / `start` / `validate` / `models` / `version`)
    work against any MTHDS-compliant runner, hosted or bare. The durable run
    lifecycle (polling a run to completion by id) is a hosted-API extension that
    lives in `pipelex-sdk` (`PipelexAPIClient`), not in this protocol base.

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
            ClientNotConfiguredError: If no API key or base URL can be resolved
                (`client.not_configured`, naming the setting).
            ValueError: If the assembled `User-Agent` is over the length limit.
        """
        self.init_user_agent(app_info)
        config = load_config()

        resolved_api_key = api_key or config["api_key"]
        if not resolved_api_key:
            msg = "API key is required for API execution. Set MTHDS_API_KEY or run: mthds config set api-key <key>"
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

        The body is read whole before returning. A body whose content encoding cannot be decoded,
        such as a broken gzip stream, is read as an empty body, so that the answer's status still
        decides how it reads rather than the decoding failure escaping as no answer at all.

        Args:
            method: HTTP method ("GET" or "POST").
            url: Fully-resolved absolute URL.
            content: JSON-encoded request body, or None for a bodyless request.
            request_timeout: Per-request timeout in seconds.

        Returns:
            The httpx.Response, without status-code interpretation.

        Raises:
            httpx.TransportError: If no answer came back; `_request` reads it as a problem.
        """
        if not self.client:
            self.start_client()
            assert self.client is not None

        # `User-Agent` is set per request too, so a subclass overriding `start_client` cannot drop it.
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if content is not None:
            headers["Content-Type"] = "application/json"
        request = self.client.build_request(method, url, content=content, headers=headers, timeout=request_timeout)
        response = await self.client.send(request, stream=True)
        try:
            await response.aread()
        except httpx.DecodingError:
            undecoded_headers = [(name, value) for name, value in response.headers.items() if name.lower() != "content-encoding"]
            return httpx.Response(response.status_code, headers=undecoded_headers, request=request)
        finally:
            await response.aclose()
        return response

    async def _request(self, method: str, endpoint: str, *, content: bytes | None, creates_run: bool) -> httpx.Response:
        """Send one request through `_send`, reading a request that got no answer as a problem.

        Every route sends through this, so a request that got no answer raises an
        `ApiTransportError` on every route: `client.unreachable` when nothing left,
        `client.timeout` when a call that creates nothing got no answer in time, and
        `client.outcome_unknown` when a request that creates a run left and no answer came
        back. A documented protected extension seam: a client built on this one sends its own
        routes through it too.

        Args:
            method: HTTP method ("GET" or "POST").
            endpoint: The endpoint below the protocol prefix, query included (`execute`, `models?type=llm`).
            content: JSON-encoded request body, or None for a bodyless request.
            creates_run: Whether the request may create a run, as `POST /execute` and `POST /start` do.

        Returns:
            The answer, whatever its status.

        Raises:
            ApiTransportError: If no answer came back.
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
        except httpx.TransportError as exc:
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
        raises it with `client.response_unreadable`. A documented protected extension seam: a
        client built on this one parses its own routes' answers through it too.

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
            self._raise_api_response_error(
                method=method, endpoint=endpoint, response=response, problem=read_response_problem(response, creates_run=creates_run)
            )
        try:
            decoded = json.loads(response.text)
        except (ValueError, RecursionError):
            self._raise_api_response_error(method=method, endpoint=endpoint, response=response, problem=unreadable_answer(response.status_code))
        try:
            return parse(decoded)
        except ValidationError:
            self._raise_api_response_error(method=method, endpoint=endpoint, response=response, problem=unreadable_answer(response.status_code))

    # ── Protocol surface ─────────────────────────────────────────────────

    @override
    async def execute(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DictRunResultExecute:
        """Execute a method synchronously and wait for its completion — `POST /v1/execute`.

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
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
            PipelineRequestError: If nothing to run was named, or if `extra` carries a
                protocol arg (`client.argument_invalid`).
            RunStillRunningError: If the server answers 202 (the protocol's optional
                async degrade) — the run continues server-side; resume by `run_id`
                (`client.follow_failed`).
            ApiResponseError: If the server answers non-2xx — a refusal to run an invalid
                method (`method.invalid`, its faults on `problem.errors`), a failed run, auth,
                or a server fault — or a success the client cannot read.
            ApiTransportError: If no answer came back; a request that left reads as
                `client.outcome_unknown`, since the run may exist.
        """
        _assert_run_sources(pipe_code=pipe_code, mthds_contents=mthds_contents, extra=extra, route="execute")

        body = _build_run_body(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
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
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunResultStart:
        """Start a method asynchronously — `POST /v1/start` (202: `pipeline_run_id` only).

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
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
            PipelineRequestError: If nothing to run was named, or if `extra` carries a
                protocol arg (`client.argument_invalid`).
            ApiResponseError: If the server answers non-2xx — a refusal to run an invalid
                method (`method.invalid`, its faults on `problem.errors`), auth, or a server
                fault — or a success the client cannot read.
            ApiTransportError: If no answer came back; a request that left reads as
                `client.outcome_unknown`, since the run may exist.
        """
        _assert_run_sources(pipe_code=pipe_code, mthds_contents=mthds_contents, extra=extra, route="start")

        body = _build_run_body(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
            extra=extra,
            exclude_none=True,
        )
        content = to_json(body)
        response = await self._request("POST", "start", content=content, creates_run=True)
        return self._parse_answer(method="POST", endpoint="start", response=response, creates_run=True, parse=RunResultStart.model_validate)

    async def _post_validate(self, mthds_contents: list[str], allow_signatures: bool, extra: dict[str, Any] | None) -> httpx.Response:
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
            PipelineRequestError: if `extra` carries a protocol arg (`mthds_contents` or
                `allow_signatures`) — pass it as a named parameter instead (`client.argument_invalid`).
            ApiResponseError: a no-verdict response (request-shape 422, 401/403, or 5xx).
            ApiTransportError: if no answer came back.
        """
        body: dict[str, Any] = {"mthds_contents": mthds_contents, "allow_signatures": allow_signatures}
        body.update(_build_extensions(extra, protocol_args=_VALIDATE_REQUEST_ARGS))
        content = to_json(body)
        response = await self._request("POST", "validate", content=content, creates_run=False)
        if not response.is_success:
            self._raise_api_response_error(
                method="POST", endpoint="validate", response=response, problem=read_response_problem(response, creates_run=False)
            )
        return response

    @override
    async def validate(
        self,
        mthds_contents: list[str],
        allow_signatures: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Parse, validate, and dry-run an MTHDS bundle — `POST /v1/validate`.

        `/validate` is 200-diagnostic: a produced verdict — valid or invalid — rides a
        200 body discriminated on `is_valid`. A non-2xx response means no verdict could
        be produced (request shape, auth, server fault) and surfaces as an
        `ApiResponseError`; an invalid bundle does NOT raise.

        Args:
            mthds_contents: MTHDS contents to load (always a list, even for one file)
            allow_signatures: Tolerate unimplemented pipe signatures (strict by default)
            extra: Server-specific extension args, merged into the request body
                as top-level properties — the server you call defines and handles
                them; this SDK only passes them through. For example, a server may
                accept `extra={"mthds_sources": [...]}` (per-content source names,
                parallel to `mthds_contents`) to thread each onto the corresponding
                diagnostic's `source`. Protocol args (`mthds_contents`,
                `allow_signatures`) must be passed as named parameters, not through
                `extra` (raises `PipelineRequestError`).

        Returns:
            The protocol-neutral 200-diagnostic union (`ValidationResult`): a
            `ValidationReport` (`is_valid: true`) or an `InvalidValidationReport`
            (`is_valid: false`, with its faults in `errors`). Both arms carry the advisory
            `warnings`, and every fault and warning is a `ProblemItem`.
            Implementation-specific artifacts (e.g. pipelex's structural artifacts,
            `rendered_markdown`) ride `model_extra`; the `pipelex-sdk` subclass narrows
            this to its typed `PipelexValidationReport` / `PipelexInvalidReport`.

        Raises:
            PipelineRequestError: if `extra` carries a protocol arg (`mthds_contents`
                or `allow_signatures`) — pass it as a named parameter instead
                (`client.argument_invalid`).
            ApiResponseError: a no-verdict response (request-shape 422, 401/403,
                or 5xx) — never an invalid bundle, which is a 200 `InvalidValidationReport` —
                or a malformed 200 body, missing or non-boolean `is_valid` or a tagged arm
                missing a required field, which reads as `client.response_unreadable`
                rather than being mistaken for a verdict.
            ApiTransportError: if no answer came back.
        """
        response = await self._post_validate(mthds_contents, allow_signatures, extra)
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

    def _raise_api_response_error(self, *, method: str, endpoint: str, response: httpx.Response, problem: Problem) -> NoReturn:
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
            problem: The problem the answer reads as (`mthds.runners.api.problem.read_response_problem`
                for a non-2xx, `mthds.protocol.problem.answers.unreadable_answer` for a success it cannot read).

        Raises:
            ApiResponseError: Always.
        """
        msg = f"API {method} /{self._API_PREFIX}/{endpoint} failed ({response.status_code}): {problem.detail}"
        excerpt = answer_excerpt(response, problem=problem)
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
        the `Location` and `Retry-After` hints on the error; a 202 that names no run is an answer the
        client cannot read.

        Raises:
            RunStillRunningError: If the answer is a 202 naming its run.
            ApiResponseError: If the answer is a 202 naming no run (`client.response_unreadable`).
        """
        if response.status_code != 202:
            return
        try:
            raw = response.json()
        except (ValueError, RecursionError):
            raw = None
        started_run_id = cast("dict[str, Any]", raw).get("pipeline_run_id") if isinstance(raw, dict) else None
        if not isinstance(started_run_id, str) or not started_run_id:
            self._raise_api_response_error(method="POST", endpoint="execute", response=response, problem=unreadable_answer(response.status_code))
        problem = make_client_problem(CoreCode.CLIENT_FOLLOW_FAILED, params={"pipeline_run_id": started_run_id})
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


# The protocol's basic request args — the named parameters of execute()/start().
# Anything else a caller passes is an extension arg: it rides `extra` and merges
# into the body as a top-level property. A protocol arg smuggled through `extra`
# is rejected (it must be passed as a named parameter).
_PROTOCOL_REQUEST_ARGS: frozenset[str] = frozenset(
    {"pipe_code", "mthds_contents", "inputs", "output_name", "output_multiplicity", "dynamic_output_concept_ref"}
)

# The protocol's `/validate` request args — the named parameters of validate().
# Same guard as execute()/start(): a validate protocol arg smuggled through
# `extra` is rejected; it must be passed as a named parameter.
_VALIDATE_REQUEST_ARGS: frozenset[str] = frozenset({"mthds_contents", "allow_signatures"})

# Built once at import (TypeAdapter construction is expensive): the single parse path for a
# 200 `/validate` body into the protocol-neutral verdict union, discriminated on `is_valid`.
# The `pipelex-sdk` subclass parses the same body into its Pipelex-branded narrowing instead.
_VALIDATION_RESULT_ADAPTER: TypeAdapter[ValidationResult] = TypeAdapter(ValidationResult)

# The answer a route parses its success body into.
AnswerT = TypeVar("AnswerT")


def _assert_run_sources(
    *, pipe_code: str | None, mthds_contents: list[str] | None, extra: dict[str, Any] | None, route: Literal["execute", "start"]
) -> None:
    """Guard the run-source arguments of one `/execute` | `/start` call, before any body is built.

    One check: something to run must have been named — a pipe, inline contents, or a
    server-specific extension arg. Which extension arg names a run source, and which of them
    exclude each other, is the server's own contract: this client serves any MTHDS-compliant
    runner, so it counts the keys inside `extra` without interpreting them, and the runner
    answers for the combination it was sent. A client that takes those arguments by name can
    pre-empt the refusal from the shared definitions in `mthds.protocol.options`.

    The extension mapping is built here rather than only in `_build_run_body` so that a protocol
    arg smuggled through `extra` is refused at this boundary, before any body exists.

    Args:
        pipe_code: The pipe selector, or None.
        mthds_contents: Inline MTHDS bundle contents, or None.
        extra: Server-specific extension args from the caller, or None.
        route: The protocol route being called, for the error message (`execute` / `start`).

    Raises:
        PipelineRequestError: If nothing to run was named, or if `extra` carries a protocol arg
            (`client.argument_invalid`).
    """
    extensions = _build_extensions(extra)
    if not pipe_code and not mthds_contents and not extensions:
        msg = f"Either pipe_code, mthds_contents or a server-specific extension arg (extra) must be provided to the API {route}."
        raise make_argument_invalid_error(msg, argument="pipe_code", reason="nothing_to_run")


def _build_run_body(
    *,
    pipe_code: str | None,
    mthds_contents: list[str] | None,
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
    may carry pydantic objects (StuffContent, working memory), so the caller
    serializes the returned mapping with `pydantic_core.to_json`, which handles
    them. With `exclude_none`, absent fields are pruned from the wire body.

    Raises:
        PipelineRequestError: If `extra` carries a protocol arg.
    """
    extensions = _build_extensions(extra)
    body: dict[str, Any] = {
        "pipe_code": pipe_code,
        "mthds_contents": mthds_contents,
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
