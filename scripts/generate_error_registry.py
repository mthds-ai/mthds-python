"""Generate `mthds/protocol/problem/registry.py` from the vendored MTHDS core error registry.

Usage: `make generate-error-registry` writes the module, and `make check-error-registry` (also run by
`tests/unit/test_error_registry_vendored.py`) fails when the vendored files differ from the hashes
their sidecar records, when the snapshot's version differs from the `CORE_ERROR_REGISTRY_VERSION`
the package declares, or when the committed module differs from what this script would write. Both
read only the files under `vendor/mthds-error-registry/`, so the check runs offline.

The inputs are the registry's JSON snapshot, which holds every core code, and the registry's JSON
Schema, which holds the protocol's closed lists (the domains, the retry verdicts, the step kinds and
the parameter types). Nothing the module states about a code is written by hand: a constant per
code, a parameters model per code, every code's entry, the extension prefixes, the family fallbacks
and the generic reading of an answer that is not a problem document are all derived here. The output
is passed through `ruff format` so that the repository's formatter leaves it unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIRECTORY = REPO_ROOT / "vendor" / "mthds-error-registry"
SNAPSHOT_PATH = VENDOR_DIRECTORY / "mthds-error-registry.json"
SCHEMA_PATH = VENDOR_DIRECTORY / "mthds-error-registry.schema.json"
SIDECAR_PATH = VENDOR_DIRECTORY / "source.json"
DECLARATION_PATH = REPO_ROOT / "mthds" / "protocol" / "protocol.py"
DECLARATION_PATTERN = re.compile(r'^CORE_ERROR_REGISTRY_VERSION: Final\[str\] = "([^"]+)"$', re.MULTILINE)
OUTPUT_PATH = REPO_ROOT / "mthds" / "protocol" / "problem" / "registry.py"
OUTPUT_RELATIVE = "mthds/protocol/problem/registry.py"

# How long a string literal may grow before it is split into an implicit concatenation, so that no
# generated line passes the repository's line length.
_CHUNK_LENGTH = 100


class GenerationError(Exception):
    """The vendored registry cannot be turned into the module."""


def _camel(name: str) -> str:
    """`request.blobs_missing` -> `RequestBlobsMissing`."""
    parts = name.replace(".", "_").split("_")
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _constant(name: str) -> str:
    """`request.blobs_missing` -> `REQUEST_BLOBS_MISSING`."""
    return name.replace(".", "_").upper()


# A word with the spaces that follow it, or the spaces a text opens with: the pieces a long literal is
# cut between, which join back into the text exactly, every space kept.
_LITERAL_PIECE = re.compile(r"[^ ]+ *| +")


def _literal(text: str) -> str:
    """A Python string literal for `text`, split into an implicit concatenation when it is long.

    The text is cut only after a run of spaces, each chunk keeping the spaces it ends on, so that the
    chunks concatenate back into `text` exactly, a double space or a leading one included.
    """
    if len(text) <= _CHUNK_LENGTH:
        return json.dumps(text, ensure_ascii=False)
    chunks: list[str] = []
    current = ""
    for piece in _LITERAL_PIECE.findall(text):
        if current and len((current + piece).rstrip(" ")) > _CHUNK_LENGTH:
            chunks.append(current)
            current = piece
        else:
            current += piece
    chunks.append(current)
    inner = "\n".join(f"    {json.dumps(chunk, ensure_ascii=False)}" for chunk in chunks)
    return f"(\n{inner}\n)"


def _closed_list(schema: dict[str, Any], name: str) -> list[str]:
    try:
        values = schema["$defs"][name]["enum"]
    except KeyError as exc:
        msg = f"The registry's schema has no closed list '{name}'."
        raise GenerationError(msg) from exc
    return [str(value) for value in values]


def _python_type(param: dict[str, Any], enum_class: str | None) -> str:
    """The annotation a parameter's value reads as, widened where the registry lists values.

    A number is read strictly, as `mthds.protocol.problem.models` reads every number of the problem
    document: `JsonInteger` and `JsonNumber` refuse a string and a boolean, which pydantic's lax mode
    would coerce.
    """
    param_type = param["type"]
    match param_type:
        case "identifier" | "caller_text":
            return "str"
        case "integer":
            return "JsonInteger"
        case "seconds":
            return "Annotated[JsonNumber, Field(ge=0)]"
        case "bytes":
            return "Annotated[JsonInteger, Field(ge=0)]"
        case "sha256":
            return 'Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]'
        case "enum":
            return f'Annotated[{enum_class} | str, Field(union_mode="left_to_right")]'
        case "list":
            item = param["items"]
            item_type = _python_type(item, enum_class)
            return f"list[{item_type}]"
        case _:
            msg = f"Unknown parameter type '{param_type}'."
            raise GenerationError(msg)


def _check(snapshot: dict[str, Any], closed: dict[str, list[str]]) -> None:
    """Refuse a snapshot this generator does not understand, before writing anything."""
    for key in ("version", "base_url", "extension_prefixes", "families", "codes"):
        if key not in snapshot:
            msg = f"The snapshot has no '{key}' member."
            raise GenerationError(msg)
    families = {family["family"] for family in snapshot["families"]}
    seen: set[str] = set()
    for entry in snapshot["codes"]:
        code = entry["code"]
        if code in seen:
            msg = f"The code '{code}' is given twice."
            raise GenerationError(msg)
        seen.add(code)
        if code.rsplit(".", 1)[0] not in families:
            msg = f"The code '{code}' belongs to no declared family."
            raise GenerationError(msg)
        for member, list_name in (("domain", "domain"), ("retry", "retry")):
            if entry[member] not in closed[list_name]:
                msg = f"The code '{code}' has the {member} '{entry[member]}', which the closed list does not hold."
                raise GenerationError(msg)
        for step_name in ("actor", "other"):
            if entry["steps"][step_name]["kind"] not in closed["stepKind"]:
                msg = f"The code '{code}' has an unknown {step_name} step kind."
                raise GenerationError(msg)
        if (entry["raised_as"] == "problem") != ("status" in entry):
            msg = f"The code '{code}' carries a status exactly when it is raised as a problem."
            raise GenerationError(msg)


def _family_unanimous(snapshot: dict[str, Any], pick: str) -> dict[str, str]:
    """The families whose every code declares the same value for `pick`, with that value.

    For the step kind, the value must be the same in both of every code's steps, the one aimed at the
    actor and the one aimed at any other reader: a reader of a problem whose step kind it does not know
    cannot tell which of the two it is, so a family whose codes give different kinds to the two
    readers says nothing it can rely on, and reads as a family it knows nothing of.
    """
    by_family: dict[str, set[str]] = {}
    for entry in snapshot["codes"]:
        family = entry["code"].rsplit(".", 1)[0]
        values = by_family.setdefault(family, set())
        if pick == "domain":
            values.add(entry["domain"])
        else:
            values.update((entry["steps"]["actor"]["kind"], entry["steps"]["other"]["kind"]))
    return {family: next(iter(values)) for family, values in by_family.items() if len(values) == 1}


def _status_readings(snapshot: dict[str, Any]) -> dict[int, str]:
    """The statuses an answer that is no problem document is read by, each with the one code it names.

    A status names a code when exactly one core code raised as a problem carries it and a client can
    state that code completely from the answer alone: every parameter it declares is optional or
    operator-only, which a caller's problem leaves out, and none of its sentences names one.
    """
    by_status: dict[int, list[dict[str, Any]]] = {}
    for entry in snapshot["codes"]:
        if entry["raised_as"] == "problem":
            by_status.setdefault(int(entry["status"]), []).append(entry)
    readings: dict[int, str] = {}
    for status, entries in sorted(by_status.items()):
        if len(entries) != 1:
            continue
        entry = entries[0]
        statable = all(param.get("optional", False) or param.get("operator_only", False) for param in entry["params"].values())
        sentences = " ".join([entry["detail"], entry["steps"]["actor"]["detail"], entry["steps"]["other"]["detail"]])
        names_a_param = any(f"{{{name}}}" in sentences for name in entry["params"])
        if statable and not names_a_param:
            readings[status] = entry["code"]
    return readings


_PREAMBLE = '''"""The MTHDS core error registry {version}, generated from its vendored snapshot: do not edit this file.

`scripts/generate_error_registry.py` writes it from `vendor/mthds-error-registry/mthds-error-registry.json`
and the registry's schema beside it, `make generate-error-registry` runs it, and
`tests/unit/test_error_registry_vendored.py` fails when this file differs from what it would write.

It holds the protocol's closed lists (`ProblemDomain`, `RetryVerdict`, `StepKind`), a constant per core
code (`CoreCode`), a parameters model per code, every code's entry (`CORE_CODE_SPECS`), the registered
extension prefixes, the family fallbacks a reader uses for a value it does not know, and the statuses
by which an answer that is not a problem document is read (`STATUS_READINGS`). A parameters model
widens a parameter whose values the registry lists to any string, since a reader accepts a value a
later registry adds, and it accepts members it does not declare. It reads a number strictly, never
from a string or a boolean, as `JsonInteger` and `JsonNumber` read it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field
{json_types_import}
REGISTRY_VERSION: Final[str] = {version_literal}
"""The version of the core registry this module was generated from, which is the standard version it is published with."""

CORE_BASE_URL: Final[str] = {base_url_literal}
"""The base URL of the core codes' pages: a core code's `type` is this URL, a slash, then the code."""
'''

_SPEC_MODELS = '''

class ParamSpec(BaseModel):
    """One parameter a code declares: its name, its type, and whether a reader may miss it."""

    model_config = ConfigDict(frozen=True)

    name: str
    param_type: ParamType
    item_type: ParamType | None = None
    values: tuple[str, ...] = ()
    optional: bool = False
    operator_only: bool = False


class StepSpec(BaseModel):
    """One of a code's two next steps: its kind and the template of its `detail` sentence."""

    model_config = ConfigDict(frozen=True)

    kind: StepKind
    detail: str


class CodeSpec(BaseModel):
    """Everything the registry declares about one code that a reader or a client building a problem needs.

    `actor_step` is aimed at the domain's actor and `other_step` at any other reader; `detail` and each
    step's `detail` are templates naming the code's parameters as `{name}`. `status` is the HTTP status
    of a response the code is the body of, and `None` for a code raised by a client or only as a warning.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    title: str
    domain: ProblemDomain
    retry: RetryVerdict
    raised_as: RaisedAs
    status: int | None
    detail: str
    actor_step: StepSpec
    other_step: StepSpec
    params: tuple[ParamSpec, ...]
    params_model: type[BaseModel]

    @property
    def family(self) -> str:
        """The code without its last segment."""
        return self.code.rsplit(".", 1)[0]
'''


def _enum_class(name: str, doc: str, values: list[str]) -> list[str]:
    lines = ["", "", f"class {name}(StrEnum):", f'    """{doc}"""', ""]
    lines.extend(f"    {_constant(value)} = {json.dumps(value)}" for value in values)
    return lines


_JSON_TYPES = ("JsonInteger", "JsonNumber")


def _json_types_import(body: str) -> str:
    """The import of the strict JSON number types the module's body uses, empty when it uses none."""
    used = [name for name in _JSON_TYPES if re.search(rf"\b{name}\b", body)]
    if not used:
        return ""
    return f"\nfrom mthds.protocol.problem.json_types import {', '.join(used)}\n"


def render(snapshot: dict[str, Any], schema: dict[str, Any]) -> str:
    """The module's source, before formatting."""
    closed = {name: _closed_list(schema, name) for name in ("domain", "retry", "stepKind", "scalarType")}
    _check(snapshot, closed)
    lines: list[str] = []
    lines.extend(_enum_class("ProblemDomain", "Who must act: the protocol's closed list of domains.", closed["domain"]))
    lines.extend(_enum_class("RetryVerdict", "Whether repeating the operation can succeed: the protocol's closed list of verdicts.", closed["retry"]))
    lines.extend(_enum_class("StepKind", "What the reader does next: the protocol's closed list of step kinds.", closed["stepKind"]))
    raised_as_doc = "Where a reader meets a code: as a problem, only as a warning, or raised by a client itself."
    lines.extend(_enum_class("RaisedAs", raised_as_doc, ["problem", "warning", "client"]))
    lines.extend(_enum_class("ParamType", "The types a code's parameter may have.", [*closed["scalarType"], "list"]))
    lines.extend(
        _enum_class(
            "CoreCode",
            "A constant per core code. A problem's `code` stays a plain string, since it may be an extension code or a later core code.",
            [entry["code"] for entry in snapshot["codes"]],
        )
    )
    lines.append(_SPEC_MODELS.rstrip("\n"))

    class_names: set[str] = set()
    model_names: dict[str, str] = {}
    for entry in snapshot["codes"]:
        code = entry["code"]
        model_name = f"{_camel(code)}Params"
        if model_name in class_names:
            msg = f"Two codes give the class name '{model_name}'."
            raise GenerationError(msg)
        class_names.add(model_name)
        model_names[code] = model_name
        field_lines: list[str] = []
        for param_name, param in entry["params"].items():
            enum_class: str | None = None
            values = param.get("values") or param.get("items", {}).get("values")
            if values:
                enum_class = f"{_camel(code)}{_camel(param_name)}"
                if enum_class in class_names:
                    msg = f"Two parameters give the class name '{enum_class}'."
                    raise GenerationError(msg)
                class_names.add(enum_class)
                lines.extend(_enum_class(enum_class, f"The values the registry lists for `{code}`'s parameter `{param_name}`.", values))
            annotation = _python_type(param, enum_class)
            description = _literal(param["description"])
            reader_may_miss = param.get("optional", False) or param.get("operator_only", False)
            if reader_may_miss:
                field_lines.append(f"    {param_name}: Annotated[{annotation} | None, Field(description={description})] = None")
            else:
                field_lines.append(f"    {param_name}: Annotated[{annotation}, Field(description={description})]")
        lines.extend(["", "", f"class {model_name}(BaseModel):", f'    """The parameters of `{code}`."""'])
        lines.extend(["", '    model_config = ConfigDict(extra="allow")'])
        if field_lines:
            lines.append("")
            lines.extend(field_lines)

    lines.extend(["", "", "CORE_CODE_SPECS: Final[dict[str, CodeSpec]] = {"])
    for entry in snapshot["codes"]:
        code = entry["code"]
        param_specs: list[str] = []
        for param_name, param in entry["params"].items():
            arguments = [f"name={json.dumps(param_name)}", f"param_type=ParamType.{_constant(param['type'])}"]
            if param["type"] == "list":
                arguments.append(f"item_type=ParamType.{_constant(param['items']['type'])}")
            values = param.get("values") or param.get("items", {}).get("values")
            if values:
                arguments.append(f"values=({', '.join(json.dumps(value) for value in values)},)")
            if param.get("optional", False):
                arguments.append("optional=True")
            if param.get("operator_only", False):
                arguments.append("operator_only=True")
            param_specs.append(f"ParamSpec({', '.join(arguments)})")
        params_tuple = f"({', '.join(param_specs)},)" if param_specs else "()"
        status = str(entry["status"]) if "status" in entry else "None"
        actor = entry["steps"]["actor"]
        other = entry["steps"]["other"]
        lines.extend(
            [
                f"    CoreCode.{_constant(code)}: CodeSpec(",
                f"        code={json.dumps(code)},",
                f"        title={_literal(entry['title'])},",
                f"        domain=ProblemDomain.{_constant(entry['domain'])},",
                f"        retry=RetryVerdict.{_constant(entry['retry'])},",
                f"        raised_as=RaisedAs.{_constant(entry['raised_as'])},",
                f"        status={status},",
                f"        detail={_literal(entry['detail'])},",
                f"        actor_step=StepSpec(kind=StepKind.{_constant(actor['kind'])}, detail={_literal(actor['detail'])}),",
                f"        other_step=StepSpec(kind=StepKind.{_constant(other['kind'])}, detail={_literal(other['detail'])}),",
                f"        params={params_tuple},",
                f"        params_model={model_names[code]},",
                "    ),",
            ]
        )
    lines.append("}")
    lines.append('"""Every core code\'s entry, by code."""')

    lines.extend(["", "FAMILIES: Final[tuple[str, ...]] = ("])
    lines.extend(f"    {json.dumps(family['family'])}," for family in snapshot["families"])
    lines.extend([")", '"""The core families, in the order the registry presents them."""'])

    lines.extend(["", "EXTENSION_PREFIXES: Final[dict[str, str]] = {"])
    lines.extend(f"    {json.dumps(prefix['prefix'])}: {json.dumps(prefix['base_url'])}," for prefix in snapshot["extension_prefixes"])
    lines.extend(["}", '"""The registered extension prefixes, each with the base URL its codes\' pages are published under."""'])

    lines.extend(["", "FAMILY_DOMAINS: Final[dict[str, ProblemDomain]] = {"])
    lines.extend(f"    {json.dumps(family)}: ProblemDomain.{_constant(domain)}," for family, domain in _family_unanimous(snapshot, "domain").items())
    lines.extend(
        [
            "}",
            '"""The domain a reader reads for a family whose every code declares that domain; a family whose codes differ reads as `runtime`."""',
        ]
    )

    lines.extend(["", "FAMILY_STEP_KINDS: Final[dict[str, StepKind]] = {"])
    lines.extend(f"    {json.dumps(family)}: StepKind.{_constant(kind)}," for family, kind in _family_unanimous(snapshot, "step").items())
    lines.extend(
        [
            "}",
            (
                '"""The step kind a reader reads for a family whose every code gives that kind in both its steps, to the actor and'
                ' to any other reader;\nanother family reads `report`."""'
            ),
        ]
    )

    lines.extend(["", "STATUS_READINGS: Final[dict[int, CoreCode]] = {"])
    lines.extend(f"    {status}: CoreCode.{_constant(code)}," for status, code in _status_readings(snapshot).items())
    lines.extend(
        [
            "}",
            '"""The statuses that name one core code a client can state completely, by which an answer that is no problem document is read."""',
        ]
    )
    body = "\n".join(lines) + "\n"
    preamble = _PREAMBLE.format(
        version=snapshot["version"],
        version_literal=json.dumps(snapshot["version"]),
        base_url_literal=json.dumps(snapshot["base_url"]),
        json_types_import=_json_types_import(body),
    ).rstrip("\n")
    return f"{preamble}\n{body}"


def _ruff() -> str:
    beside_interpreter = Path(sys.executable).parent / "ruff"
    if beside_interpreter.is_file():
        return str(beside_interpreter)
    found = shutil.which("ruff")
    if found is None:
        msg = "ruff is not installed; run `make install` first."
        raise GenerationError(msg)
    return found


def formatted(source: str) -> str:
    """The source as the repository's formatter writes it."""
    completed = subprocess.run(
        [_ruff(), "format", "--config", str(REPO_ROOT / "pyproject.toml"), "--stdin-filename", OUTPUT_RELATIVE, "-"],
        input=source.encode(),
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )
    if completed.returncode != 0:
        msg = f"ruff format refused the generated module: {completed.stderr.decode(errors='replace').strip()}"
        raise GenerationError(msg)
    return completed.stdout.decode()


def generate() -> str:
    """The module as it must be committed, from the vendored files."""
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return formatted(render(snapshot, schema))


def drift() -> list[str]:
    """Every way the vendored registry, the declared version and the committed module disagree, empty when they agree."""
    findings: list[str] = []
    sidecar = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
    for name, recorded in sidecar["files"].items():
        actual = hashlib.sha256((VENDOR_DIRECTORY / name).read_bytes()).hexdigest()
        if actual != recorded:
            findings.append(f"vendor/mthds-error-registry/{name} is not the file its sidecar records; vendor it again.")
    snapshot_version = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["version"]
    if sidecar["registry_version"] != snapshot_version:
        findings.append(f"The sidecar records the registry {sidecar['registry_version']} but the snapshot is {snapshot_version}.")
    declared = DECLARATION_PATTERN.search(DECLARATION_PATH.read_text(encoding="utf-8"))
    if declared is None:
        findings.append("mthds/protocol/protocol.py declares no CORE_ERROR_REGISTRY_VERSION.")
    elif declared.group(1) != snapshot_version:
        findings.append(f"The package declares the registry {declared.group(1)} but the vendored snapshot is {snapshot_version}.")
    committed = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.is_file() else ""
    if committed != generate():
        findings.append(f"{OUTPUT_RELATIVE} differs from what the vendored registry generates; run `make generate-error-registry`.")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the vendored registry, the declared version and the module disagree")
    arguments = parser.parse_args()
    try:
        if arguments.check:
            findings = drift()
        else:
            source = generate()
    except GenerationError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    if arguments.check:
        for finding in findings:
            sys.stderr.write(f"error: {finding}\n")
        if findings:
            return 1
        sys.stdout.write("The vendored core error registry, its declared version and the generated module agree.\n")
        return 0
    OUTPUT_PATH.write_text(source, encoding="utf-8")
    sys.stdout.write(f"Wrote {OUTPUT_RELATIVE} from the vendored registry.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
