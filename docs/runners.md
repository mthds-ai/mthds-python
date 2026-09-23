# MTHDS protocol & runners

The `mthds` package is the Python client for the open-source `pipelex-api` runner — and, more generally, any server that speaks the [MTHDS Protocol](https://mthds.ai). One abstraction, `MTHDSProtocol`, mirrors the standard's five routes; `MthdsAPIClient` implements it over HTTP. It is **protocol-only** — the durable run lifecycle (polling a run to completion by id) is a hosted-API extension that lives in `pipelex-sdk` (`PipelexAPIClient`), built on this base.

## Package layout

The protocol contract and its implementations live in separate packages:

- `mthds/protocol/` — the MTHDS Protocol itself: `protocol.py` (the `MTHDSProtocol` interface), `models.py` (the run/discovery wire models — `RunResultExecute`, `RunResultStart`, `ModelDeck`, `ValidationReport`, `VersionInfo`), `pipe_io_contracts.py` and `input_form.py` (the two validate artifacts the standard owns — see [The validate artifacts](#the-validate-artifacts-pipe_io_contracts-and-input_form) below), `method_files.py` (the catalog serialization of a stored method's source — see [The catalog serialization](#the-catalog-serialization-method_files) below), `options.py` (the run-source argument surface — see [Run sources: what may be combined](#run-sources-what-may-be-combined) below), `exceptions.py` (`PipelineRequestError`), and the protocol's domain shapes — `concept.py`, `stuff.py`, `working_memory.py`, `pipe_output.py`, `pipeline_inputs.py` (the abstract, non-Dict base models the protocol is defined in terms of).
- `mthds/runners/` — every runner implementation, one subpackage per runner:
    - `api/` — the API runner: `client.py` (`MthdsAPIClient`, one file with its helpers), `models.py` (the Dict-serialized wire models — `DictConcept`, `DictStuffAbstract`, `DictWorkingMemoryAbstract`, `DictPipeOutputAbstract`, `DictRunResultExecute` — the runners' concrete JSON materialization of the protocol's domain shapes), `exceptions.py` (API auth + the protocol's 202-degrade error, `RunStillRunningError`), `user_agent.py` (the `User-Agent` builder and `AppInfo` — see [Client identification](#client-identification-user-agent) below).
    - `pipelex/runner.py` — `PipelexRunner`, the local runner that shells out to the `pipelex` CLI.
    - `types.py` — `RunnerType`.

## Configuration

One URL, one key:

| Setting | Env var / config key | Default |
| --- | --- | --- |
| API base URL (host only, no path) | `MTHDS_BASE_URL` | `http://localhost:8081` |
| API key | `MTHDS_API_KEY` | — |

The client composes every endpoint as `{MTHDS_BASE_URL}/v1/{endpoint}`. It defaults to a local `pipelex-api` runner (`http://localhost:8081`), but the same paths work against any remote MTHDS-Protocol server; server-specific extensions are detectable via the `version()` handshake. Config lives in `~/.mthds/config` (the same file the `mthds` CLI reads/writes) — keys `MTHDS_BASE_URL` / `MTHDS_API_KEY`.

## The protocol surface (works on any runner)

`MTHDSProtocol` has exactly five methods — `execute`, `start`, `validate`, `models`, `version`:

```python
from mthds.runners.api.client import MthdsAPIClient

async with MthdsAPIClient() as client:
    # Synchronous execution — the full output comes back in the response
    result = await client.execute(mthds_contents=[bundle_text], inputs={"topic": {"concept": "Text", "content": "owls"}})
    print(result.pipeline_run_id)  # the protocol's two base fields...
    print(result.pipe_output)
    # anything else the server returned (run state, timestamps, output naming)
    # is an implementation extension — preserved in result.model_extra

    # Validation (dry-run included) — 200-diagnostic: read the verdict from the body
    report = await client.validate([bundle_text])
    if report.is_valid is True:
        ...  # ValidationReport — structural artifacts ride model_extra
    else:
        for item in report.validation_errors:  # InvalidValidationReport — neutral diagnostics
            print(item.category, item.message)  # category/message typed; locators ride item.model_extra
    # `validate()` returns the protocol-neutral ValidationResult. pipelex-sdk's PipelexAPIClient
    # narrows the same 200 body to typed PipelexValidationReport / PipelexInvalidReport (structural
    # artifacts, typed locators like `source` / `pipe_code`, `rendered_markdown`).
    # An invalid bundle is a 200 InvalidReport, NOT a 422; non-2xx (request-shape 422,
    # auth, 5xx) means no verdict could be produced and raises httpx.HTTPStatusError.
    # Server-specific extension args ride `extra` — e.g. a server may accept
    # validate(contents, extra={"mthds_sources": [...]}) to thread per-content source
    # names onto each diagnostic's `source`. The local PipelexRunner instead raises
    # PipelexRunnerError on an invalid bundle (the CLI's exit code).

    # Discovery
    deck = await client.models()  # optionally client.models(ModelCategory.LLM)
    info = await client.version()  # {protocol_version, runner_version} + server-specific extensions (info.model_extra)
```

`execute` may raise `RunStillRunningError` if a server answers 202 (the protocol's optional async degrade) — the run keeps executing server-side and the error carries `run_id`, `retry_after_seconds`, and `location`. `execute` answers with `RunResultExecute` (`pipeline_run_id` + `pipe_output`, both present — a completed run has output); `start` answers with `RunResultStart` (`pipeline_run_id` only). Both are extension-open on the response side.

The Dict wire models are extension-open at every level, matching the protocol's OpenAPI spec (which declares `pipe_output` as an open object). Base fields are typed; anything more a runner returns rides `model_extra`. The hosted `pipelex-api` runner dumps its full `PipeOutput` — per-stuff `stuff_code` / `stuff_name`, pipe-output `graph_spec` / `tokens_usages` / `working_memory_raw` and assembly errors — and all of it is preserved. A stuff's `concept` accepts both wire forms: the reduced namespaced ref string (what this SDK's own serialization emits) or the full concept object (`DictConcept`, what the hosted runner dumps); `DictStuffAbstract.concept_ref` normalizes either form to the ref string.

On the producing side the protocol's own domain shapes say the same thing, and say it once: `ConceptAbstract` carries the reference alone (`code` + `domain_code`, with `concept_ref` joining them), and `StuffAbstract` serializes its `concept` field through that property, so every dump of a stuff emits `{"concept": "<domain>.<Code>", "content": …}` without a runner having to remember to reduce it. That is the standard's rule — a concept's definition (its description, its structure, what it refines, any runtime class name) belongs to the library the method loads and never travels beside a stuff, per the "Stuffs on the Wire" section of the [CLI I/O contract](https://mthds.ai/latest/spec/cli-io-contract/). A runtime that needs more of the definition in memory declares it on its own `ConceptAbstract` subclass, where it stays out of the wire form. Two consequences are worth naming. The crate key for a concept a dependency contributes is `<package_address>::<domain>.<Code>`, and the protocol model holds no declaring package address, so producing that form is a subclass's business — it overrides `StuffAbstract.serialize_concept` under that name, since a second `field_serializer` for the field under any other name is a class-definition error and a serializer re-annotated onto the field is ignored silently. Which override point a runtime picks decides what this SDK's own output path emits, since `DictRunResultExecute.from_pipe_output` reduces a stuff by `concept_ref` rather than through the serializer: a `concept_ref` override reaches it, a `serialize_concept` override does not. And the dump is one-way: these shapes are strict, so a stuff, a working memory or a pipe output cannot be validated back from what it dumped, the definition such a parse would need being precisely what no longer travels. A consumer that re-validated a dump resolves the concept by ref through the library the method loads instead, as the input side already does; the `Dict` wire models above are the other way to read one back, since they accept either form.

### The validate artifacts: `pipe_io_contracts` and `input_form`

Two artifacts of the valid `/validate` report are owned by the standard since `mthds` v0.9.0 — [Pipe I/O Contracts](https://mthds.ai/latest/spec/pipe-io-contracts/) and the [Input-Form Descriptor](https://mthds.ai/latest/spec/input-form-descriptor/) — and this package types them: `mthds/protocol/pipe_io_contracts.py` and `mthds/protocol/input_form.py` mirror those pages exactly, snake_case slot for snake_case slot. Both are **recommended extension fields** of the report, not base fields: the protocol's base did not change, and how a caller asks a runner for the descriptor is implementation-defined (the hosted Pipelex API gates it behind its `views` request extension). They therefore arrive beside the report's typed base fields, and you narrow them by declaring them as typed fields on a model that extends the report — pydantic parses the maps and the discriminated union from the plain annotations, with no adapter machinery (this is exactly how `pipelex-sdk`'s report narrowing consumes them):

```python
from mthds.protocol.input_form import InputForm, ListField
from mthds.protocol.models import ValidationReport
from mthds.protocol.pipe_io_contracts import IOMultiplicity, PipeIOContracts


class ValidReportWithArtifacts(ValidationReport):
    """The valid arm, narrowed: the standard's two artifacts as typed fields instead of `model_extra`."""

    pipe_io_contracts: PipeIOContracts | None = None
    input_form: InputForm | None = None  # served only when the runner was asked for the view


report = await client.validate([bundle_text])
if report.is_valid is True:
    narrowed = ValidReportWithArtifacts.model_validate(report.model_dump())
    if narrowed.pipe_io_contracts is not None:
        summarize = narrowed.pipe_io_contracts["legal.summarize_contract"]
        for input_name, slot in summarize.inputs.items():  # a map — the descriptor below carries the order
            print(input_name, slot.concept_ref, slot.presence, slot.multiplicity, slot.item_count, slot.json_schema)
        print(summarize.output.concept_ref, summarize.output.multiplicity is IOMultiplicity.SINGLE, summarize.output.optional)

    if narrowed.input_form is not None:
        for field in narrowed.input_form["legal.summarize_contract"].fields:  # authored input order
            match field:
                case ListField():
                    print(field.name, "list of", field.item.kind, field.item_count)
                case _:
                    print(field.name, field.kind, field.required, field.gating)
```

What to know about the two modules:

- **They are closed shapes, unlike the report that carries them.** Every model is `extra="forbid"`: a member the standard does not define is version drift and fails the parse, where catching it is cheap. The report itself stays extension-open. The `hints` map on a field descriptor is the one exception, in content only — its shape is a strict flat map of string to string, and unknown keys and unknown intent words inside it are carried through, as the language's content-leniency rule requires.
- **The presence and multiplicity vocabularies are `StrEnum`s** — `PresenceMarker` (`plain` / `optional` / `force`, with `is_optional`) and `IOMultiplicity` (`single` / `variable` / `fixed`, with `is_plural`) — and the descriptor's closed `kind` union is `FieldKind`.
- **A field descriptor is a discriminated union, `InputFormField`,** of one model per kind (`TextField`, `ProseField`, `DateField`, `NumberField`, `BooleanField`, `EnumField`, `DocumentField`, `ImageField`, `ObjectField`, `ListField`, `UnknownField`), each carrying the common slots plus that kind's own, so a slot of another kind is rejected as an unknown member; an `object` recurses through `fields`, a `list` through `item`. Narrow a node with `match` or `isinstance`.
- **A `list`'s `item` is a different shape, not a field with a blank name.** The page gives `name` as applicable on every node except a `list`'s `item`, which "has no authored name and carries no `name` member at all" — the index labels items, and a sentinel would be a value two producers could pick differently. So `ListField.item` is an `InputFormItem`: the same closed union one layer down (`TextItem`, `ObjectItem`, …), declaring every slot but `name`. `InputFormField` is that union plus a required `name: str`, which is what `PipeInputFormDescriptor.fields` and `ObjectField.fields` hold. Both halves of the rule are therefore structural — an item carrying a `name` and a named node missing one each fail the parse, and `field.name` is a `str` you never have to narrow. The TypeScript mirror declares the same pair (`InputFormField = InputFormItem & { name: string }`).
- **The two artifacts state `item_count` differently, on purpose.** A contract always carries it, `null` off the fixed arm; a descriptor's `ListField` carries it exactly on a fixed `[N]` slot and omits it otherwise. The descriptor models own that rule — an inapplicable slot is dropped at serialization, so a plain `model_dump()` reproduces the wire and you never need `exclude_none` (which would strip the contract's `null`).
- **The models describe themselves in serialization mode too.** The serializer that drops the inapplicable slots publishes no return schema of its own, so `model_json_schema(mode="serialization")` is identical to the validation one: every per-kind arm keeps its properties, its `kind` const and its closed shape. A server that embeds these models in a response model — FastAPI, and the OpenAPI artifact it generates in serialization mode — therefore publishes the per-kind field shapes rather than an opaque object behind the discriminator.
- **Parity with the TypeScript client is measured.** `tests/fixtures/protocol/` holds one real payload pair from the reference engine, committed byte-for-byte here and in `mthds-js`; the suite parses it strictly and asserts the dump equals the input. The fixture's README records the capture and the known engine drift the standard has since ruled on.
- **The descriptor projects to a fill-in inputs template, client-side.** `mthds.protocol.inputs_template` turns one `PipeInputFormDescriptor` into the template somebody fills in and hands back — the compact and explicit shapes, as JSON or as TOML — so a client needs no server round trip to offer one for a method it does not have on disk. It is held to byte identity with the twin projection in the `mthds` npm package. See [docs/inputs-template.md](./inputs-template.md).

### The catalog serialization: `method_files`

A stored method's source is persisted by the hosted platform as one string in the **catalog** form — the JSON `[{ name, content }]` array the webapp editor writes, one entry per bundle-relative file, for the method's `.mthds` source and again for its custom PipeFunc `python`. `mthds.protocol.method_files` is the one Python definition of that form: `MethodFile` (`name` + `content`, a closed strict shape) and the pair `serialize_method_files` / `parse_method_files` between a list of them and the stored string. It mirrors `protocol/method_files.ts` in the `mthds` npm package, so a client that fetches a stored method and wants its bundle back — an MCP server, your own code — reads it here instead of re-porting the platform's decoder. That is what the module is for, not yet a description of every consumer: `pipelex-sdk` still carries its own copy of this format, which disagrees with this one on blankness and on bytes, and moving it across is tracked as ledger item L-260912-6ef508.

```python
from mthds.protocol.method_files import MethodFile, parse_method_files, serialize_method_files

files = parse_method_files(stored_method["mthds"])  # -> list[MethodFile], in stored order; "" and "[]" both give []
for method_file in files:
    print(method_file.name, len(method_file.content))

stored = serialize_method_files([MethodFile(name="bundle.mthds", content=bundle_text)])  # -> the catalog string
```

What to know about it:

- **It is the at-rest representation, not the run surface.** The catalog is an ordered, named array; a run request's `files` is an unordered path-to-text map. They are different shapes for different moments, and this module owns only the first.
- **No files is `""`, never `"[]"`.** The empty string is the platform's "no source" / "clear the field" sentinel, so the empty list serializes to it; the literal `"[]"` would be stored as a source. On the way back, a blank string, `None` and the empty array all parse to `[]`.
- **A blank file is not a file.** An entry whose content is empty or whitespace-only is dropped on both directions, so the round-trip is stable and the canonical form never carries an empty file. "Whitespace" here is what ECMAScript's `trim` strips — the byte-order mark included, U+001C–U+001F and U+0085 excluded — because the twin's verdict on a file must be this side's, and Python's `str.isspace` disagrees at both ends. One test derives that set from the Unicode categories rather than sampling it, so a code point cannot quietly go missing. Note that a zero-byte file is therefore not representable: an empty `__init__.py` does not survive a round trip.
- **The bytes are the twin's.** Serialization writes what `JSON.stringify` writes: compact separators, UTF-8 left as is, and only the JSON-mandated escapes. Surrogates take two rules, because Python addresses code points where JavaScript addresses UTF-16 code units: an unpaired surrogate is escaped rather than written raw — `ensure_ascii=False` alone would produce a string that cannot be encoded as UTF-8 at all — while two adjacent halves of a pair, which Python can hold as two code points and the twin cannot, are combined into the astral character the twin writes. The suite pins both against strings the twin printed.
- **Anything but the named array is a contract violation.** A source that is not JSON — a legacy raw bundle string included — a non-array value, an entry that is not an object with string `name` and string `content`, one of the three constants Python's `json` accepts and `JSON.parse` refuses (`NaN`, `Infinity`, `-Infinity`, an ignored extra member included) all raise `PipelineRequestError`. An entry's extra members are tolerated and stripped; a blank name is not a reason to drop an entry; duplicate names are kept, and since the platform refuses a method whose file names collide, uniqueness is the producer's obligation. An oversized integer is *not* a violation: Python's bounded `int()` conversion would refuse bytes the twin accepts, so integers are decoded as floats, which is the twin's own number model.
- **Deep nesting is the one place the two sides differ, and not by choice.** A source nested deeply enough to exhaust Python's recursive decoder raises `PipelineRequestError` rather than letting a `RecursionError` escape the typed surface — but the twin's `JSON.parse` is iterative and accepts any depth, so this side refuses what the twin accepts. The depth that trips it is an interpreter build constant: it rose by an order of magnitude in CPython 3.14 and differs between patch releases, so treat the guard as best-effort and never as a depth you can rely on.
- **A `name` is untrusted text.** Neither this module nor the twin checks that it is really bundle-relative, so an absolute or `..`-walking name round-trips untouched. Validate containment before writing a catalog to disk.
- **Where it departs from the platform's own decoder, it follows the twin.** The platform has no blank-source guard on its contents path at all, so a whitespace-only raw source fails downstream at the TOML parse; its own blankness is Python's `str.strip()`, which disagrees with the twin in both directions on an entry's content (a BOM-only file is content there and blank here, a U+001C–U+001F or U+0085 file the reverse); it drops blank-named entries; and it reads a non-array source — or a whole array containing one malformed entry — as a single legacy bundle, while silently dropping an entry whose content is not a string. This module and the TypeScript twin agree with each other on every one of those instead, so the three implementations never split two against one. **This package does not decode the legacy bare-bundle shape**, so a consumer reading one of the platform's very old plain-string rows must handle the `PipelineRequestError` itself — the example above assumes a catalog-form row.

### Basic args vs extension args

The abstract `MTHDSProtocol` interface carries the protocol's **basic** arguments only. Implementations may accept more (the protocol's extension policy), and the SDK passes any of them through:

- Extension args never appear in this SDK — not even as convenience params. They ride the generic `extra` mapping on both `execute` and `start`: `client.start(pipe_code="answer", extra={"some_server_arg": True})` merges `some_server_arg` into the request body as a top-level property. The server you call defines and handles its own extension args; consult that server's API documentation for what it accepts.
- Protocol args inside `extra` are rejected client-side with `PipelineRequestError` — pass them as named parameters.

### Run sources: what may be combined

A run request has to name something to run, and several of the ways to name it exclude each other. That rule is an invariant of the request itself rather than of any one runner, so it lives in `mthds.protocol.options` for any Python client to enforce from one place instead of re-deriving it. **The definitions are there; no client enforces from them yet** — see "What is actually wired" below. The module is the twin of `mthds-js/src/protocol/options.ts`, whose two exported predicates it matches message for message; it is **not** a twin of either server, so a rejection here can read differently from the 422 it pre-empts (`pipelex-api` and the hosted platform each word these refusals their own way, and the platform checks the two exclusivity arms in the opposite order — `pipelex-api` has no two-encodings check at all).

Three layers of argument meet in it: the protocol's own source (`pipe_code`, `mthds_contents`), the pipelex-api extensions that carry a whole method bundle (`files`, `bundle_b64`) or its published address (`method_ref`), and the hosted platform's catalog id (`method_id`). Only the first layer is a named parameter of `execute` / `start`; the others ride `extra` here, and are named parameters on a client that types its own stack's arguments.

| Function | What it decides |
| --- | --- |
| `assert_exclusive_run_sources` | A bundle is self-contained, so it cannot be combined with `mthds_contents`, and `files` / `bundle_b64` are two encodings of one bundle. Keys off **presence** (`files={}` beside a zip is still two encodings), while `mthds_contents` counts only when non-empty. |
| `has_bundle_payload` | Whether a **runnable** bundle is present — an empty map or string carries no method, so it satisfies nothing. |
| `assert_method_ref_pairs_with_nothing` | A `method_ref` is a complete run source: exclusive with `mthds_contents`, with a bundle encoding, and with `method_id`. `pipe_code` beside it is legal (it overrides the fetched manifest's `main_pipe`), and inline source + `method_id` stays legal (the inline source runs, the id becomes run-history linkage). |
| `normalized_selector` / `run_selector_extensions` | The boundary normalization a selector goes through: a non-string is refused rather than silently dropped or forwarded to a server 422, and an absent or empty selector contributes nothing. |

#### What is actually wired

The table above describes the predicates, not a guarantee any client makes: **nothing in this package calls them.** `MthdsAPIClient.execute` / `start` check only that something to run was named — a pipe, inline contents, or any extension arg — and forward the keys inside `extra` without interpreting them. That is the client's documented contract: it serves any MTHDS-compliant runner, and which extension arg names a run source is that runner's to define. So an illegal combination sent through `extra` still reaches the server and comes back as its own 422, exactly as it did before this module existed.

The predicates are there for a client that takes these arguments by name, which is where the combination is knowable before the request leaves. `PipelexAPIClient` in `pipelex-sdk` is the first such client; it still carries its own private copies and pins an older `mthds`, so replacing them waits on a release that ships this module. Which layer should enforce the extension rules — the generic client here, the client that names the arguments, or a Pipelex-scoped module beside this one — is still an open question, and the `pipe-selector` campaign will change this same surface after it is settled.

## The durable run lifecycle (hosted API only) — lives in `pipelex-sdk`

`start` (a protocol route) returns a `pipeline_run_id` only; turning that id into a result means polling the run to completion. That **durable run lifecycle is not part of the MTHDS Protocol** — it is a hosted-API extension, so it no longer lives in this package. It is exposed by `PipelexAPIClient` in `pipelex-sdk` (`get_run_status` / `get_run_result` / `wait_for_result` / `start_and_wait`), which builds on this protocol base. A bare runner serves no run store; the SDK detects that via the `version()` handshake and falls back to a blocking `execute`.

```python
async with MthdsAPIClient() as client:
    # Submit a long run and get back its authoritative id (no output yet):
    started = await client.start(pipe_code="answer", inputs=inputs)  # POST /v1/start → 202 RunResultStart (id only)
    # server-specific args (defined by the server, not this SDK) ride `extra`:
    # started = await client.start(inputs=inputs, extra={...})
    # ...then poll it to completion via pipelex-sdk's PipelexAPIClient.
```

- `start` carries the protocol's basic args only. Anything beyond them — including a client-supplied run identifier, where a server supports one — is server-specific and rides `extra`; see the server's own documentation for the extension args it accepts. The `pipeline_run_id` returned by `start` is always the authoritative one.

## Client identification (`User-Agent`)

Every request `MthdsAPIClient` sends carries a `User-Agent` built from RFC 9110 product tokens, outermost first, as the workspace spec `docs/specs/client-identification.md` fixes for every first-party client:

```
[<app_info>] mthds-python/<package version> python/<major.minor.micro> (<os>; <arch>)
```

The library's own token is `mthds-python` (the repo name, since the npm twin is also published as `mthds`) followed by `mthds.version.__version__`, which is read from the installed distribution rather than typed by hand. The runtime token closes the value, with `<os>` from `platform.system().lower()` and `<arch>` from `platform.machine()`. The value is computed once at construction, stored on `client.user_agent`, and set both as a default header of the `httpx.AsyncClient` and on every request `_send` issues, so no request path can miss it. The header is self-declared: the hosted platform uses it for analytics and diagnostics only, never for authorization, and it must never carry a secret, a user identifier, an email or a hostname.

An integrator names itself with `app_info`, shaped like Stripe's `appInfo`:

```python
from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.user_agent import AppInfo

client = MthdsAPIClient(app_info=AppInfo(name="acme-invoicer", version="1.4.0", url="https://acme.example", details=("batch",)))
# User-Agent: acme-invoicer/1.4.0 (batch; +https://acme.example) mthds-python/0.15.0 python/3.12.4 (linux; x86_64)
```

`name` is required and, like `version`, must be an RFC 9110 token; each `details` entry is a `token` or `token=value` comment parameter; `url` must be visible ASCII with no whitespace, parenthesis, semicolon or backslash and renders last in the comment as `+url`; an empty `version` or `url` counts as absent. An invalid field raises `ValueError` when the `AppInfo` is built, and a header over 512 characters raises `ValueError` when the client is built; nothing is silently dropped or rewritten.

The helpers live in `mthds.runners.api.user_agent`: `AppInfo`, `product_token(name, version)`, `render_app_info(app_info)`, `mthds_python_token()`, `runtime_token()` and `build_user_agent(app_info, sdk_tokens)`.

## Protected extension surface (for `pipelex-sdk`)

`pipelex-sdk`'s `PipelexAPIClient` subclasses `MthdsAPIClient` to add the durable run lifecycle, the product surface, and a richer error layer on top of the protocol base. To make that cross-package coupling intentional rather than accidental, these single-underscore members are a **protected extension surface** — a subclass in `pipelex-sdk` may rely on them, and they will not be renamed or have their signatures changed without coordinating a `pipelex-sdk` release:

- `_send(method, url, *, content, request_timeout)` — issue one HTTP request, return the raw `httpx.Response` with no status interpretation (the caller decides). The reusable transport primitive every endpoint composes from.
- `_url(endpoint)` — compose `{base}/v1/{endpoint}`.
- `_build_run_body(...)` and `_build_extensions(extra, *, protocol_args=...)` (module-level) — assemble the `execute` / `start` request body and validate the generic `extra` passthrough (rejecting protocol args smuggled through it).
- `user_agent_sdk_tokens()` (a classmethod) and `init_user_agent(app_info)` — the client-identification seam. A subclass on the same transport overrides `user_agent_sdk_tokens` to prepend its own token and keep the base's, `return (product_token("pipelex-sdk-python", __version__), *super().user_agent_sdk_tokens())`, and a subclass whose `__init__` does not call `super().__init__()` calls `self.init_user_agent(app_info)` from it, which sets `self.app_info` and `self.user_agent`. A subclass that overrides `start_client` should put `self.user_agent` in its default headers; `_send` sets it per request regardless.
- `_post_validate(mthds_contents, allow_signatures, extra)` — build + send the `/validate` request and return the raw 200-diagnostic `httpx.Response`, leaving the verdict-union parse to the caller. The base's own `validate()` parses it into the neutral `ValidationResult`; `pipelex-sdk` reuses this seam to parse the same body into its Pipelex-branded narrowing.

Everything else (private methods not listed here, internal constants) is implementation detail and may change freely.

## Runners

Construct a runner directly — both implement `MTHDSProtocol`:

- `MthdsAPIClient` (`mthds.runners.api.client`) — the API runner; the MTHDS Protocol surface over HTTP (the durable run lifecycle lives in `pipelex-sdk`).
- `PipelexRunner` (`mthds.runners.pipelex.runner`) — shells out to a locally installed `pipelex` CLI (`execute` via `pipelex run`, `validate` via `pipelex validate`, `version` via `pipelex --version`; `start`/`models` raise `NotImplementedError`).
