"""The shared projection fixture corpus, from this side of the mirror.

A pipe's fill-in inputs template is projected client-side from the input-form descriptor — once
here and once in the `mthds` TypeScript package — and the two projections must produce the *same
bytes*, TOML ``# concept:`` comment lines included, or the JS/Python asymmetry the build-route
retirement set out to remove is simply rebuilt one layer up. ``tests/fixtures/protocol/
inputs_template/`` holds the expected bytes; `mthds-js` commits the identical tree and runs the twin
of this module. The corpus README carries the provenance and the regeneration command.

Five jobs, four of which run today:

1. **Byte parity** — every corpus file reproduced exactly by the projection. Skipped until the
   projection exists (`L-260830-e7c5b5`); it is the whole point of the corpus, and the reason the
   corpus lands before either projection is written.
2. **Kind coverage** — the kinds the corpus exercises must be the *whole* closed vocabulary. A kind
   added to the standard without a fixture is a corpus gap, and this says so by name rather than
   passing silently.
3. **File-set completeness** — every pipe the manifest names, in both shapes and both formats,
   non-empty.
4. **Divergence lapse** — the corpus deliberately differs from the reference engine's own
   inputs-template renderer in declared places. Each declared class must still be visible in the
   committed bytes, so an engine fix retires its entry deliberately instead of leaving the manifest
   claiming a difference that has gone.
5. **Unshapeable-record integrity** — the generator round-trips every projected template through the
   runtime's own input shaper and records each refusal. The verdict itself cannot be re-derived here
   (there is no shaper on this side of the mirror), so what this checks is that the record keys
   resolve against the rest of the manifest and each entry names the gap that retires it.
"""

import importlib
import importlib.util
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from mthds.protocol.input_form import FieldKind, InputFormItem, PipeInputFormDescriptor

_CORPUS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "protocol"
_TEMPLATES_DIR = _CORPUS_DIR / "inputs_template"
_MANIFEST_FILE_NAME = "manifest.json"

# Where the projection will live, and the surface this corpus checks. Named here because the corpus
# is contract-first: it states the expectation before either projection is written. If the projection
# lands under another name, update this module in the same change — do not leave the check skipped.
_PROJECTION_MODULE = "mthds.protocol.inputs_template"
_PROJECTION_ITEM = "L-260830-e7c5b5"

_MANIFEST: dict[str, Any] = json.loads((_TEMPLATES_DIR / _MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
_INPUT_FORM: dict[str, Any] = json.loads((_CORPUS_DIR / "input_form.json").read_text(encoding="utf-8"))
_PIPE_IO_CONTRACTS: dict[str, Any] = json.loads((_CORPUS_DIR / "pipe_io_contracts.json").read_text(encoding="utf-8"))

# The axes are read from the manifest but not trusted from it. Every case below is a product of
# these two lists, so a regeneration that dropped a shape or a format would quietly shrink the suite
# instead of failing it — the parity check would stop covering TOML and still report green. Pinning
# them here means the corpus can grow a pipe without touching this file, but never lose an axis.
_EXPECTED_SHAPES = ["compact", "explicit"]
_EXPECTED_FORMATS = ["json", "toml"]

_PIPE_REFS: list[str] = _MANIFEST["pipes"]
_SHAPES: list[str] = _MANIFEST["shapes"]
_FORMATS: list[str] = _MANIFEST["formats"]
_DIVERGENCES: list[dict[str, Any]] = _MANIFEST["divergences"]
_UNSHAPEABLE: list[dict[str, Any]] = _MANIFEST["unshapeable"]

# One bullet of the README's divergence list: the id in backticks, then the em dash its prose follows.
_README_DIVERGENCE_BULLET = re.compile(r"^- `([a-z0-9-]+)` — ", re.MULTILINE)

# A workspace-ledger id, the form every entry must name its tracking gap in.
_LEDGER_ITEM_PATTERN = re.compile(r"^L-\d{6}-[0-9a-f]{6}$")

assert sorted(_SHAPES) == sorted(_EXPECTED_SHAPES), f"the manifest lost a shape: {_SHAPES}"
assert sorted(_FORMATS) == sorted(_EXPECTED_FORMATS), f"the manifest lost a format: {_FORMATS}"

_CASES = [(pipe_ref, shape, file_format) for pipe_ref in _PIPE_REFS for shape in _SHAPES for file_format in _FORMATS]

_projection_available = importlib.util.find_spec(_PROJECTION_MODULE) is not None


def _template_file_name(*, pipe_ref: str, shape: str, file_format: str) -> str:
    """The corpus file name for one pipe, shape and format — the layout is part of the contract."""
    return f"{pipe_ref}.{shape}.{file_format}"


def _read_template(*, pipe_ref: str, shape: str, file_format: str) -> str:
    return (_TEMPLATES_DIR / _template_file_name(pipe_ref=pipe_ref, shape=shape, file_format=file_format)).read_text(encoding="utf-8")


def _walk_nodes(*, node: InputFormItem) -> Iterator[InputFormItem]:
    """Every node of a descriptor tree, the node itself first, then depth-first."""
    yield node
    match node.kind:
        case FieldKind.OBJECT:
            for field in node.fields:
                yield from _walk_nodes(node=field)
        case FieldKind.LIST:
            yield from _walk_nodes(node=node.item)
        case _:
            return


def _unshapeable_id(entry: dict[str, Any]) -> str:
    """The `(pipe_ref, shape)` key of one unshapeable entry, which is also its test id."""
    return f"{entry['pipe_ref']}.{entry['shape']}"


def _value_at_path(*, root: Any, path: str) -> Any:
    """One dotted path into a projected template — ``"page_in.content.images.0"``."""
    if not path:
        return root
    current = root
    for segment in path.split("."):
        if isinstance(current, list):
            current = cast("list[Any]", current)[int(segment)]
        elif isinstance(current, dict):
            current = cast("dict[str, Any]", current)[segment]
        else:
            return None
    return current


class TestTheCorpus:
    """What the committed bytes must cover, checkable with no projection and no engine present."""

    def test_it_exercises_the_whole_closed_kind_vocabulary(self):
        covered: set[str] = set()
        for raw_descriptor in _INPUT_FORM.values():
            descriptor = PipeInputFormDescriptor.model_validate(raw_descriptor)
            for field in descriptor.fields:
                covered.update(node.kind for node in _walk_nodes(node=field))
        # Equality both ways: a kind the corpus misses is a gap, and a kind it holds that the
        # vocabulary no longer declares is a stale capture.
        assert covered == set(FieldKind)

    def test_it_holds_every_pipe_in_both_shapes_and_both_formats(self):
        expected = {_template_file_name(pipe_ref=pipe_ref, shape=shape, file_format=file_format) for pipe_ref, shape, file_format in _CASES}
        present = {path.name for path in _TEMPLATES_DIR.iterdir() if path.name != _MANIFEST_FILE_NAME}
        assert present == expected

    def test_it_describes_exactly_the_pipes_the_descriptor_capture_holds(self):
        assert set(_PIPE_REFS) == set(_INPUT_FORM)

    def test_the_two_payload_files_name_the_same_pipes(self):
        # `input_form.json` and `pipe_io_contracts.json` are one capture taken in one command, so a
        # pipe present in either must be present in both. Nothing else here reads the contracts file,
        # which is what let one half lose a pipe with the whole suite still green.
        assert set(_PIPE_IO_CONTRACTS) == set(_INPUT_FORM)

    @pytest.mark.parametrize(("pipe_ref", "shape", "file_format"), _CASES)
    def test_no_template_is_empty(self, pipe_ref: str, shape: str, file_format: str):
        assert _read_template(pipe_ref=pipe_ref, shape=shape, file_format=file_format).strip()


class TestDeclaredDivergences:
    """The corpus departs from the reference engine only where it says it does, and it still does."""

    def test_at_least_one_is_declared(self):
        assert _DIVERGENCES

    def test_every_declared_class_is_documented_in_the_readme_and_no_other(self):
        # The README beside the corpus explains each class in prose, and that is the half of the record
        # nothing enforced: the manifest is checked hard, so a class that stops occurring has to be
        # retired deliberately, but a retired class could leave its bullet behind describing a difference
        # that no longer exists — and the suite, parametrised over the manifest's own list, would simply
        # shrink rather than fail. The equality runs both ways, so neither half can move alone.
        readme = (_CORPUS_DIR / "README.md").read_text(encoding="utf-8")
        documented = set(_README_DIVERGENCE_BULLET.findall(readme))
        declared = {str(divergence["divergence_id"]) for divergence in _DIVERGENCES}
        assert documented == declared

    @pytest.mark.parametrize("divergence", _DIVERGENCES, ids=lambda divergence: str(divergence["divergence_id"]))
    def test_a_divergence_states_why_it_exists_and_where(self, divergence: dict[str, Any]):
        assert divergence["reason"]
        assert divergence["occurrences"] > 0
        assert divergence["examples"]

    @pytest.mark.parametrize("divergence", _DIVERGENCES, ids=lambda divergence: str(divergence["divergence_id"]))
    def test_a_divergence_is_still_visible_in_the_committed_bytes(self, divergence: dict[str, Any]):
        for example in cast("list[dict[str, Any]]", divergence["examples"]):
            template = json.loads(_read_template(pipe_ref=example["pipe_ref"], shape=example["shape"], file_format="json"))
            # The corpus must hold what the manifest says it holds — and something other than what
            # the engine emitted, or the class has lapsed and its entry should go.
            assert _value_at_path(root=template, path=example["path"]) == example["expected"]
            assert example["expected"] != example["engine"]


class TestTheUnshapeableRecord:
    """The templates this capture pins that the runtime's own input shaper refuses to take back.

    A template's whole purpose is to be filled in and handed back, so the generator hands every
    projected template to ``InputShaper.shape`` at capture time and writes down each refusal. There
    is no shaper on this side of the mirror, so the verdict is taken on the generator's authority;
    what is checkable here is that the record stays about *this* corpus across a regeneration.
    """

    @pytest.mark.parametrize("entry", _UNSHAPEABLE, ids=_unshapeable_id)
    def test_an_entry_is_keyed_to_a_pipe_and_a_shape_the_corpus_holds(self, entry: dict[str, Any]):
        assert entry["pipe_ref"] in _PIPE_REFS
        assert entry["shape"] in _SHAPES

    def test_it_names_one_entry_per_pipe_and_shape(self):
        keys = [_unshapeable_id(entry) for entry in _UNSHAPEABLE]
        assert sorted(set(keys)) == sorted(keys)

    @pytest.mark.parametrize("entry", _UNSHAPEABLE, ids=_unshapeable_id)
    def test_an_entry_states_the_refusal_and_the_gap_that_retires_it(self, entry: dict[str, Any]):
        # The error type is what the runtime raised; the ledger item is the fix whose landing makes
        # the entry disappear from a regenerated manifest. An entry with neither is a refusal nobody
        # is tracking, which is the thing this record exists to prevent.
        assert entry["error_type"]
        assert _LEDGER_ITEM_PATTERN.match(entry["ledger_item"])

    def test_it_is_an_exception_list_not_the_whole_corpus(self):
        # Every (pipe, shape) unshapeable would mean the corpus pins bytes the runtime refuses
        # outright — a broken capture wearing a complete declaration.
        assert len(_UNSHAPEABLE) < len(_PIPE_REFS) * len(_SHAPES)


@pytest.mark.skipif(
    not _projection_available,
    reason=f"{_PROJECTION_MODULE} does not exist yet — the corpus lands before the projection ({_PROJECTION_ITEM})",
)
class TestByteParity:
    """The deliverable this whole corpus exists for: the same bytes as the TypeScript projection."""

    @pytest.mark.parametrize(("pipe_ref", "shape", "file_format"), _CASES)
    def test_the_projection_reproduces_the_corpus(self, pipe_ref: str, shape: str, file_format: str):
        projection = importlib.import_module(_PROJECTION_MODULE)
        descriptor = PipeInputFormDescriptor.model_validate(_INPUT_FORM[pipe_ref])
        rendered = projection.render_inputs_template(
            descriptor=descriptor,
            explicit=shape == "explicit",
            output_format=file_format,
        )
        assert rendered == _read_template(pipe_ref=pipe_ref, shape=shape, file_format=file_format)
