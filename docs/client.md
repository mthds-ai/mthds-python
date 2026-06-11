# MTHDS Python client

The `mthds` package is the Python client of any MTHDS runner: the hosted MTHDS API (`api.pipelex.com`) or a self-hosted `pipelex-api` instance. One abstraction, `MTHDSProtocol`, mirrors the five routes of the [MTHDS Protocol](https://mthds.ai) standard; `MthdsAPIClient` implements it over HTTP and adds the hosted run-lifecycle extension.

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
from mthds.client.client import MthdsAPIClient

async with MthdsAPIClient() as client:
    # Synchronous execution — the full output comes back in the response
    result = await client.execute(mthds_contents=[bundle_text], inputs={"topic": {"concept": "Text", "content": "owls"}})
    print(result.pipeline_run_id, result.state, result.main_stuff_name)

    # Validation (dry-run included); raises on an invalid bundle (HTTP 422 problem)
    report = await client.validate([bundle_text])

    # Discovery
    deck = await client.models()           # optionally client.models(ModelCategory.LLM)
    info = await client.version()          # {protocol_version, implementation, implementation_version, runtime_version}
```

`execute` may raise `RunStillRunningError` if a server answers `202 + StartAck` (the protocol's optional async degrade) — the run keeps executing server-side and the error carries `run_id`, `retry_after_seconds`, and `location`.

### Basic args vs extension args

The abstract `MTHDSProtocol` interface carries the protocol's **basic** arguments only. Implementations may accept more (the protocol's extension policy), and the SDK passes any of them through:

- The concrete `MthdsAPIClient` exposes the common pipelex extensions as typed convenience params: `method_id` (on `execute` and `start`) and `callback_urls` (on `start`).
- Anything else rides the generic `extra` mapping on both `execute` and `start`: `client.start(pipe_code="answer", extra={"some_vendor_arg": True})` merges `some_vendor_arg` into the request body as a top-level property. Protocol args inside `extra` are rejected client-side with `PipelineRequestError` — pass them as named parameters.

## The run-lifecycle extension (hosted API only)

`start` + polling is how long runs survive the hosted gateway's ~30s synchronous cap. **Polling is not part of the MTHDS Protocol** — it is a hosted extension; a bare runner 404s these routes and the client raises `RunLifecycleUnavailableError`.

```python
async with MthdsAPIClient() as client:
    ack = await client.start(method_id="mt_123", inputs=inputs)        # POST /v1/start → 202 StartAck
    status = await client.get_run_status(ack.pipeline_run_id)                   # GET /v1/runs/{id}/status (self-healing)
    results = await client.wait_for_result(ack.pipeline_run_id)                 # polls GET /v1/runs/{id}/results
    print(results.main_stuff)
```

- `start` accepts the protocol arg `pipeline_run_id` (bare-runner only: the hosted API always generates the id server-side and rejects a client-supplied one with 422), plus the **pipelex extension args** `method_id` (a stored method in your org's catalog; combinable with `mthds_contents`: the inline contents run, `method_id` links run history) and `callback_urls` (HMAC-signed completion webhooks). Neither extension is part of the MTHDS Protocol — they are server-specific args the concrete client exposes for convenience.
- `wait_for_result` resolves on `COMPLETED`, raises `RunFailedError` on any other terminal status, `RunTimeoutError` when its budget elapses (the run keeps executing — resume by id), and honors the server's `Retry-After`.

## Runners

`create_runner` returns an `MTHDSProtocol` implementation:

- `RunnerType.API` → the `MthdsAPIClient` itself.
- `RunnerType.PIPELEX` → `PipelexRunner`, which shells out to a locally installed `pipelex` CLI (`execute` via `pipelex run`, `validate` via `pipelex validate`, `version` via `pipelex --version`; `start`/`models` raise `NotImplementedError`). Falls back to the API client when `pipelex` is not on PATH.

## Runnable example

`examples/run_lifecycle_demo.py` exercises the whole lifecycle against the hosted API — `version`, start & wait, start-only, poll-by-id, and a single-shot get — over the `examples/invoice_reimbursement.mthds` batch method. Configure your key (`mthds config set api-key …`) and run `python examples/run_lifecycle_demo.py`.
