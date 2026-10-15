import base64
from typing import Any

import pytest

from mthds.method_tree.exceptions import MethodTreeRefusedError
from mthds.method_tree.file_entry import InMemoryBlobStore, read_file_map
from tests.unit.method_tree.test_data import MethodTreeCorpus


class TestMethodTreeCorpusMaps:
    @pytest.mark.parametrize("case", MethodTreeCorpus.MAP_CASES, ids=[case["id"] for case in MethodTreeCorpus.MAP_CASES])
    def test_map_case(self, case: dict[str, Any]):
        """Each map case's document reads as its expected tree, or is refused as expected, against a store holding its blobs."""
        blob_store = InMemoryBlobStore([base64.b64decode(blob["base64"]) for blob in case["blob_store"]])
        expected = case["expected"]
        if "refusal" in expected:
            with pytest.raises(MethodTreeRefusedError) as refused:
                read_file_map(case["document"], blob_store=blob_store)
            assert refused.value.refusal.model_dump(mode="json", exclude_none=True) == expected["refusal"]
            return
        reading = read_file_map(case["document"], blob_store=blob_store)
        assert [tree_file.model_dump() for tree_file in reading.tree.files] == expected["files"]
        assert reading.tree.digest == expected["digest"]
        assert sorted(reading.contents) == [tree_file["path"] for tree_file in expected["files"]]
