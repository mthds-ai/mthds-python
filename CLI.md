# MTHDS CLI Reference (Python)

Command-line interface for the [mthds.ai](https://mthds.ai) open standard. Manage packages, configure credentials, and run pipelines.

## Installation

```bash
# With pip
pip install mthds

# With uv
uv pip install mthds

# For development
pip install -e ".[dev]"
```

After installation the `mthds` command is available on your PATH.

## Quick Start

```bash
# Initialize a new package
mthds package init

# Validate the manifest
mthds validate

# Configure your API key
mthds config set api-key YOUR_KEY

# Run a pipe
mthds run my_pipe_code
```

## Global Options

| Option | Description |
|---|---|
| `-V, --version` | Print the CLI version and exit |
| `--help` | Show help for any command |

Runner selection (`--runner`) and directory targeting (`--directory`) are available per-command.

---

## Run

Execute a pipe via a runner (pipelex subprocess or MTHDS API).

### `mthds run`

```bash
mthds run <target> [OPTIONS] [EXTRA_ARGS...]
```

| Argument / Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `target` | string | yes | -- | `.mthds` file path or pipe code to execute |
| `--inputs`, `-i` | string | no | `None` | Path to a JSON file containing inputs |
| `--inputs-json` | string | no | `None` | Inline JSON string with inputs |
| `--runner`, `-r` | string | no | auto-detect | Runner to use: `pipelex` or `api` |
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |
| `EXTRA_ARGS` | string[] | no | -- | Additional arguments passed through to the runner |

When `--runner` is omitted, the CLI uses the runner configured via `mthds config set runner <name>` (default: `api`).

**Examples:**

```bash
# Run by pipe code using the default runner
mthds run my_pipe_code

# Run a .mthds bundle file
mthds run ./path/to/bundle.mthds

# Run with inputs from a JSON file
mthds run my_pipe_code --inputs inputs.json

# Run with inline JSON inputs
mthds run my_pipe_code --inputs-json '{"topic": "climate"}'

# Run with a specific runner
mthds run my_pipe_code --runner pipelex
```

---

## Validate

Validate the `METHODS.toml` manifest and optionally delegate deeper validation to a runner.

### `mthds validate`

```bash
mthds validate [TARGET] [OPTIONS] [EXTRA_ARGS...]
```

| Argument / Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `target` | string | no | `None` | Pipe code or `.mthds` file path (for runner validation) |
| `--all`, `-a` | bool | no | `False` | Validate all pipes via the runner |
| `--runner`, `-r` | string | no | `None` | Runner for deeper validation (e.g. `pipelex`) |
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |
| `EXTRA_ARGS` | string[] | no | -- | Additional arguments passed through to the runner |

Without `--runner`, only the `METHODS.toml` manifest structure is validated. With `--runner pipelex`, validation is delegated to the pipelex CLI subprocess for deeper checks.

**Examples:**

```bash
# Validate the METHODS.toml manifest only
mthds validate

# Validate a specific pipe via pipelex
mthds validate my_pipe_code --runner pipelex

# Validate all pipes via pipelex
mthds validate --all --runner pipelex
```

---

## Build

Build pipes, runners, inputs, and outputs. Build operations delegate to the pipelex runner. The API runner does not support build operations.

### `mthds build pipe`

Build a pipe from a brief natural-language description.

```bash
mthds build pipe <brief>
```

| Argument | Type | Required | Description |
|---|---|---|---|
| `brief` | string | yes | Brief description of the pipe to build |
| `--directory`, `-d` | string | no | Target package directory (defaults to current directory) |

**Example:**

```bash
mthds build pipe "Extract key facts from a news article"
```

### `mthds build runner`

Build a runner configuration for a target.

```bash
mthds build runner <target>
```

| Argument | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | Target runner to build for |
| `--directory`, `-d` | string | no | Target package directory (defaults to current directory) |

**Example:**

```bash
mthds build runner pipelex
```

### `mthds build inputs`

Build inputs for a specific pipe.

```bash
mthds build inputs <target> <pipe_code>
```

| Argument | Type | Required | Description |
|---|---|---|---|
| `target` | string | yes | Target runner |
| `pipe_code` | string | yes | Pipe code to build inputs for |
| `--directory`, `-d` | string | no | Target package directory (defaults to current directory) |

**Example:**

```bash
mthds build inputs pipelex my_pipe_code
```

### `mthds build output`

Build output configuration for a specific pipe.

```bash
mthds build output <target> <pipe_code> [OPTIONS]
```

| Argument / Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `target` | string | yes | -- | Target runner |
| `pipe_code` | string | yes | -- | Pipe code to build output for |
| `--format`, `-f` | string | no | `json` | Output format |
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |

**Example:**

```bash
mthds build output pipelex my_pipe_code --format json
```

---

## Config

Manage MTHDS configuration and credentials stored in `~/.mthds/credentials`.

Configuration values are resolved in this order: **environment variables > credentials file > defaults**.

### Valid Configuration Keys

| Key | Environment Variable | Default | Description |
|---|---|---|---|
| `runner` | `MTHDS_RUNNER` | `api` | Default runner (`api` or `pipelex`) |
| `api-url` | `PIPELEX_API_URL` | `https://api.pipelex.com` | MTHDS API base URL |
| `api-key` | `PIPELEX_API_KEY` | (empty) | API authentication key |
| `telemetry` | `DISABLE_TELEMETRY` | `0` | Set to `1` to disable telemetry |

### `mthds config set`

Set a configuration value.

```bash
mthds config set <key> <value>
```

| Argument | Type | Required | Description |
|---|---|---|---|
| `key` | string | yes | Configuration key (e.g. `api-key`, `runner`, `api-url`, `telemetry`) |
| `value` | string | yes | Value to set |

**Examples:**

```bash
mthds config set api-key sk-my-api-key
mthds config set runner pipelex
mthds config set telemetry 1
```

### `mthds config get`

Get a configuration value and its source.

```bash
mthds config get <key>
```

| Argument | Type | Required | Description |
|---|---|---|---|
| `key` | string | yes | Configuration key |

**Example:**

```bash
mthds config get runner
# runner = api  (source: default)
```

### `mthds config list`

List all configuration values with their sources.

```bash
mthds config list
```

Displays a table with all keys, their current values, and the source of each value (env, file, or default).

---

## Setup

Setup runners and dependencies.

### `mthds setup runner`

Check if a runner is available and print installation instructions.

```bash
mthds setup runner <name>
```

| Argument | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Runner name (`pipelex` or `api`) |

**Examples:**

```bash
# Check if pipelex is installed
mthds setup runner pipelex

# Check the API runner (always available)
mthds setup runner api
```

---

## Package

Manage MTHDS packages: initialize, list, add dependencies, lock, install, update, and publish.

### `mthds package init`

Initialize a `METHODS.toml` package manifest in the current directory.

```bash
mthds package init [OPTIONS]
```

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `--force`, `-f` | bool | no | `False` | Overwrite existing `METHODS.toml` |
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |

**Examples:**

```bash
# Create a new manifest
mthds package init

# Overwrite an existing manifest
mthds package init --force
```

### `mthds package list`

Display the package manifest (`METHODS.toml`) for the current directory.

```bash
mthds package list [OPTIONS]
```

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |

Shows package metadata, dependencies, and exports in formatted tables.

### `mthds package add`

Add a dependency to `METHODS.toml`.

```bash
mthds package add <address> [OPTIONS]
```

| Argument / Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `address` | string | yes | -- | Package address (e.g. `github.com/org/repo`) |
| `--alias`, `-a` | string | no | auto-derived | Dependency alias (derived from address if omitted) |
| `--version`, `-v` | string | no | `0.1.0` | Version constraint |
| `--path`, `-p` | string | no | `None` | Local filesystem path to the dependency |
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |

**Examples:**

```bash
# Add a dependency (alias auto-derived as "my_methods")
mthds package add github.com/org/my-methods

# Add with explicit alias and version
mthds package add github.com/org/repo --alias my_dep --version 1.0.0

# Add a local dependency
mthds package add github.com/org/repo --path ../local-repo
```

### `mthds package lock`

Resolve dependencies and generate `methods.lock`.

```bash
mthds package lock [OPTIONS]
```

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |

### `mthds package install`

Install dependencies from `methods.lock`.

```bash
mthds package install [OPTIONS]
```

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |

Requires a `methods.lock` file. Run `mthds package lock` first if one does not exist.

### `mthds package update`

Re-resolve dependencies and update `methods.lock`.

```bash
mthds package update [OPTIONS]
```

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `--directory`, `-d` | string | no | `.` | Target package directory (defaults to current directory) |

Performs a fresh resolve of all dependencies, rewrites the lock file, and displays a diff of changes.
