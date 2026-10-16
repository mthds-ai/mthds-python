from typing import Any

import pytest
from pydantic import ValidationError

from mthds.protocol.models import BlobRef, MissingBlobsRequest, MissingBlobsResult, VersionInfo
from tests.unit.test_data import BlobWireBodies


class TestProtocolBlobModels:
    @pytest.mark.parametrize(
        ("body", "expected_blob_store"),
        [
            pytest.param({"protocol_version": "1.0.0"}, False, id="a runner that does not say keeps no blob store"),
            pytest.param({"protocol_version": "1.0.0", "blob_store": False}, False, id="a runner that says it keeps none"),
            pytest.param({"protocol_version": "1.0.0", "runner_version": "0.88.0", "blob_store": True}, True, id="a runner with a blob store"),
        ],
    )
    def test_version_info_reads_the_blob_store_flag(self, body: dict[str, Any], expected_blob_store: bool) -> None:
        """`blob_store` is a typed protocol field, false when absent, rather than an untyped extension."""
        info = VersionInfo.model_validate(body)
        assert info.blob_store is expected_blob_store
        assert info.model_extra == {}

    def test_missing_blobs_request_writes_the_wire_shape(self) -> None:
        """The request lists each blob by hash and size, and leaves `digest` out when none is given."""
        blob = BlobRef(sha256=BlobWireBodies.CARD_SHA256, size=13)
        with_digest = MissingBlobsRequest(blobs=[blob], digest=BlobWireBodies.TREE_DIGEST)
        without_digest = MissingBlobsRequest(blobs=[blob])
        assert with_digest.model_dump_json(exclude_none=True) == BlobWireBodies.REQUEST_WITH_DIGEST
        assert without_digest.model_dump_json(exclude_none=True) == BlobWireBodies.REQUEST_WITHOUT_DIGEST

    def test_missing_blobs_result_reads_the_upload_targets(self) -> None:
        """The answer's blobs carry their upload target whole, and extension members ride `model_extra`."""
        result = MissingBlobsResult.model_validate(BlobWireBodies.ONE_MISSING)
        assert len(result.missing) == 1
        missing = result.missing[0]
        assert (missing.sha256, missing.size) == (BlobWireBodies.CARD_SHA256, 13)
        assert missing.upload.method == "PUT"
        assert missing.upload.url == BlobWireBodies.UPLOAD_URL
        assert missing.upload.headers == BlobWireBodies.UPLOAD_HEADERS
        assert result.model_extra == {"expires_in": 900}

    @pytest.mark.parametrize(
        ("topic", "missing_blob"),
        BlobWireBodies.MALFORMED_MISSING_BLOBS,
    )
    def test_missing_blobs_result_refuses_a_malformed_blob(self, topic: str, missing_blob: dict[str, Any]) -> None:
        """A size written with a fraction, an uppercase hash or a blob with no upload target is no blob the protocol defines."""
        with pytest.raises(ValidationError):
            MissingBlobsResult.model_validate({"missing": [missing_blob]})
        assert topic

    @pytest.mark.parametrize(
        "fields",
        [
            pytest.param({"sha256": BlobWireBodies.CARD_SHA256, "size": 13, "url": "https://example.com"}, id="a member the protocol closes out"),
            pytest.param({"sha256": BlobWireBodies.CARD_SHA256, "size": -1}, id="a negative size"),
        ],
    )
    def test_blob_ref_is_closed(self, fields: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            BlobRef.model_validate(fields)
