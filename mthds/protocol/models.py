"""Wire models for the MTHDS Protocol — mirrors `mthds-protocol.openapi.yaml` (the standard's normative artifact).

    POST /execute       : -> RunResultExecute (200: pipeline_run_id + pipe_output)
    POST /start         : -> RunResultStart   (202: pipeline_run_id only)
    POST /validate      :              -> ValidationResult (200 union: ValidationReport | InvalidValidationReport)
    GET  /models        :              -> ModelDeck
    GET  /version       :              -> VersionInfo
    POST /blobs/missing : MissingBlobsRequest -> MissingBlobsResult (optional, a runner with a blob store)

The run and validate routes have no request *model*: the SDK runners take the
request's basic arguments as named parameters and serialize the wire body
directly, merging any server-specific extension args as top-level properties.
The method those routes carry, `files`, is typed by `MethodFiles` in
`mthds.method_tree.file_entry`. The optional blob routes do have one, since a
sender builds their request from a listed tree rather than from named arguments.

Response models declare the protocol's BASE fields only and are extension-open
too: an implementation may return more, and those server-specific fields are
preserved as accessible attributes — the response side of the same passthrough
principle as the request-side `extra`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from mthds._utils.pydantic_utils import empty_list_factory_of

PipeOutputT = TypeVar("PipeOutputT")


# ── Run responses (`POST /execute` 200, `POST /start` 202) ───────────


class RunResultExecute(BaseModel, Generic[PipeOutputT]):
    """`POST /execute` 200 — the completed run.

    Two base fields: the authoritative server-generated `pipeline_run_id` and
    the method's `pipe_output` (always present — a completed run has output).
    Extension-open (`extra="allow"`): anything more an implementation returns
    (a run state, timestamps, output naming) rides `model_extra`, never named
    by this SDK.
    """

    model_config = ConfigDict(extra="allow")

    pipeline_run_id: str
    pipe_output: PipeOutputT


class RunResultStart(BaseModel):
    """`POST /start` 202 (and the optional `/execute` 202 degrade) — the started
    run's authoritative `pipeline_run_id`, nothing else.

    A started run has no output yet; how it is delivered later (polling,
    callbacks, anything else) is implementation-defined and outside the
    protocol. Extension-open (`extra="allow"`): an implementation may add its
    own fields (a workflow id, a created-at timestamp), preserved via
    `model_extra`.
    """

    model_config = ConfigDict(extra="allow")

    pipeline_run_id: str


# ── Discovery + validation (`POST /validate`, `GET /models`, `GET /version`) ──


class ModelCategory(StrEnum):
    """The protocol's model categories: what a deck entry's `type` reports and the `GET /models?type=` filter accepts.

    A category is a settings family of the language — the inline settings a model
    serves, and so the pipes that can name it: `llm` (`LLMSetting`, named by
    `PipeLLM` and `PipeStructure`), `extract` (`ExtractSetting`, `PipeExtract`),
    `img_gen` (`ImgGenSetting`, `PipeImgGen`), `search` (`SearchSetting`,
    `PipeSearch`) and `judgment` (`JudgmentSetting`, `PipeJudge`). A settings
    family the standard adds brings a category in the next protocol minor.
    """

    LLM = "llm"
    EXTRACT = "extract"
    IMG_GEN = "img_gen"
    SEARCH = "search"
    JUDGMENT = "judgment"


class ModelInfo(BaseModel):
    """One entry of the model deck (`ModelDeck.models[]`) — base fields + extensions.

    `type` is an open read of the entry's category, under the protocol's reader
    rule: "A client reading a model list MUST NOT fail it because an entry carries
    a category it does not recognize; it keeps that entry with its raw value or
    leaves it out." This package keeps it: a category it knows reads as its
    `ModelCategory` member, and one it does not — a category a runner of a later
    protocol minor reports — keeps its raw string, so a consumer handles the
    `str` case rather than the whole deck failing. The union is validated left to
    right on purpose: pydantic's default smart mode would keep every string,
    known or not, as a plain `str`.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    type: Annotated[ModelCategory | str | None, Field(union_mode="left_to_right")] = None


class ModelDeck(BaseModel):
    """The model deck a runner can route to — `GET /models`.

    The protocol's base is the `models` list; implementations may add their own
    routing metadata (aliases, fallback chains, anything else) as extensions.
    """

    model_config = ConfigDict(extra="allow")

    models: list[ModelInfo] = Field(default_factory=empty_list_factory_of(ModelInfo))


class ValidationReport(BaseModel):
    """The VALID arm of the `POST /validate` 200 response union (`is_valid: true`).

    `/validate` is a diagnostic endpoint: any produced verdict — valid or invalid —
    rides a **200** body discriminated on `is_valid`. This is the valid arm; an
    invalid verdict is the sibling `InvalidValidationReport` (also 200), NOT a 422
    problem. Non-2xx is reserved for "no verdict could be produced" (malformed
    request, auth, server fault).

    The protocol declares only the `is_valid` discriminant here; implementations
    include their own artifacts (parsed structures, graphs, anything else),
    preserved as extension attributes (`extra="allow"`).

    Two of those extensions are the standard's own **recommended extension
    fields**, each with a page of its own since `mthds` v0.9.0 and typed in this
    package: `pipe_io_contracts` (`mthds.protocol.pipe_io_contracts.PipeIOContracts`)
    and `input_form` (`mthds.protocol.input_form.InputForm`). They stay extensions —
    the protocol's base fields did not change, and how a caller asks for the
    descriptor is implementation-defined — so they ride `model_extra` and a
    consumer narrows them by declaring typed fields on a model that extends this
    report — `pipe_io_contracts: PipeIOContracts | None = None` and
    `input_form: InputForm | None = None` — parsed by pydantic from the plain
    annotations, with no adapter machinery. That is how the Pipelex SDK narrows
    the same 200 body. Unlike this envelope, the artifacts themselves are closed
    shapes.
    """

    model_config = ConfigDict(extra="allow")

    is_valid: Literal[True] = True


class ValidationDiagnostic(BaseModel):
    """One diagnostic in `InvalidValidationReport.validation_errors[]` — protocol base.

    The protocol fixes only the neutral `category` + `message`; implementations
    narrow `category` to their closed vocabulary and add structured locators
    (preserved as extensions until narrowed). Named `ValidationDiagnostic` to stay
    distinct from `pydantic.ValidationError` (this is a wire model, not an exception).
    """

    model_config = ConfigDict(extra="allow")

    category: str
    message: str


ValidationDiagnosticT = TypeVar("ValidationDiagnosticT", bound=ValidationDiagnostic, covariant=True)


class InvalidValidationReport(BaseModel, Generic[ValidationDiagnosticT]):
    """The INVALID arm of the `POST /validate` 200 response union (`is_valid: false`).

    Carries the per-error diagnostics (`validation_errors[]`, always non-empty on an
    invalid verdict), best-effort `pending_signatures`, `is_runnable: false`, and a
    human-readable `message`. The structural artifacts of the valid arm are absent —
    they do not exist when load/parse/wiring failed.

    Generic over the diagnostic item type so an implementation can narrow
    `validation_errors` to its structured item (e.g. pipelex's `ValidationErrorItem`)
    without re-declaring the field.
    """

    model_config = ConfigDict(extra="allow")

    is_valid: Literal[False] = False
    validation_errors: list[ValidationDiagnosticT]
    pending_signatures: list[str] = Field(default_factory=list)
    is_runnable: Literal[False] = False
    message: str


ValidationResult: TypeAlias = Annotated[
    ValidationReport | InvalidValidationReport[ValidationDiagnostic],
    Field(discriminator="is_valid"),
]
"""The `POST /validate` 200 response — discriminated on `is_valid`.

A consumer pattern-matches the one mandatory field (`is_valid`) regardless of
outcome, and never inspects a status code or catches an exception body to learn the
verdict. Non-2xx means the endpoint could not produce a verdict.
"""


class VersionInfo(BaseModel):
    """Protocol + runner versions — `GET /version` (always public).

    The handshake clients use for feature detection. The protocol defines
    `protocol_version`, an optional `runner_version` and an optional
    `blob_store` flag; implementations may add their own identification (a
    name, an underlying runtime version, anything else) as extensions.
    """

    model_config = ConfigDict(extra="allow")

    protocol_version: str
    runner_version: str | None = None
    blob_store: bool = Field(
        default=False,
        description=(
            "True when the runner keeps a blob store: it serves POST /blobs/missing and resolves hash entries in a files map. "
            "False or absent when it does not, in which case it answers any hash entry with a 422 listing missing_blobs."
        ),
    )


# ── Sending files by hash (`POST /blobs/missing`, optional) ──────────

SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
TREE_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"

_SIZE_DESCRIPTION = (
    "The length of the bytes, a JSON integer written without a fraction or an exponent. "
    "A size written 13.0 is refused, although JSON Schema's integer type admits it."
)


class BlobRef(BaseModel):
    """A blob, named by its SHA-256 in lowercase hexadecimal and its length in bytes.

    Closed, as the protocol declares it. `size` is strict, so a size read as a float, being
    written with a fraction or an exponent, or a boolean is refused.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str = Field(pattern=SHA256_HEX_PATTERN, description="The SHA-256 of the bytes, in lowercase hexadecimal.")
    size: StrictInt = Field(ge=0, description=_SIZE_DESCRIPTION)


class MissingBlobsRequest(BaseModel):
    """`POST /blobs/missing` request — the blobs a sender is about to send by hash, and optionally the tree they make up.

    Each hash is listed once. `digest` names the tree the blobs make up, so a runner that has
    recorded that tree as held in full may answer with an empty list at once. Extension-open
    (`extra="allow"`), as the protocol declares it.
    """

    model_config = ConfigDict(extra="allow")

    blobs: list[BlobRef] = Field(default_factory=empty_list_factory_of(BlobRef), description="The blobs to check, each hash listed once.")
    digest: str | None = Field(default=None, pattern=TREE_DIGEST_PATTERN, description="The tree digest of the method tree the blobs make up.")


class UploadTarget(BaseModel):
    """Where to upload one blob: its bytes as the whole body of a request with this `method` to this `url`, with exactly these `headers`.

    The target is the runner's choice: its own `PUT /blobs/{sha256}`, or any address that stores
    the bytes where the runner reads its blobs, such as a presigned object-store URL. Extension-open.
    """

    model_config = ConfigDict(extra="allow")

    method: str = Field(description="The HTTP method, such as PUT.")
    url: str = Field(description="Where to send the bytes.")
    headers: dict[str, str] = Field(description="The headers to send, exactly.")


class MissingBlob(BaseModel):
    """A blob the runner lacks, with where to upload it. Extension-open."""

    model_config = ConfigDict(extra="allow")

    sha256: str = Field(pattern=SHA256_HEX_PATTERN, description="The SHA-256 of the bytes, in lowercase hexadecimal.")
    size: StrictInt = Field(ge=0, description=_SIZE_DESCRIPTION)
    upload: UploadTarget


class MissingBlobsResult(BaseModel):
    """`POST /blobs/missing` 200 — every blob of the request the runner does not hold; empty when there is nothing to upload.

    Extension-open (`extra="allow"`).
    """

    model_config = ConfigDict(extra="allow")

    missing: list[MissingBlob]
