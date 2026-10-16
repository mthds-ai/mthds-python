"""Wire models for the MTHDS Protocol — mirrors `mthds-protocol.openapi.yaml` (the standard's normative artifact).

    POST /execute  : -> RunResultExecute (200: pipeline_run_id + pipe_output)
    POST /start    : -> RunResultStart   (202: pipeline_run_id only)
    POST /validate :              -> ValidationResult (200 union: ValidationReport | InvalidValidationReport, items ProblemItem)
    GET  /models   :              -> ModelDeck
    GET  /version  :              -> VersionInfo

The protocol has no request *model*: the SDK runners take the request's basic
arguments as named parameters and serialize the wire body directly, merging
any server-specific extension args as top-level properties.

Response models declare the protocol's BASE fields only and are extension-open
too: an implementation may return more, and those server-specific fields are
preserved as accessible attributes — the response side of the same passthrough
principle as the request-side `extra`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from mthds._utils.pydantic_utils import empty_list_factory_of
from mthds.protocol.problem.models import ProblemItem

PipeOutputT = TypeVar("PipeOutputT")

# The item type of a `/validate` verdict's `errors` and `warnings`: the protocol's `ProblemItem`, or an
# implementation's subclass of it. Covariant, so a narrowed verdict is still a verdict of the base item.
ProblemItemT = TypeVar("ProblemItemT", bound=ProblemItem, covariant=True)


def _no_items() -> list[Any]:
    """The empty item list a verdict without warnings reads as, whatever its item type."""
    return []


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


class ValidationReport(BaseModel, Generic[ProblemItemT]):
    """The VALID arm of the `POST /validate` 200 response union (`is_valid: true`).

    `/validate` is a diagnostic endpoint: any produced verdict — valid or invalid —
    rides a **200** body discriminated on `is_valid`. This is the valid arm; an
    invalid verdict is the sibling `InvalidValidationReport` (also 200), NOT a 422
    problem. Non-2xx is reserved for "no verdict could be produced" (malformed
    request, auth, server fault).

    The protocol declares the `is_valid` discriminant, the runnability facts and the
    advisory `warnings` here, one `ProblemItem` each, which never make the bundle
    invalid; implementations include their own artifacts (parsed structures, graphs,
    anything else), preserved as extension attributes (`extra="allow"`).

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

    Generic over the item type of `warnings`, like `InvalidValidationReport`.
    """

    model_config = ConfigDict(extra="allow")

    is_valid: Literal[True] = True
    warnings: list[ProblemItemT] = Field(default_factory=_no_items)


class InvalidValidationReport(BaseModel, Generic[ProblemItemT]):
    """The INVALID arm of the `POST /validate` 200 response union (`is_valid: false`).

    Carries one `ProblemItem` per fault in `errors` (always non-empty on an invalid
    verdict), each with its own code, detail, params and location, the advisory
    `warnings` in the same item schema, best-effort `pending_signatures`,
    `is_runnable: false`, and, when the runner gives one, a human-readable `message`.
    The structural artifacts of the valid arm are absent — they do not exist when
    load/parse/wiring failed. An item carries a code and no verdict: its domain is read
    from its code (`ProblemItem.effective_domain`).

    Generic over the item type so an implementation can narrow `errors` and `warnings`
    to its own subclass of `ProblemItem` without re-declaring the fields.
    """

    model_config = ConfigDict(extra="allow")

    is_valid: Literal[False] = False
    errors: Annotated[list[ProblemItemT], Field(min_length=1)]
    warnings: list[ProblemItemT] = Field(default_factory=_no_items)
    pending_signatures: list[str] = Field(default_factory=list)
    is_runnable: Literal[False] = False
    message: str | None = None


ValidationResult: TypeAlias = Annotated[
    ValidationReport[ProblemItem] | InvalidValidationReport[ProblemItem],
    Field(discriminator="is_valid"),
]
"""The `POST /validate` 200 response — discriminated on `is_valid`.

A consumer pattern-matches the one mandatory field (`is_valid`) regardless of
outcome, and never inspects a status code or catches an exception body to learn the
verdict. Non-2xx means the endpoint could not produce a verdict.
"""


class VersionInfo(BaseModel):
    """Protocol + runner versions — `GET /version` (always public).

    The handshake clients use for feature detection. The protocol defines two
    fields; implementations may add their own identification (a name, an
    underlying runtime version, anything else) as extensions.
    """

    model_config = ConfigDict(extra="allow")

    protocol_version: str
    runner_version: str | None = None
