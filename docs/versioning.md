# Versions this package carries

Several different numbers are in play when you use `mthds`, and only some of them are the standard's. Confusing them is what let the standard version sit still for six months while the language underneath it changed, so this page says what each one is and where it is written.

| Number | Declared at | What it versions |
|---|---|---|
| **MTHDS standard version** | `MTHDS_STANDARD_VERSION`, `mthds/package/manifest/schema.py` | The language, the native concept set, the `METHODS.toml` and `methods.lock` formats, the library crate format, the namespace resolution rules |
| **MTHDS Protocol version** | `PROTOCOL_VERSION`, `mthds/protocol/protocol.py` | The HTTP runner contract — its routes and the shapes they exchange |
| **MTHDS core error registry version** | `CORE_ERROR_REGISTRY_VERSION`, `mthds/protocol/protocol.py` | The registry of error codes a problem document carries, vendored under `vendor/mthds-error-registry/` and generated into `mthds/protocol/problem/registry.py` |
| This package's release | `pyproject.toml` | This library, and nothing else |
| A runner's version | `VersionInfo.runner_version`, reported by the runner | That runner's own build |

The standard's numbers are **copies of a cut made by the standard**, not decisions this package makes. The rule that moves them — what counts as a major, a minor and a patch for each — is [`https://mthds.ai/latest/spec/versioning/`](https://mthds.ai/latest/spec/versioning/), and each constant is declared once, in one place, with that page named in its docstring. Following a cut is therefore a single edit per number.

Two properties of the rule are worth knowing before you read a version out of this package:

- **The standard version and the protocol version are independent.** The protocol version never tracks the standard version. A release of the standard that leaves the routes alone leaves `PROTOCOL_VERSION` exactly where it is, which is why `2.0.0` and `8.0.0` are as far apart as they are.
- **The standard version moves on every release of the specification**, including one that changes nothing normative. So the number rising is not by itself evidence that anything you depend on changed; the standard's changelog is. The corollary is that the pinned native set is identified by the standard version in which it *last changed*, and an implementation of version `V` materializes the set pinned at the greatest version less than or equal to `V`.

## `mthds_version` in a manifest is a constraint

A package's `METHODS.toml` may declare a `mthds_version`. It is a constraint — the versions of the standard the package says it works with — and it is evaluated against `MTHDS_STANDARD_VERSION` and nothing else: never against this package's release, a runner's version, or the protocol version.

```python
from mthds.package.manifest.parser import parse_methods_toml
from mthds.package.manifest.schema import is_mthds_version_satisfied

manifest = parse_methods_toml(methods_toml_text)
if manifest.mthds_version is not None and not is_mthds_version_satisfied(manifest.mthds_version):
    ...  # this runtime implements a standard version the package does not accept
```

Parsing a manifest deliberately does **not** evaluate the constraint. A package asking for a standard version this runtime does not implement is a well-formed manifest, and what to do about it — warn, refuse to load it, fail validation — belongs to the runtime, which is why the evaluation is a helper you call rather than something `parse_methods_toml` decides for you. The parser checks only that the constraint is *spellable*: `is_valid_version_constraint` accepts the range syntax the manifest format documents (`2.0.0`, `^2.0.0`, `~2.0.0`, `>=2.0.0`, `>=2.0.0, <3.0.0`, `*`, `2.*`), and `is_mthds_version_satisfied` raises `SemVerError` on anything it cannot parse.

The same number appears in a library crate as a **stamp** rather than a constraint: the exact standard version the crate was normalized against, recording which pinned native set produced its materialized natives. Crates are produced by the runtime (`pipelex`), which stamps them with this package's `MTHDS_STANDARD_VERSION`.

## Reading a runner's versions

`VersionInfo`, returned by a runner's `version()` route, carries `protocol_version`, an optional `runner_version`, and `blob_store`, true when the runner keeps a blob store and so accepts files sent by hash (false when the runner does not say). The protocol version a runner reports is the one it implements — compare it against `PROTOCOL_VERSION` to know whether this client and that runner agree on the wire contract. `runner_version` is that server's own build number and means nothing outside it.

## The error registry follows the standard's releases

The core error registry is published with each release of the standard, under that release's number, and a new code moves no protocol number: that is why the registry has a version of its own here, and why it can stand ahead of `MTHDS_STANDARD_VERSION`, which follows the language rather than the codes. The registry's JSON snapshot and its schema are vendored byte for byte from the `mthds` repository, with a sidecar (`vendor/mthds-error-registry/source.json`) recording the ref, the commit and each file's SHA-256, and the module `mthds/protocol/problem/registry.py` is generated from them. Following a registry release takes three steps:

```bash
make vendor-error-registry MTHDS=<path to an mthds checkout> REF=<tag, such as v8.0.0>
make generate-error-registry
# then set CORE_ERROR_REGISTRY_VERSION in mthds/protocol/protocol.py to the registry's version
```

`make check-error-registry` runs offline and fails when the vendored files differ from the hashes their sidecar records, when the snapshot's version differs from `CORE_ERROR_REGISTRY_VERSION`, or when regenerating the module from the vendored snapshot would change it; `tests/unit/test_error_registry_vendored.py` checks the same in `make agent-test` and in CI. `make check-error-registry-upstream MTHDS=<path> REF=<tag>` additionally compares the vendored snapshot with the one the given ref publishes, and is never required.
