# mthds

The Python implementation of the [MTHDS Protocol](https://mthds.ai) — a typed client for any MTHDS runner, plus the base structures that methods are defined in.

Learn more at [mthds.ai](https://mthds.ai) and browse the Hub at [mthds.sh](https://mthds.sh).

> Looking for the command line? The `mthds` **CLI** ships as the [npm package](https://www.npmjs.com/package/mthds) (mthds-js). This Python package is a **library** — it has no CLI.

## Installation

```bash
pip install mthds
```

## What's in the box

- **The protocol** (`mthds.protocol`) — `MTHDSProtocol`, the five-route interface every runner implements (`execute`, `start`, `validate`, `models`, `version`); the wire models (`RunResult`, `ModelDeck`, `ValidationReport`, `VersionInfo`); and the domain shapes methods are built from (`concept`, `stuff`, `working_memory`, `pipe_output`, `pipeline_inputs`).
- **Runners** (`mthds.runners`) — `MthdsAPIClient` (`mthds.runners.api.client`), the HTTP client for any MTHDS-Protocol server plus the hosted run-lifecycle (polling) extension; and `PipelexRunner` (`mthds.runners.pipelex.runner`), which shells out to a locally installed `pipelex` CLI.
- **Package management** (`mthds.package`) — read, lock, and resolve `METHODS.toml` manifests.

See [docs/runners.md](./docs/runners.md) for the protocol + runners reference.

## Quick start

Run a method against any MTHDS-Protocol server with the **API runner**, `MthdsAPIClient`:

```python
import asyncio

from mthds.runners.api.client import MthdsAPIClient


async def main() -> None:
    async with MthdsAPIClient() as client:
        # Discovery handshake
        version = await client.version()
        print(version.protocol_version)

        # Run a method and wait for the result — start → poll → result in one call
        result = await client.start_and_wait(pipe_code="my_pipe", inputs={"topic": "owls"})
        print(result.main_stuff)


asyncio.run(main())
```

`execute` runs synchronously; `start` returns immediately with a `pipeline_run_id`; `start_and_wait` does the whole async lifecycle in one call. `validate`, `models`, and `version` round out the protocol surface.

Need local execution instead of an API? `PipelexRunner` (`mthds.runners.pipelex.runner`) implements the same `MTHDSProtocol` by shelling out to an installed `pipelex` CLI — no API key.

## Configuration

`MthdsAPIClient()` reads its config from `~/.mthds/config` — the same file the `mthds` CLI (npm) reads and writes, so configuring either configures both. Environment variables take precedence:

| Variable | Description | Default |
|----------|-------------|---------|
| `MTHDS_API_KEY` | API authentication key | (empty) |
| `MTHDS_BASE_URL` | API base URL — any [MTHDS Protocol](https://mthds.ai) server | `http://localhost:8081` |

This client targets the open-source **`pipelex-api`** runner, so it defaults to a local instance (`http://localhost:8081`, `pipelex-api`'s default port). Point `MTHDS_BASE_URL` at any other MTHDS-Protocol server to use it instead. You can also pass `api_key` / `base_url` straight to `MthdsAPIClient(...)`.

To set the config from a terminal, use the npm CLI (`mthds config set api-key …`) or edit `~/.mthds/config` directly.

## Related packages

- [`mthds`](https://www.npmjs.com/package/mthds) (npm) — the `mthds` CLI (install methods, run, configure) + TypeScript client.
- [Pipelex](https://github.com/Pipelex/pipelex) — the reference full-featured runner.
