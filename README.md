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

The default runner is `api`. To use it, configure your Pipelex API credentials:

```bash
mthds config set api-key YOUR_KEY
mthds config set api-url https://your-api-instance.com
```

Credentials are stored in `~/.mthds/credentials` and shared between mthds-python and mthds-js.

You can also use environment variables, which take precedence over the credentials file:

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPELEX_API_KEY` | API authentication key | (empty) |
| `PIPELEX_API_URL` | API base URL | `https://api.pipelex.com` |
| `MTHDS_RUNNER` | Default runner (`api` or `pipelex`) | `api` |

See `mthds config list` to view all current settings and their sources.

For the full CLI reference, see [CLI.md](./CLI.md).
