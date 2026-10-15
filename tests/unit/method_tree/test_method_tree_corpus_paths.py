from typing import Any

import pytest

from mthds.method_tree.exceptions import MethodTreeRefusedError
from mthds.method_tree.tree_path import check_tree_path, is_tree_path
from tests.unit.method_tree.test_data import MethodTreeCorpus


class TestMethodTreeCorpusPaths:
    @pytest.mark.parametrize("case", MethodTreeCorpus.PATH_CASES, ids=[case["description"] for case in MethodTreeCorpus.PATH_CASES])
    def test_path_case(self, case: dict[str, Any]):
        """Each path case is a tree path or is refused as invalid_tree_path naming it."""
        expected = case["expected"]
        if expected.get("valid"):
            assert is_tree_path(case["path"])
            assert check_tree_path(case["path"]) == case["path"]
            return
        assert not is_tree_path(case["path"])
        with pytest.raises(MethodTreeRefusedError) as refused:
            check_tree_path(case["path"])
        assert refused.value.refusal.model_dump(mode="json", exclude_none=True) == expected["refusal"]
