from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeRefusal
from mthds.method_tree.lister import list_method_tree
from mthds.method_tree.models import MethodTree
from mthds.method_tree.python_modules import locate_function
from mthds.method_tree.references import resolve_reference, resolve_reference_in_paths
from mthds.method_tree.vocabulary import ReferenceContext
from tests.unit.method_tree.test_data import MethodTreeCorpus


def _refusal_record(refusal: TreeRefusal) -> dict[str, Any]:
    return refusal.model_dump(mode="json", exclude_none=True)


def _workspace_of(handed_over: Path, *, case: dict[str, Any]) -> Path:
    depth = 0 if case["handed_over"] == "." else len(case["handed_over"].split("/"))
    workspace = handed_over
    for _level in range(depth):
        workspace = workspace.parent
    return workspace.resolve()


def _outcome_in_paths(tree: MethodTree, *, probe: dict[str, Any], context: ReferenceContext) -> str | dict[str, Any] | None:
    """What resolving a probe in the tree's set of paths answers: the tree path, None, or the refusal's record."""
    try:
        return resolve_reference_in_paths(
            probe["reference"], holder=probe["holder"], context=context, tree_paths=tree.members, is_one_file_tree=tree.is_one_file
        )
    except MethodTreeRefusedError as exc:
        return _refusal_record(exc.refusal)


def _check_references(tree: MethodTree, *, case: dict[str, Any]) -> None:
    """Each probe resolves as the corpus expects, and in the tree's set of paths to the same answer, which records no exclusion rule."""
    for probe in case.get("references", []):
        expected = probe["expected"]
        context = ReferenceContext(probe["context"])
        described = f"reference {probe['reference']!r} from {probe['holder']!r} in {context} context"
        in_paths = _outcome_in_paths(tree, probe=probe, context=context)
        if "refusal" in expected:
            with pytest.raises(MethodTreeRefusedError) as refused:
                resolve_reference(probe["reference"], holder=probe["holder"], context=context, tree=tree)
            assert _refusal_record(refused.value.refusal) == expected["refusal"], described
            without_exclusion = {key: value for key, value in expected["refusal"].items() if key not in {"excluded_by", "excluded_directory"}}
            assert in_paths == without_exclusion, described
        elif expected.get("not_a_reference"):
            assert resolve_reference(probe["reference"], holder=probe["holder"], context=context, tree=tree) is None, described
            assert in_paths is None, described
        else:
            assert resolve_reference(probe["reference"], holder=probe["holder"], context=context, tree=tree) == expected["tree_path"], described
            assert in_paths == expected["tree_path"], described


def _check_function_names(tree: MethodTree, *, case: dict[str, Any]) -> None:
    for probe in case.get("function_names", []):
        expected = probe["expected"]
        described = f"function_name {probe['function_name']!r}"
        if "refusal" in expected:
            with pytest.raises(MethodTreeRefusedError) as refused:
                locate_function(probe["function_name"], tree=tree)
            assert _refusal_record(refused.value.refusal) == expected["refusal"], described
        else:
            location = locate_function(probe["function_name"], tree=tree)
            assert {"module": location.module, "function": location.function} == expected, described


class TestMethodTreeCorpusTrees:
    @pytest.mark.parametrize("case", MethodTreeCorpus.TREE_CASES, ids=[case["id"] for case in MethodTreeCorpus.TREE_CASES])
    def test_tree_case(self, case: dict[str, Any], materialize_tree_case: Callable[[dict[str, Any]], Path]):
        """Each tree case lists to its tree, resolves its references in the tree and in its paths, and locates its functions, or is refused."""
        handed_over = materialize_tree_case(case)
        expected = case["expected"]
        if "refusal" in expected:
            with pytest.raises(MethodTreeRefusedError) as refused:
                list_method_tree(handed_over)
            assert _refusal_record(refused.value.refusal) == expected["refusal"]
            return
        tree = list_method_tree(handed_over)
        if expected["root"] is None:
            assert tree.is_one_file
        else:
            assert not tree.is_one_file
            assert tree.directory is not None
            root = _workspace_of(handed_over, case=case)
            if expected["root"] != ".":
                root = root.joinpath(*expected["root"].split("/"))
            assert tree.directory == root
        assert tree.entry == expected.get("entry")
        assert [tree_file.model_dump() for tree_file in tree.files] == expected["files"]
        assert tree.digest == expected["digest"]
        _check_references(tree, case=case)
        _check_function_names(tree, case=case)
