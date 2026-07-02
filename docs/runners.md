# MTHDS protocol & runners

The `mthds` package is the Python client for the open-source `pipelex-api` runner — and, more generally, any server that speaks the [MTHDS Protocol](https://mthds.ai). One abstraction, `MTHDSProtocol`, mirrors the standard's five routes; `MthdsAPIClient` implements it over HTTP. It is **protocol-only** — the durable run lifecycle (polling a run to completion by id) is a hosted-API extension that lives in `pipelex-sdk` (`PipelexAPIClient`), built on this base.

## Package layout

The protocol contract and its implementations live in separate packages:

- `mthds/protocol/` — the MTHDS Protocol itself: `protocol.py` (the `MTHDSProtocol` interface), `models.py` (the run/discovery wire models — `RunResultExecute`, `RunResultStart`, `ModelDeck`, `ValidationReport`, `VersionInfo`), `exceptions.py` (`PipelineRequestError`), and the protocol's domain shapes — `concept.py`, `stuff.py`, `working_memory.py`, `pipe_output.py`, `pipeline_inputs.py` (the abstract, non-Dict base models the protocol is defined in terms of).
- `mthds/runners/` — every runner implementation, one subpackage per runner:
    - `api/` — the API runner: `client.py` (`MthdsAPIClient`, one file with its helpers), `models.py` (the Dict-serialized wire models — `DictStuffAbstract`, `DictWorkingMemoryAbstract`, `DictPipeOutputAbstract`, `DictRunResultExecute` — the runners' concrete JSON materialization of the protocol's domain shapes), `exceptions.py` (API auth + the protocol's 202-degrade error, `RunStillRunningError`).
    - `pipelex/runner.py` — `PipelexRunner`, the local runner that shells out to the `pipelex` CLI.
    - `types.py` — `RunnerType`.

## Configuration

One URL, one key:

| Setting | Env var / config key | Default |
| --- | --- | --- |
| API base URL (host only, no path) | `MTHDS_API_URL` | `http://localhost:8081` |
| API key | `MTHDS_API_KEY` | — |

The client composes every endpoint as `{MTHDS_API_URL}/v1/{endpoint}`. It defaults to a local `pipelex-api` runner (`http://localhost:8081`), but the same paths work against any remote MTHDS-Protocol server; server-specific extensions are detectable via the `version()` handshake. Config lives in `~/.mthds/config` (the same file the `mthds` CLI reads/writes) — keys `MTHDS_API_URL` / `MTHDS_API_KEY`.

## The protocol surface (works on any runner)

`MTHDSProtocol` has exactly five methods — `execute`, `start`, `validate`, `models`, `version`:

```python
from mthds.runners.api.client import MthdsAPIClient

async with MthdsAPIClient() as client:
    # Synchronous execution — the full output comes back in the response
    result = await client.execute(mthds_contents=[bundle_text], inputs={"topic": {"concept": "Text", "content": "owls"}})
    print(result.pipeline_run_id)                    # the protocol's two base fields...
    print(result.pipe_output)
    # anything else the server returned (run state, timestamps, output naming)
    # is an implementation extension — preserved in result.model_extra

    # Validation (dry-run included) — 200-diagnostic: read the verdict from the body
    report = await client.validate([bundle_text])
    if report.is_valid is True:
        ...                                          # ValidationReport — structural artifacts ride model_extra
    else:
        for item in report.validation_errors:        # InvalidValidationReport — neutral diagnostics
            print(item.category, item.message)       # category/message typed; locators ride item.model_extra
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
    deck = await client.models()           # optionally client.models(ModelCategory.LLM)
    info = await client.version()          # {protocol_version, runner_version} + server-specific extensions (info.model_extra)
```

`execute` may raise `RunStillRunningError` if a server answers 202 (the protocol's optional async degrade) — the run keeps executing server-side and the error carries `run_id`, `retry_after_seconds`, and `location`. `execute` answers with `RunResultExecute` (`pipeline_run_id` + `pipe_output`, both present — a completed run has output); `start` answers with `RunResultStart` (`pipeline_run_id` only). Both are extension-open on the response side.

### Basic args vs extension args

The abstract `MTHDSProtocol` interface carries the protocol's **basic** arguments only. Implementations may accept more (the protocol's extension policy), and the SDK passes any of them through:

- Extension args never appear in this SDK — not even as convenience params. They ride the generic `extra` mapping on both `execute` and `start`: `client.start(pipe_code="answer", extra={"some_server_arg": True})` merges `some_server_arg` into the request body as a top-level property. The server you call defines and handles its own extension args; consult that server's API documentation for what it accepts.
- Protocol args inside `extra` are rejected client-side with `PipelineRequestError` — pass them as named parameters.

## The durable run lifecycle (hosted API only) — lives in `pipelex-sdk`

`start` (a protocol route) returns a `pipeline_run_id` only; turning that id into a result means polling the run to completion. That **durable run lifecycle is not part of the MTHDS Protocol** — it is a hosted-API extension, so it no longer lives in this package. It is exposed by `PipelexAPIClient` in `pipelex-sdk` (`get_run_status` / `get_run_result` / `wait_for_result` / `start_and_wait`), which builds on this protocol base. A bare runner serves no run store; the SDK detects that via the `version()` handshake and falls back to a blocking `execute`.

```python
async with MthdsAPIClient() as client:
    # Submit a long run and get back its authoritative id (no output yet):
    started = await client.start(pipe_code="answer", inputs=inputs)     # POST /v1/start → 202 RunResultStart (id only)
    # server-specific args (defined by the server, not this SDK) ride `extra`:
    # started = await client.start(inputs=inputs, extra={...})
    # ...then poll it to completion via pipelex-sdk's PipelexAPIClient.
```

- `start` carries the protocol's basic args only. Anything beyond them — including a client-supplied run identifier, where a server supports one — is server-specific and rides `extra`; see the server's own documentation for the extension args it accepts. The `pipeline_run_id` returned by `start` is always the authoritative one.

## Protected extension surface (for `pipelex-sdk`)

`pipelex-sdk`'s `PipelexAPIClient` subclasses `MthdsAPIClient` to add the durable run lifecycle, the product surface, and a richer error layer on top of the protocol base. To make that cross-package coupling intentional rather than accidental, these single-underscore members are a **protected extension surface** — a subclass in `pipelex-sdk` may rely on them, and they will not be renamed or have their signatures changed without coordinating a `pipelex-sdk` release:

- `_send(method, url, *, content, request_timeout)` — issue one HTTP request, return the raw `httpx.Response` with no status interpretation (the caller decides). The reusable transport primitive every endpoint composes from.
- `_url(endpoint)` — compose `{base}/v1/{endpoint}`.
- `_build_run_body(...)` and `_build_extensions(extra, *, protocol_args=...)` (module-level) — assemble the `execute` / `start` request body and validate the generic `extra` passthrough (rejecting protocol args smuggled through it).
- `_post_validate(mthds_contents, allow_signatures, extra)` — build + send the `/validate` request and return the raw 200-diagnostic `httpx.Response`, leaving the verdict-union parse to the caller. The base's own `validate()` parses it into the neutral `ValidationResult`; `pipelex-sdk` reuses this seam to parse the same body into its Pipelex-branded narrowing.

Everything else (private methods not listed here, internal constants) is implementation detail and may change freely.

## Runners

Construct a runner directly — both implement `MTHDSProtocol`:

- `MthdsAPIClient` (`mthds.runners.api.client`) — the API runner; the MTHDS Protocol surface over HTTP (the durable run lifecycle lives in `pipelex-sdk`).
- `PipelexRunner` (`mthds.runners.pipelex.runner`) — shells out to a locally installed `pipelex` CLI (`execute` via `pipelex run`, `validate` via `pipelex validate`, `version` via `pipelex --version`; `start`/`models` raise `NotImplementedError`).
