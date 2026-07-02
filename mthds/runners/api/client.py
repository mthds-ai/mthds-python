from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter
from pydantic_core import to_json
from typing_extensions import override

from mthds.config.credentials import load_credentials
from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import ModelCategory, ModelDeck, RunResultStart, ValidationResult, VersionInfo
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.exceptions import ClientAuthenticationError, RunStillRunningError
from mthds.runners.api.models import DictPipeOutputAbstract, DictRunResultExecute
from mthds.runners.types import RunnerType

if TYPE_CHECKING:
    from typing_extensions import Self

    from mthds.protocol.pipe_output import VariableMultiplicity
    from mthds.protocol.pipeline_inputs import PipelineInputs
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract


class MthdsAPIClient(MTHDSProtocol[DictPipeOutputAbstract]):
    """Client for any MTHDS runner — the MTHDS Protocol surface over HTTP.

    One base URL (`MTHDS_API_URL`); every endpoint is `<base>/v1/<endpoint>`. The
    five protocol routes (`execute` / `start` / `validate` / `models` / `version`)
    work against any MTHDS-compliant runner, hosted or bare. The durable run
    lifecycle (polling a run to completion by id) is a hosted-API extension that
    lives in `pipelex-sdk` (`PipelexAPIClient`), not in this protocol base.
    """

    # The client composes every endpoint from one origin (MTHDS_API_URL): `{base}/v1/{endpoint}`.
    # It targets the open-source pipelex-api runner (default http://localhost:8081/v1), but the
    # same paths are served by any MTHDS-Protocol server — the protocol surface is identical;
    # server-specific extensions (e.g. the hosted durable run lifecycle) are detectable via GET /version.
    # `_API_PREFIX` is the protocol surface identity (it tracks the protocol major version),
    # not per-call configuration — it stays a class constant; the timeout below is the default
    # for the overridable per-instance `request_timeout_seconds`.
    _API_PREFIX: ClassVar[str] = "v1"

    _DEFAULT_REQUEST_TIMEOUT_SECONDS: ClassVar[float] = 1200.0  # runner blocking-execute ceiling

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        request_timeout_seconds: float | None = None,
    ):
        credentials = load_credentials()

        resolved_api_key = api_key or credentials["api_key"]
        if not resolved_api_key:
            msg = "API key is required for API execution. Set MTHDS_API_KEY or run: mthds config set api-key <key>"
            raise ClientAuthenticationError(msg)
        self.api_key = resolved_api_key

        resolved_base_url = base_url or credentials["api_url"]
        if not resolved_base_url:
            msg = "API base URL is required for API execution. Set MTHDS_API_URL or run: mthds config set api-url <url>"
            raise ClientAuthenticationError(msg)
        self.base_url = resolved_base_url.rstrip("/")

        self.request_timeout_seconds = request_timeout_seconds or self._DEFAULT_REQUEST_TIMEOUT_SECONDS

        self.client: httpx.AsyncClient | None = None

    @property
    def runner_type(self) -> RunnerType:
        """Return the runner type (the API client IS the API runner — parity D8)."""
        return RunnerType.API

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start_client(self) -> MthdsAPIClient:
        """Initialize the HTTP client for API calls."""
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {self.api_key}"})
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

        Args:
            method: HTTP method ("GET" or "POST").
            url: Fully-resolved absolute URL.
            content: JSON-encoded request body, or None for a bodyless request.
            request_timeout: Per-request timeout in seconds.

        Returns:
            The httpx.Response, without status-code interpretation.
        """
        if not self.client:
            self.start_client()
            assert self.client is not None

        headers = {"Accept": "application/json"}
        if content is not None:
            headers["Content-Type"] = "application/json"
        return await self.client.request(method, url, content=content, headers=headers, timeout=request_timeout)

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
            RunStillRunningError: If the server answers 202 (the protocol's optional
                async degrade) — the run continues server-side; resume by `run_id`.
        """
        if not pipe_code and not mthds_contents and not extra:
            msg = "Either pipe_code, mthds_contents or a server-specific extension arg (extra) must be provided to the API execute."
            raise PipelineRequestError(msg)

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
        response = await self._send("POST", self._url("execute"), content=content, request_timeout=self.request_timeout_seconds)
        self._raise_if_execute_degraded(response)
        response.raise_for_status()
        return DictRunResultExecute.model_validate(response.json())

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
        """
        if not pipe_code and not mthds_contents and not extra:
            msg = "Either pipe_code, mthds_contents or a server-specific extension arg (extra) must be provided to the API start."
            raise PipelineRequestError(msg)

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
        response = await self._send("POST", self._url("start"), content=content, request_timeout=self.request_timeout_seconds)
        response.raise_for_status()
        return RunResultStart.model_validate(response.json())

    async def _post_validate(self, mthds_contents: list[str], allow_signatures: bool, extra: dict[str, Any] | None) -> httpx.Response:
        """POST a `/validate` request and return the raw 200-diagnostic response.

        The shared transport + body-building seam for `validate`: builds the request body
        (the protocol's basic args plus the generic `extra` extension passthrough, guarded
        against a smuggled protocol arg), sends it, and raises on a no-verdict non-2xx. The
        200 body — a produced verdict discriminated on `is_valid` — is left for the caller to
        parse into its own verdict union (the protocol-neutral `ValidationResult` here; the
        `pipelex-sdk` subclass narrows it to its Pipelex-branded report types). A documented
        protected extension seam, alongside `_send` / `_url` / `_build_run_body`.

        Raises:
            PipelineRequestError: if `extra` carries a protocol arg (`mthds_contents` or
                `allow_signatures`) — pass it as a named parameter instead.
            httpx.HTTPStatusError: a no-verdict response (request-shape 422, 401/403, or 5xx).
        """
        body: dict[str, Any] = {"mthds_contents": mthds_contents, "allow_signatures": allow_signatures}
        body.update(_build_extensions(extra, protocol_args=_VALIDATE_REQUEST_ARGS))
        content = to_json(body)
        response = await self._send(
            "POST",
            self._url("validate"),
            content=content,
            request_timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
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
        `httpx.HTTPStatusError`; an invalid bundle does NOT raise.

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
            (`is_valid: false`, with `validation_errors`). Implementation-specific
            artifacts (e.g. pipelex's structural artifacts, `rendered_markdown`) ride
            `model_extra`; the `pipelex-sdk` subclass narrows this to its typed
            `PipelexValidationReport` / `PipelexInvalidReport`.

        Raises:
            PipelineRequestError: if `extra` carries a protocol arg (`mthds_contents`
                or `allow_signatures`) — pass it as a named parameter instead.
            pydantic.ValidationError: a malformed 200 body — missing or non-boolean
                `is_valid` (the discriminant cannot be tagged), or a tagged arm missing
                a required field. A malformed 200 is a server bug, surfaced raw rather
                than wrapped or mistaken for a valid verdict.
            httpx.HTTPStatusError: a no-verdict response (request-shape 422, 401/403,
                or 5xx) — never an invalid bundle, which is a 200 `InvalidValidationReport`.
        """
        response = await self._post_validate(mthds_contents, allow_signatures, extra)
        return _VALIDATION_RESULT_ADAPTER.validate_python(response.json())

    @override
    async def models(self, category: ModelCategory | None = None) -> ModelDeck:
        """The model deck the runner can route to — `GET /v1/models[?type=]`.

        Args:
            category: Optional filter (`llm`, `extract`, `img_gen`, `search`).

        Returns:
            ModelDeck with the models this runner can route to (base fields
            + any implementation extensions).
        """
        endpoint = f"models?type={quote(category, safe='')}" if category is not None else "models"
        response = await self._send("GET", self._url(endpoint), content=None, request_timeout=self.request_timeout_seconds)
        response.raise_for_status()
        return ModelDeck.model_validate(response.json())

    @override
    async def version(self) -> VersionInfo:
        """Protocol + runner versions — `GET /v1/version` (public).

        Returns:
            VersionInfo — the handshake for feature detection (hosted extensions or not).
        """
        response = await self._send("GET", self._url("version"), content=None, request_timeout=self.request_timeout_seconds)
        response.raise_for_status()
        return VersionInfo.model_validate(response.json())

    def _raise_if_execute_degraded(self, response: httpx.Response) -> None:
        """Map the protocol's optional 202 execute degrade to a typed error.

        Hosted does not emit 202 today, but the protocol permits it; raising a typed
        error (with the `run_id` + `Location` + `Retry-After` hints) beats a generic
        validation failure on an unexpected body shape.
        """
        if response.status_code != 202:
            return
        body: dict[str, Any] = {}
        try:
            raw = response.json()
            if isinstance(raw, dict):
                body = cast("dict[str, Any]", raw)
        except ValueError:
            body = {}
        started_run_id = body.get("pipeline_run_id")
        run_id = started_run_id if isinstance(started_run_id, str) else ""
        msg = (
            f"execute() was accepted asynchronously (202): run {run_id or '<unknown>'} is still "
            "running server-side. Poll its results (hosted) or use start()."
        )
        raise RunStillRunningError(
            msg,
            run_id=run_id,
            retry_after_seconds=_parse_retry_after(response.headers),
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
        raise PipelineRequestError(msg)
    return extensions


def _parse_retry_after(headers: httpx.Headers) -> int | None:
    """Parse the `Retry-After` header (integer-seconds form, which the platform uses)."""
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
