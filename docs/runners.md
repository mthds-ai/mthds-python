# MTHDS protocol & runners

The `mthds` package is the Python client of any MTHDS runner: the hosted MTHDS API (`api.pipelex.com`) or a self-hosted `pipelex-api` instance. One abstraction, `MTHDSProtocol`, mirrors the five routes of the [MTHDS Protocol](https://mthds.ai) standard; `MthdsAPIClient` implements it over HTTP and adds the hosted run-lifecycle extension.

## Package layout

The protocol contract and its implementations live in separate packages:

- `mthds/protocol/` — the MTHDS Protocol itself, nothing else: `protocol.py` (the `MTHDSProtocol` interface), `models.py` (the wire models mirroring `mthds-protocol.openapi.yaml`), `exceptions.py` (`PipelineRequestError`).
- `mthds/runners/` — every runner implementation: `api_runner.py` (`MthdsAPIClient` — the API runner, one file with its helpers), `pipelex_runner.py` (the local CLI runner), `registry.py` (`create_runner`), plus the runner-side support modules (`results.py` for the concrete Dict responses, `runs.py` for the hosted run-lifecycle models, `exceptions.py` for runner errors).

## Configuration

One URL, one key:

| Setting | Env var / config key | Default |
| --- | --- | --- |
| API base URL (host only, no path) | `MTHDS_API_URL` | `https://api.pipelex.com` |
| API key | `MTHDS_API_KEY` | — |

The client composes every endpoint as `{MTHDS_API_URL}/v1/{endpoint}`. The same paths work against the hosted API and a bare runner (`http://localhost:8081`); hosted-only extensions are detectable via the `version()` handshake. Credentials live in `~/.mthds/config` (the same file the `mthds` CLI reads/writes) — keys `MTHDS_API_URL` / `MTHDS_API_KEY`.

## The protocol surface (works on any runner)

`MTHDSProtocol` has exactly five methods — `execute`, `start`, `validate`, `models`, `version`:

```python
from mthds.runners.api_runner import MthdsAPIClient

async with MthdsAPIClient() as client:
    # Synchronous execution — the full output comes back in the response
    result = await client.execute(mthds_contents=[bundle_text], inputs={"topic": {"concept": "Text", "content": "owls"}})
    print(result.pipeline_run_id)                    # the protocol's two base fields...
    print(result.pipe_output)
    # anything else the server returned (run state, timestamps, output naming)
    # is an implementation extension — preserved in result.model_extra

    # Validation (dry-run included); raises on an invalid bundle (HTTP 422 problem)
    report = await client.validate([bundle_text])

    # Discovery
    deck = await client.models()           # optionally client.models(ModelCategory.LLM)
    info = await client.version()          # {protocol_version, runner_version} + server-specific extensions (info.model_extra)
```

`execute` may raise `RunStillRunningError` if a server answers 202 (the protocol's optional async degrade) — the run keeps executing server-side and the error carries `run_id`, `retry_after_seconds`, and `location`. Both `execute` and `start` answer with the protocol's single `RunResult`: `pipeline_run_id` (mandatory, server-generated, authoritative) + `pipe_output` (present on a completed `execute`, absent on `start`), extension-open on the response side.

### Basic args vs extension args

The abstract `MTHDSProtocol` interface carries the protocol's **basic** arguments only. Implementations may accept more (the protocol's extension policy), and the SDK passes any of them through:

- Extension args never appear in this SDK — not even as convenience params. They ride the generic `extra` mapping on both `execute` and `start`: `client.start(pipe_code="answer", extra={"some_server_arg": True})` merges `some_server_arg` into the request body as a top-level property. The server you call defines and handles its own extension args; consult that server's API documentation for what it accepts.
- Protocol args inside `extra` are rejected client-side with `PipelineRequestError` — pass them as named parameters.

## The run-lifecycle extension (hosted API only)

`start` + polling is how long runs survive the hosted gateway's ~30s synchronous cap. **Polling is not part of the MTHDS Protocol** — it is a hosted extension; a bare runner 404s these routes and the client raises `RunLifecycleUnavailableError`.

```python
async with MthdsAPIClient() as client:
    # One call for the whole lifecycle — start, poll, return the results:
    results = await client.start_and_wait(pipe_code="answer", inputs=inputs)
    print(results.main_stuff)

    # Or step by step:
    ack = await client.start(pipe_code="answer", inputs=inputs)         # POST /v1/start → 202 (pipe_output absent)
    # server-specific args (defined by the server, not this SDK) ride `extra`:
    # ack = await client.start(inputs=inputs, extra={...})
    status = await client.get_run_status(ack.pipeline_run_id)                   # GET /v1/runs/{id}/status (self-healing)
    results = await client.wait_for_result(ack.pipeline_run_id)                 # polls GET /v1/runs/{id}/results
```

- `start` carries the protocol's basic args only. Anything beyond them — including a client-supplied run identifier, where a server supports one — is server-specific and rides `extra`; see the server's own documentation for the extension args it accepts. The `pipeline_run_id` returned by `start` is always the authoritative one.
- `wait_for_result` resolves on `COMPLETED`, raises `RunFailedError` on any other terminal status, `RunTimeoutError` when its budget elapses (the run keeps executing — resume by id), and honors the server's `Retry-After`.

## Runners

`create_runner` returns an `MTHDSProtocol` implementation:

- `RunnerType.API` → the `MthdsAPIClient` itself.
- `RunnerType.PIPELEX` → `PipelexRunner`, which shells out to a locally installed `pipelex` CLI (`execute` via `pipelex run`, `validate` via `pipelex validate`, `version` via `pipelex --version`; `start`/`models` raise `NotImplementedError`). Falls back to the API client when `pipelex` is not on PATH.

## Runnable example

`examples/run_lifecycle_demo.py` exercises the whole lifecycle against the hosted API — `version`, start & wait, start-only, poll-by-id, and a single-shot get — over the `examples/invoice_reimbursement.mthds` batch method. Configure your key (`mthds config set api-key …`) and run `python examples/run_lifecycle_demo.py`.
