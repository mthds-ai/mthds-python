# mthds

The Python interface for methods — base structures for structured outputs and the base runner for executing methods via API.

Learn more at [mthds.ai](https://mthds.ai) and browse the Hub at [mthds.sh](https://mthds.sh).

## Runners

This package provides the base structures that define methods and their structured outputs, as well as the base runner that executes methods through API calls. Other runners have been implemented on top of it:

- [Pipelex](https://github.com/Pipelex/pipelex) — a full-featured runner

## Related packages

- [`mthds`](https://www.npmjs.com/package/mthds) (npm) — **CLI to install methods** + light client

## Installation

```bash
pip install mthds
```

## Quick Start

```bash
# Configure the API runner (default)
mthds config set api-key YOUR_KEY
mthds config set api-url https://your-api-instance.com

# Run a pipe
mthds run my_pipe_code

# Validate the manifest
mthds validate

# Initialize a new package
mthds package init
```

## API Configuration

The default runner is `api` — any server that implements the [MTHDS Protocol](https://mthds.ai). The reference implementation is **Pipelex** (`https://api.pipelex.com`): get an API key at [app.pipelex.com](https://app.pipelex.com).

```bash
mthds config set api-key YOUR_KEY
mthds config set api-url https://api.pipelex.com   # or your own MTHDS-Protocol server
```

Credentials are stored in `~/.mthds/config` and shared between mthds-python and mthds-js.

You can also use environment variables, which take precedence over the config file:

| Variable | Description | Default |
|----------|-------------|---------|
| `MTHDS_API_KEY` | API authentication key | (empty) |
| `MTHDS_API_URL` | API base URL | `https://api.pipelex.com` |
| `MTHDS_RUNNER` | Default runner (`api` or `pipelex`) | `api` |

Configuration lives in `~/.mthds/config` (the same file the `mthds` CLI reads/writes). See `mthds config list` to view all current settings and their sources.

For the full CLI reference, see [CLI.md](./CLI.md).
