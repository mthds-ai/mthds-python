from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, NoReturn, Self, cast
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from pydantic import TypeAdapter
from pydantic_core import to_json
from typing_extensions import override

from mthds.config import load_config
from mthds.method_tree.digest import sha256_hex, tree_digest, tree_files_from_contents
from mthds.method_tree.exceptions import TreeSourceError
from mthds.method_tree.file_entry import FileEntry, HashFileEntry, encode_file_entry
from mthds.protocol.exceptions import PipelineRequestError
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
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.exceptions import ApiResponseError, BlobUploadError, ClientAuthenticationError, RunStillRunningError
from mthds.runners.api.models import DictPipeOutputAbstract, DictRunResultExecute
from mthds.runners.api.problem import ProblemDocument
from mthds.runners.api.user_agent import AppInfo, build_user_agent, mthds_python_token
from mthds.runners.types import RunnerType

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from mthds.method_tree.file_entry import MethodFiles
    from mthds.method_tree.models import MethodTree, TreeFile
    from mthds.protocol.pipe_output import VariableMultiplicity
    from mthds.protocol.pipeline_inputs import PipelineInputs
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract


DEFAULT_INLINE_TREE_MAX_BYTES: Final[int] = 256 * 1024
"""The largest total, in bytes, of a tree `prepare_files` sends inline without asking the runner first.

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
    five protocol routes (`execute` / `start` / `validate` / `models` / `version`)
    work against any MTHDS-compliant runner, hosted or bare, each run or validation
    carrying the method as its whole method tree in `files`. The optional blob routes
    (`missing_blobs`, `upload_blob`) work against a runner whose `version()` declares
    `blob_store`, and `prepare_files` builds the `files` map from a listed tree, inline
    or by hash. The durable run lifecycle (polling a run to completion by id) is a
    hosted-API extension that lives in `pipelex-sdk` (`PipelexAPIClient`), not in this
    protocol base.
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
            ClientAuthenticationError: If no API key or base URL can be resolved.
            ValueError: If the assembled `User-Agent` is over the length limit.
        """
        self.init_user_agent(app_info)
        config = load_config()

        resolved_api_key = api_key or config["api_key"]
        if not resolved_api_key:
            msg = "API key is required for API execution. Set MTHDS_API_KEY or run: mthds config set api-key <key>"
            raise ClientAuthenticationError(msg)
        self.api_key = resolved_api_key

        resolved_base_url = base_url or config["base_url"]
        if not resolved_base_url:
            msg = "API base URL is required for API execution. Set MTHDS_BASE_URL or run: mthds config set base-url <url>"
            raise ClientAuthenticationError(msg)
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

        # `User-Agent` is set per request too, so a subclass overriding `start_client` cannot drop it.
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        if content is not None:
            headers["Content-Type"] = "application/json"
        return await self.client.request(method, url, content=content, headers=headers, timeout=request_timeout)

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
                or if `extra` carries a protocol arg.
            RunStillRunningError: If the server answers 202 (the protocol's optional
                async degrade) — the run continues server-side; resume by `run_id`.
            ApiResponseError: If the server answers non-2xx — a refusal to run an invalid
                method (`422`, its diagnostics on `validation_errors`, or `missing_blobs`
                naming each hash entry the runner does not hold), a failed run, auth, or a
                server fault — with the problem document's members typed.
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
        response = await self._send("POST", self._url("execute"), content=content, request_timeout=self.request_timeout_seconds)
        self._raise_if_execute_degraded(response)
        if not response.is_success:
            self._raise_api_response_error(method="POST", endpoint="execute", response=response)
        return DictRunResultExecute.model_validate(response.json())

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
                or if `extra` carries a protocol arg.
            ApiResponseError: If the server answers non-2xx — a refusal to run an invalid
                method (`422`, its diagnostics on `validation_errors`, or `missing_blobs`
                naming each hash entry the runner does not hold), auth, or a server
                fault — with the problem document's members typed.
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
        response = await self._send("POST", self._url("start"), content=content, request_timeout=self.request_timeout_seconds)
        if not response.is_success:
            self._raise_api_response_error(method="POST", endpoint="start", response=response)
        return RunResultStart.model_validate(response.json())

    async def _post_validate(self, files: MethodFiles, allow_signatures: bool, extra: dict[str, Any] | None) -> httpx.Response:
        """POST a `/validate` request and return the raw 200-diagnostic response.

        The shared transport + body-building seam for `validate`: builds the request body
        (the protocol's basic args plus the generic `extra` extension passthrough, guarded
        against a smuggled protocol arg), sends it, and raises `ApiResponseError` on a
        no-verdict non-2xx. The 200 body — a produced verdict discriminated on `is_valid` —
        is left for the caller to parse into its own verdict union (the protocol-neutral
        `ValidationResult` here; the `pipelex-sdk` subclass narrows it to its Pipelex-branded
        report types). A documented protected extension seam, alongside `_send` / `_url` /
        `_build_run_body`.

        Raises:
            PipelineRequestError: if `files` holds no file, or if `extra` carries a protocol
                arg (`files` or `allow_signatures`) — pass it as a named parameter instead.
            ApiResponseError: a no-verdict response (request-shape 422, 401/403, or 5xx).
        """
        _refuse_empty_files(files)
        body: dict[str, Any] = {"files": files, "allow_signatures": allow_signatures}
        body.update(_build_extensions(extra, protocol_args=_VALIDATE_REQUEST_ARGS))
        content = to_json(body)
        response = await self._send(
            "POST",
            self._url("validate"),
            content=content,
            request_timeout=self.request_timeout_seconds,
        )
        if not response.is_success:
            self._raise_api_response_error(method="POST", endpoint="validate", response=response)
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
            (`is_valid: false`, with `validation_errors`). Implementation-specific
            artifacts (e.g. pipelex's structural artifacts, `rendered_markdown`) ride
            `model_extra`; the `pipelex-sdk` subclass narrows this to its typed
            `PipelexValidationReport` / `PipelexInvalidReport`.

        Raises:
            PipelineRequestError: if `files` holds no file, or if `extra` carries a
                protocol arg (`files` or `allow_signatures`) — pass it as a named
                parameter instead.
            pydantic.ValidationError: a malformed 200 body — missing or non-boolean
                `is_valid` (the discriminant cannot be tagged), or a tagged arm missing
                a required field. A malformed 200 is a server bug, surfaced raw rather
                than wrapped or mistaken for a valid verdict.
            ApiResponseError: a no-verdict response (request-shape 422, 401/403,
                or 5xx) — never an invalid bundle, which is a 200 `InvalidValidationReport`.
        """
        response = await self._post_validate(files, allow_signatures, extra)
        return _VALIDATION_RESULT_ADAPTER.validate_python(response.json())

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
            ApiResponseError: If the server answers non-2xx.
        """
        endpoint = f"models?type={quote(category, safe='')}" if category is not None else "models"
        response = await self._send("GET", self._url(endpoint), content=None, request_timeout=self.request_timeout_seconds)
        if not response.is_success:
            self._raise_api_response_error(method="GET", endpoint=endpoint, response=response)
        return ModelDeck.model_validate(response.json())

    @override
    async def version(self) -> VersionInfo:
        """Protocol + runner versions — `GET /v1/version` (public).

        Returns:
            VersionInfo — the handshake for feature detection (hosted extensions or not).

        Raises:
            ApiResponseError: If the server answers non-2xx.
        """
        response = await self._send("GET", self._url("version"), content=None, request_timeout=self.request_timeout_seconds)
        if not response.is_success:
            self._raise_api_response_error(method="GET", endpoint="version", response=response)
        return VersionInfo.model_validate(response.json())

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
                or a server fault.
        """
        request = MissingBlobsRequest(blobs=list(blobs), digest=digest)
        content = request.model_dump_json(exclude_none=True).encode("utf-8")
        response = await self._send("POST", self._url("blobs/missing"), content=content, request_timeout=self.request_timeout_seconds)
        if not response.is_success:
            self._raise_api_response_error(method="POST", endpoint="blobs/missing", response=response)
        return MissingBlobsResult.model_validate(response.json())

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
            PipelineRequestError: If `data` is not the blob named: another SHA-256 or another size.
            BlobUploadError: If the target answers non-2xx, other than a create-only target's `412`.
        """
        async with self._make_upload_client() as upload_client:
            await self._upload_blob_with(upload_client=upload_client, blob=blob, data=data)

    async def prepare_files(self, tree: MethodTree, *, inline_max_bytes: int = DEFAULT_INLINE_TREE_MAX_BYTES) -> dict[str, FileEntry]:
        """The `files` map that sends a tree listed from a directory: inline, or by hash once the runner holds every blob.

        A tree whose files total at most `inline_max_bytes` travels inline whole, with no round trip.
        A larger one travels inline too when the runner keeps no blob store, as `version()` reports;
        otherwise `missing_blobs` is asked which blobs the runner lacks, naming the tree's digest,
        each missing blob is uploaded once, and every file travels by hash. Each file is read from
        disk and checked against the hash the listing recorded, so what travels is the tree the
        digest names.

        Args:
            tree: A tree listed from a directory, as `list_method_tree` returns it.
            inline_max_bytes: The largest total, in bytes, of a tree that travels inline without
                asking the runner whether it keeps a blob store.

        Returns:
            The map of file entries, keyed by tree path in tree path order, ready for `files`.

        Raises:
            PipelineRequestError: If the tree was not listed from a directory, or the runner asks for
                a blob the tree does not hold.
            TreeSourceError: If a file cannot be read, or changed after the tree was listed.
            ApiResponseError: If the runner answers `version` or `missing_blobs` non-2xx.
            BlobUploadError: If an upload target answers non-2xx.
        """
        if tree.directory is None:
            msg = "This tree was not listed from a directory, so its files cannot be read from disk: send its bytes with prepare_files_from_contents."
            raise PipelineRequestError(msg)
        return await self._prepare_files(
            tree_files=tree.files,
            digest=tree.digest,
            read=lambda tree_file: _read_listed_file(tree, tree_file=tree_file),
            inline_max_bytes=inline_max_bytes,
        )

    async def prepare_files_from_contents(
        self, contents: Mapping[str, bytes], *, inline_max_bytes: int = DEFAULT_INLINE_TREE_MAX_BYTES
    ) -> dict[str, FileEntry]:
        """The `files` map that sends a tree whose bytes are at hand, keyed by tree path, by the rule of `prepare_files`.

        Args:
            contents: Each file's bytes, by tree path. The keys are sent as they are, and the runner
                refuses one that is not a tree path.
            inline_max_bytes: The largest total, in bytes, of a tree that travels inline without
                asking the runner whether it keeps a blob store.

        Returns:
            The map of file entries, keyed by tree path in tree path order, ready for `files`.

        Raises:
            PipelineRequestError: If `contents` holds no file, or the runner asks for a blob the
                tree does not hold.
            ApiResponseError: If the runner answers `version` or `missing_blobs` non-2xx.
            BlobUploadError: If an upload target answers non-2xx.
        """
        tree_files = tree_files_from_contents(contents)
        return await self._prepare_files(
            tree_files=tree_files,
            digest=tree_digest(tree_files),
            read=lambda tree_file: contents[tree_file.path],
            inline_max_bytes=inline_max_bytes,
        )

    async def _prepare_files(
        self, *, tree_files: list[TreeFile], digest: str, read: Callable[[TreeFile], bytes], inline_max_bytes: int
    ) -> dict[str, FileEntry]:
        """Choose inline or hash entries for a tree's files, uploading what the runner lacks before naming anything by hash."""
        if not tree_files:
            msg = "The tree holds no file, and a method tree holds at least one."
            raise PipelineRequestError(msg)
        total_bytes = sum(tree_file.size for tree_file in tree_files)
        if total_bytes <= inline_max_bytes:
            return _inline_entries(tree_files=tree_files, read=read)
        version_info = await self.version()
        if not version_info.blob_store:
            return _inline_entries(tree_files=tree_files, read=read)
        # One blob per distinct hash: two files with the same bytes are one blob, listed and uploaded once.
        file_of_blob: dict[str, TreeFile] = {}
        for tree_file in tree_files:
            file_of_blob.setdefault(tree_file.sha256, tree_file)
        blobs = [BlobRef(sha256=tree_file.sha256, size=tree_file.size) for tree_file in file_of_blob.values()]
        answer = await self.missing_blobs(blobs, digest=digest)
        await self._upload_missing(answer.missing, file_of_blob=file_of_blob, read=read)
        return {tree_file.path: HashFileEntry(sha256=tree_file.sha256, size=tree_file.size) for tree_file in tree_files}

    async def _upload_missing(self, missing: list[MissingBlob], *, file_of_blob: dict[str, TreeFile], read: Callable[[TreeFile], bytes]) -> None:
        """Upload every missing blob, a bounded number at a time, reading each one's bytes only when its turn comes.

        Every upload runs to its end before the first failure is raised, so no upload is left
        running against a closed connection; a blob uploaded beside a failed one is stored, which
        is harmless since a blob is named by its bytes.
        """
        unknown = sorted({blob.sha256 for blob in missing if blob.sha256 not in file_of_blob})
        if unknown:
            msg = f"The runner asked for blobs this tree does not hold: {', '.join(unknown)}."
            raise PipelineRequestError(msg)
        if not missing:
            return
        slots = asyncio.Semaphore(_MAX_CONCURRENT_UPLOADS)
        async with self._make_upload_client() as upload_client:

            async def upload_one(blob: MissingBlob) -> None:
                async with slots:
                    await self._upload_blob_with(upload_client=upload_client, blob=blob, data=read(file_of_blob[blob.sha256]))

            outcomes = await asyncio.gather(*(upload_one(blob) for blob in missing), return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                raise outcome

    def _make_upload_client(self) -> httpx.AsyncClient:
        """The HTTP client blob uploads go through, apart from the API client: no default header, no auth, no event hook."""
        return httpx.AsyncClient()

    async def _upload_blob_with(self, *, upload_client: httpx.AsyncClient, blob: MissingBlob, data: bytes) -> None:
        """Upload one blob through `upload_client`, with exactly its target's headers; see `upload_blob`."""
        if len(data) != blob.size or sha256_hex(data) != blob.sha256:
            msg = (
                f"The bytes given for blob {blob.sha256} are not that blob: "
                f"they hash to {sha256_hex(data)} and hold {len(data)} bytes, not {blob.size}."
            )
            raise PipelineRequestError(msg)
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
        reason = _body_excerpt(response.text) or response.reason_phrase or "no reason given"
        msg = f"Uploading blob {blob.sha256} to {upload_url} failed ({response.status_code}): {reason}"
        raise BlobUploadError(
            msg,
            sha256=blob.sha256,
            status=response.status_code,
            status_text=response.reason_phrase,
            response_body=response.text,
            upload_url=upload_url,
        )

    def _raise_api_response_error(self, *, method: str, endpoint: str, response: httpx.Response) -> NoReturn:
        """Raise the typed `ApiResponseError` for a non-2xx answer, its problem document's members parsed.

        Every route calls this on a non-2xx answer, so it is the one place an answer becomes an error.
        A documented protected extension seam: a client built on this one overrides it to raise its own
        subclass of `ApiResponseError` (one that narrows `validation_errors`, or carries members of its
        own), and every inherited route then raises that subclass.

        Args:
            method: The HTTP method of the request, for the message (`POST`).
            endpoint: The endpoint below the protocol prefix, query included, exactly as the route sent it
                (`execute`, `models?type=llm`): it names the request in the message and gives `request_url`.
            response: The runner's non-2xx answer.

        Raises:
            ApiResponseError: Always.
        """
        document = ProblemDocument.make_from_response(response)
        reason = _failure_reason(document, response)
        msg = f"API {method} /{self._API_PREFIX}/{endpoint} failed ({response.status_code}): {reason}"
        raise ApiResponseError(
            msg,
            api_url=self.base_url,
            status=response.status_code,
            status_text=response.reason_phrase,
            response_body=response.text,
            headers=dict(response.headers),
            request_url=self._url(endpoint),
            error_type=document.error_type,
            server_message=document.server_message,
            validation_errors=document.validation_errors,
            type_uri=document.type_uri,
            title=document.title,
            instance=document.instance,
            request_id=document.request_id,
            error_domain=document.error_domain,
            retryable=document.retryable,
            user_action=document.user_action,
            problem=document.members,
        )

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
            carries a protocol arg.
    """
    extensions = _build_extensions(extra)
    _refuse_empty_files(files)
    if not pipe_code and files is None and not extensions:
        msg = f"Either pipe_code, files or a server-specific extension arg (extra) must be provided to the API {route}."
        raise PipelineRequestError(msg)


def _refuse_empty_files(files: MethodFiles | None) -> None:
    """Refuse a `files` map holding no file: a method tree holds at least one, and a runner answers an empty map with a 422.

    Raises:
        PipelineRequestError: If `files` is an empty map.
    """
    if files is not None and not files:
        msg = "files holds no file, and a method tree holds at least one: send every file of the method's tree."
        raise PipelineRequestError(msg)


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
        "files": files,
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


# How much of a body that is no problem document the error's message quotes; `response_body` keeps it whole.
_REASON_BODY_LIMIT = 500


def _inline_entries(*, tree_files: list[TreeFile], read: Callable[[TreeFile], bytes]) -> dict[str, FileEntry]:
    """Every file of a tree as an inline entry: its text when its bytes are UTF-8, else its bytes in Base64."""
    return {tree_file.path: encode_file_entry(read(tree_file)) for tree_file in tree_files}


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
    """The URL without its query and fragment, which may carry a signature granting the write."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _body_excerpt(body: str) -> str:
    """A body stripped and cut short for an error message, since an object store's error page can be long."""
    stripped = body.strip()
    return stripped if len(stripped) <= _REASON_BODY_LIMIT else f"{stripped[:_REASON_BODY_LIMIT]}…"


def _failure_reason(document: ProblemDocument, response: httpx.Response) -> str:
    """The reason a non-2xx answer gives, in the order a person is best served by.

    The problem's `detail`, else its `title`, else the raw body (cut short, since a gateway's HTML
    page can be long), else the status text.
    """
    for candidate in (document.server_message, document.title):
        if candidate and candidate.strip():
            return candidate
    excerpt = _body_excerpt(response.text)
    if excerpt:
        return excerpt
    return response.reason_phrase or "no reason given"


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
