import asyncio
import json
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic_core import to_json
from pytest_mock import MockerFixture

from mthds.method_tree.digest import sha256_hex
from mthds.method_tree.exceptions import TreeSourceError
from mthds.method_tree.file_entry import Base64FileEntry, HashFileEntry, read_file_map
from mthds.method_tree.lister import list_method_tree
from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import BlobRef, MissingBlob, MissingBlobsResult, UploadTarget
from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.registry import CoreCode
from mthds.runners.api.client import DEFAULT_INLINE_TREE_MAX_BYTES, MthdsAPIClient
from mthds.runners.api.exceptions import ApiResponseError, BlobUploadError
from tests.unit.test_data import BlobWireBodies, ExecuteWireResponses, MethodFileMaps

_BASE_URL = "http://localhost:8081"
_BUCKET_HOST = "bucket.example"
_MISSING_BLOBS_REQUEST_ID = "req_3c1e9a52"
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _FakeRunner:
    """A runner keeping a blob store whose upload targets are presigned object-store URLs, served through httpx's MockTransport.

    It answers `version`, `blobs/missing` and `execute`, and stores an upload as a create-only object
    store does: bytes it already holds draw a `412`. An upload can be refused with `upload_status`,
    answering `upload_body`, or made to fail in transport, by the
    httpx failure `upload_failure` names, or to get an answer whose body cannot be decoded, and the targets
    it names can be moved to another origin, with other headers.
    """

    def __init__(self) -> None:
        self.blob_store = True
        self.held: dict[str, bytes] = {}
        self.upload_status: int | None = None
        self.upload_body = "<Error><Code>AccessDenied</Code></Error>"
        self.upload_failure: type[httpx.TransportError] | None = None
        self.upload_body_broken = False
        self.unrequested_missing: list[str] = []
        self.target_origin = f"https://{_BUCKET_HOST}"
        self.target_headers: dict[str, str] = {"If-None-Match": "*"}
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == _BUCKET_HOST:
            return self._store(request)
        match request.url.path:
            case "/v1/version":
                return httpx.Response(200, json={"protocol_version": "1.0.0", "runner_version": "0.88.0", "blob_store": self.blob_store})
            case "/v1/blobs/missing":
                asked = json.loads(request.content)["blobs"]
                missing = [self._missing(blob["sha256"], blob["size"]) for blob in asked if blob["sha256"] not in self.held]
                missing.extend(self._missing(sha256, 1) for sha256 in self.unrequested_missing)
                return httpx.Response(200, json={"missing": missing}, headers={"X-Request-ID": _MISSING_BLOBS_REQUEST_ID})
            case "/v1/execute":
                return httpx.Response(200, json=ExecuteWireResponses.REDUCED)
            case _:
                return httpx.Response(404, json={"type": "about:blank", "title": "Not Found", "status": 404})

    @property
    def uploads(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.host == _BUCKET_HOST]

    @property
    def api_paths(self) -> list[str]:
        return [request.url.path for request in self.requests if request.url.host != _BUCKET_HOST]

    def _missing(self, sha256: str, size: int) -> dict[str, Any]:
        url = f"{self.target_origin}/org_1/blobs/{sha256}?X-Amz-Signature=0123abcd"
        return {"sha256": sha256, "size": size, "upload": {"method": "PUT", "url": url, "headers": self.target_headers}}

    def _store(self, request: httpx.Request) -> httpx.Response:
        if self.upload_failure is not None:
            msg = "the transport failed"
            raise self.upload_failure(msg, request=request)
        if self.upload_body_broken:
            return httpx.Response(200, stream=httpx.ByteStream(b"this was never gzip"), headers={"Content-Encoding": "gzip"})
        if self.upload_status is not None:
            return httpx.Response(self.upload_status, text=self.upload_body)
        sha256 = request.url.path.rsplit("/", 1)[-1]
        if sha256 in self.held:
            return httpx.Response(412, text="<Error><Code>PreconditionFailed</Code></Error>")
        self.held[sha256] = request.content
        return httpx.Response(200)


@asynccontextmanager
async def _silent_server() -> AsyncGenerator[tuple[str, list[bytes]], None]:
    """A local server that accepts every connection and answers nothing, giving its origin and, once it is closed, what each connection sent.

    httpx writes a request only once it is connected, so a request it refuses to write must reach a server
    that accepts it for the refusal to be the client's own, rather than a connection that never opened.
    """
    received: list[bytes] = []

    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.read())
        writer.close()

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", received
    finally:
        server.close()
        await server.wait_closed()


def _write_tree(root: Path) -> None:
    """A method whose card template is stored twice under two names, so two files share one blob."""
    (root / "main.mthds").write_text(MethodFileMaps.BUNDLE, encoding="utf-8")
    (root / "templates").mkdir()
    (root / "templates" / "card.html").write_bytes(MethodFileMaps.CARD)
    (root / "templates" / "copy.html").write_bytes(MethodFileMaps.CARD)
    (root / "logo.png").write_bytes(MethodFileMaps.LOGO)


def _record_hashing(mocker: MockerFixture) -> list[int]:
    """Patch the client module's SHA-256 so that each call records the thread it ran on, and return that record."""
    hashing_threads: list[int] = []

    def recording_sha256_hex(data: bytes) -> str:
        hashing_threads.append(threading.get_ident())
        return sha256_hex(data)

    mocker.patch("mthds.runners.api.client.sha256_hex", side_effect=recording_sha256_hex)
    return hashing_threads


class TestMthdsAPIClientBlobs:
    @pytest.fixture(autouse=True)
    def _mock_config(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "mthds.runners.api.client.load_config",
            return_value={"api_key": "", "base_url": "", "runner": "api"},
        )

    @pytest.fixture
    def runner(self, mocker: MockerFixture) -> _FakeRunner:
        """Route every AsyncClient the client module builds, the API client and the upload client alike, to the fake runner."""
        fake = _FakeRunner()

        def make_client(**kwargs: Any) -> httpx.AsyncClient:
            return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(fake.handle), **kwargs)

        mocker.patch("mthds.runners.api.client.httpx.AsyncClient", side_effect=make_client)
        return fake

    def _client(self) -> MthdsAPIClient:
        return MthdsAPIClient(api_key="test-token", base_url=_BASE_URL)

    # ── missing_blobs ────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("digest", "expected_body"),
        [
            pytest.param(BlobWireBodies.TREE_DIGEST, BlobWireBodies.REQUEST_WITH_DIGEST, id="naming the tree"),
            pytest.param(None, BlobWireBodies.REQUEST_WITHOUT_DIGEST, id="naming no tree"),
        ],
    )
    def test_missing_blobs_posts_the_blobs_and_reads_the_targets(self, runner: _FakeRunner, digest: str | None, expected_body: str) -> None:
        """`missing_blobs` posts the protocol's request and reads each missing blob with its upload target."""
        client = self._client()

        result = asyncio.run(client.missing_blobs([BlobRef(sha256=MethodFileMaps.CARD_SHA256, size=13)], digest=digest))

        assert runner.api_paths == ["/v1/blobs/missing"]
        assert runner.requests[0].content.decode("utf-8") == expected_body
        assert runner.requests[0].headers["Authorization"] == "Bearer test-token"
        assert [(blob.sha256, blob.size, blob.upload.method) for blob in result.missing] == [(MethodFileMaps.CARD_SHA256, 13, "PUT")]
        assert result.missing[0].upload.headers == {"If-None-Match": "*"}

    def test_missing_blobs_refusal_raises_api_response_error(self, mocker: MockerFixture) -> None:
        """A runner's refusal, such as one hash listed with two sizes, raises the typed error every route raises."""
        client = self._client()
        problem = {
            "type": "https://mthds.ai/errors/request.invalid",
            "title": "The request does not match the route's schema",
            "status": 422,
            "detail": "The blob is listed twice with different sizes.",
            "code": "request.invalid",
            "domain": "input",
            "retry": "no",
            "next_step": {"kind": "change_input", "detail": "Pass this to the caller, who must correct the field 'blobs' of the request."},
            "params": {"field": "blobs"},
        }
        response = httpx.Response(422, json=problem, request=httpx.Request("POST", f"{_BASE_URL}/v1/blobs/missing"))
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=response))

        with pytest.raises(ApiResponseError) as exc_info:
            asyncio.run(client.missing_blobs([BlobRef(sha256=MethodFileMaps.CARD_SHA256, size=13)]))

        assert exc_info.value.problem.as_wire() == problem
        assert str(exc_info.value) == (
            "API POST /v1/blobs/missing failed (422): The blob is listed twice with different sizes.\n"
            "Next step: Pass this to the caller, who must correct the field 'blobs' of the request."
        )
        assert exc_info.value.request_url == f"{_BASE_URL}/v1/blobs/missing"

    @pytest.mark.parametrize(("topic", "answer"), BlobWireBodies.UNREADABLE_SIGNED_ANSWERS)
    def test_an_unreadable_missing_blobs_success_never_shows_its_signed_urls(self, mocker: MockerFixture, topic: str, answer: dict[str, Any]) -> None:
        """A success naming upload targets is never quoted, malformed or not the route's answer: only `response_body` keeps its signed URLs."""
        client = self._client()
        body = json.dumps(answer)
        request = httpx.Request("POST", f"{_BASE_URL}/v1/blobs/missing")
        response = httpx.Response(200, text=body, headers={"Content-Type": "application/json"}, request=request)
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=response))

        with pytest.raises(ApiResponseError) as exc_info:
            asyncio.run(client.missing_blobs([BlobRef(sha256=MethodFileMaps.CARD_SHA256, size=13)]))

        error = exc_info.value
        assert error.problem.as_wire() == make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 200}).as_wire(), topic
        assert str(error) == (
            "API POST /v1/blobs/missing failed (200): "
            "The runtime answered with the HTTP status 200 and a body that is not a problem document the client can read.\n"
            "Next step: Report this to whoever runs the runtime, with the status and the body."
        ), topic
        for shown in (str(error), json.dumps(error.problem.as_wire())):
            assert BlobWireBodies.SECRET_SIGNATURE not in shown, topic
            assert "X-Amz-Signature" not in shown, topic
        assert error.response_body == body, topic

    # ── upload_blob ──────────────────────────────────────────────

    def test_upload_blob_sends_exactly_the_target_headers(self, runner: _FakeRunner) -> None:
        """The bytes go to the named URL with the named method and headers, and nothing of the API client's: no key, no User-Agent."""
        client = self._client()
        blob = MissingBlobsResult.model_validate(BlobWireBodies.ONE_MISSING).missing[0]

        asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))

        assert len(runner.requests) == 1
        upload = runner.requests[0]
        assert (upload.method, str(upload.url), upload.content) == ("PUT", BlobWireBodies.UPLOAD_URL, MethodFileMaps.CARD)
        expected_headers = {name.lower(): value for name, value in BlobWireBodies.UPLOAD_HEADERS.items()}
        assert dict(upload.headers) == {"host": _BUCKET_HOST, "content-length": "13", **expected_headers}

    @pytest.mark.parametrize(
        ("topic", "target_headers", "status", "is_uploaded"),
        [
            ("a create-only target answering 412 already holds the bytes", {"If-None-Match": "*"}, 412, True),
            ("a create-only target named in lower case", {"if-none-match": "*"}, 412, True),
            ("a 412 from a target that asked for no condition is a failure", {}, 412, False),
            ("a refusal is a failure", {"If-None-Match": "*"}, 403, False),
        ],
    )
    def test_upload_blob_reads_the_target_answer(
        self, runner: _FakeRunner, topic: str, target_headers: dict[str, str], status: int, is_uploaded: bool
    ) -> None:
        """Only a 2xx, or a create-only target's 412, counts as uploaded; any other answer raises with the target's query left out."""
        client = self._client()
        runner.upload_status = status
        target = UploadTarget(method="PUT", url=BlobWireBodies.UPLOAD_URL, headers=target_headers)
        blob = MissingBlob(sha256=MethodFileMaps.CARD_SHA256, size=13, upload=target)

        if is_uploaded:
            asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))
            return
        with pytest.raises(BlobUploadError) as exc_info:
            asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))
        error = exc_info.value
        assert (error.sha256, error.status, error.upload_url) == (MethodFileMaps.CARD_SHA256, status, BlobWireBodies.UPLOAD_URL_WITHOUT_QUERY), topic
        assert error.response_body == "<Error><Code>AccessDenied</Code></Error>"
        # An object store's error page is no problem document, so it reads as any such answer does, by its status.
        assert error.problem.code == "client.response_unreadable", topic
        assert error.problem.as_wire()["params"] == {"status": status}
        assert str(error) == (
            f"Uploading blob {MethodFileMaps.CARD_SHA256} to {BlobWireBodies.UPLOAD_URL_WITHOUT_QUERY} failed ({status}): "
            f"The runtime answered with the HTTP status {status} and a body that is not a problem document the client can read.\n"
            "Next step: Report this to whoever runs the runtime, with the status and the body."
        )
        assert "Signature" not in str(error)

    def test_upload_blob_refuses_bytes_that_are_not_the_blob(self, mocker: MockerFixture, runner: _FakeRunner) -> None:
        """Bytes that do not hash to the blob named are refused before anything is sent, hashed once for the check and its message."""
        hashing_threads = _record_hashing(mocker)
        client = self._client()
        blob = MissingBlobsResult.model_validate(BlobWireBodies.ONE_MISSING).missing[0]
        other_bytes = b"<p>Bye</p>\n\n\n"

        with pytest.raises(PipelineRequestError) as exc_info:
            asyncio.run(client.upload_blob(blob, other_bytes))

        assert str(exc_info.value) == (
            f"The bytes given for blob {MethodFileMaps.CARD_SHA256} are not that blob: "
            f"they hash to {sha256_hex(other_bytes)} and hold 13 bytes, not 13.\n"
            "Next step: Correct the argument 'data', then try again."
        )
        assert exc_info.value.problem.as_wire()["params"] == {"argument": "data", "reason": "not_the_blob"}
        assert len(hashing_threads) == 1
        assert runner.requests == []

    def test_upload_blob_hashes_the_bytes_once_off_the_event_loop(self, mocker: MockerFixture, runner: _FakeRunner) -> None:
        """The check of the bytes runs in a thread, so a large blob does not stall the event loop while it is hashed."""
        hashing_threads = _record_hashing(mocker)
        client = self._client()
        blob = MissingBlobsResult.model_validate(BlobWireBodies.ONE_MISSING).missing[0]

        asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))

        assert len(hashing_threads) == 1
        assert hashing_threads[0] != threading.get_ident()
        assert len(runner.uploads) == 1

    def test_an_upload_error_keeps_no_credential_of_the_target(self, runner: _FakeRunner) -> None:
        """A `user:password@` in the target's authority is a credential, as a presigned query is: the error keeps neither, nor the fragment."""
        client = self._client()
        runner.upload_status = 403
        target = UploadTarget(method="PUT", url=BlobWireBodies.UPLOAD_URL_WITH_USERINFO, headers={})
        blob = MissingBlob(sha256=MethodFileMaps.CARD_SHA256, size=13, upload=target)

        with pytest.raises(BlobUploadError) as exc_info:
            asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))

        error = exc_info.value
        assert error.upload_url == BlobWireBodies.UPLOAD_URL_WITH_USERINFO_STRIPPED
        assert str(error).split("\n")[0] == (
            f"Uploading blob {MethodFileMaps.CARD_SHA256} to {BlobWireBodies.UPLOAD_URL_WITH_USERINFO_STRIPPED} failed (403): "
            "The runtime answered with the HTTP status 403 and a body that is not a problem document the client can read."
        )
        for credential in ("uploader", "pa55word", "Signature", "#part"):
            assert credential not in str(error)

    def test_an_upload_error_never_quotes_the_target_answer(self, runner: _FakeRunner) -> None:
        """An object store's refusal may echo the signature and the presigned query, so the message never quotes it: only `response_body` keeps it."""
        client = self._client()
        runner.upload_status = 403
        runner.upload_body = BlobWireBodies.SIGNATURE_MISMATCH_BODY
        target = UploadTarget(method="PUT", url=BlobWireBodies.SIGNED_UPLOAD_URL, headers={})
        blob = MissingBlob(sha256=MethodFileMaps.CARD_SHA256, size=13, upload=target)

        with pytest.raises(BlobUploadError) as exc_info:
            asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))

        error = exc_info.value
        assert error.problem.as_wire() == make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 403}).as_wire()
        assert str(error) == (
            f"Uploading blob {MethodFileMaps.CARD_SHA256} to {BlobWireBodies.UPLOAD_URL_WITHOUT_QUERY} failed (403): "
            "The runtime answered with the HTTP status 403 and a body that is not a problem document the client can read.\n"
            "Next step: Report this to whoever runs the runtime, with the status and the body."
        )
        serialized_problem = json.dumps(error.problem.as_wire())
        for secret in (
            BlobWireBodies.SECRET_SIGNATURE,
            BlobWireBodies.FAKE_ACCESS_KEY_ID,
            "SignatureDoesNotMatch",
            "StringToSign",
            "X-Amz-Signature",
        ):
            assert secret not in str(error), secret
            assert secret not in serialized_problem, secret
        assert (error.status, error.response_body) == (403, BlobWireBodies.SIGNATURE_MISMATCH_BODY)

    @pytest.mark.parametrize(
        ("topic", "failure", "expected_code", "expected_params"),
        [
            ("no connection opened", httpx.ConnectError, "client.unreachable", {"base_url": BlobWireBodies.UPLOAD_URL_WITH_USERINFO_STRIPPED}),
            ("no answer in time", httpx.ReadTimeout, "client.timeout", {"seconds": 30}),
            (
                "the connection dropped mid-answer",
                httpx.ReadError,
                "client.unreachable",
                {"base_url": BlobWireBodies.UPLOAD_URL_WITH_USERINFO_STRIPPED},
            ),
            ("a body that cannot be decoded", None, "client.unreachable", {"base_url": BlobWireBodies.UPLOAD_URL_WITH_USERINFO_STRIPPED}),
        ],
    )
    def test_an_upload_that_got_no_answer_is_an_upload_error_safe_to_repeat(
        self,
        runner: _FakeRunner,
        topic: str,
        failure: type[httpx.TransportError] | None,
        expected_code: str,
        expected_params: dict[str, Any],
    ) -> None:
        """No usable answer reads as on a route that creates nothing, a blob being named by its bytes, naming the target without its credentials."""
        client = MthdsAPIClient(api_key="test-token", base_url=_BASE_URL, request_timeout_seconds=30.0)
        runner.upload_failure = failure
        runner.upload_body_broken = failure is None
        target = UploadTarget(method="PUT", url=BlobWireBodies.UPLOAD_URL_WITH_USERINFO, headers={})
        blob = MissingBlob(sha256=MethodFileMaps.CARD_SHA256, size=13, upload=target)

        with pytest.raises(BlobUploadError) as exc_info:
            asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))

        error = exc_info.value
        assert len(runner.uploads) == 1, topic
        assert isinstance(error.__cause__, httpx.TransportError | httpx.DecodingError), topic
        assert error.problem.code == expected_code, topic
        assert error.problem.as_wire()["params"] == expected_params, topic
        assert error.problem.is_retryable, topic
        assert not error.problem.outcome_is_unknown, topic
        assert (error.sha256, error.upload_url) == (MethodFileMaps.CARD_SHA256, BlobWireBodies.UPLOAD_URL_WITH_USERINFO_STRIPPED), topic
        assert (error.status, error.status_text, error.response_body) == (None, None, None), topic
        assert str(error) == (
            f"Uploading blob {MethodFileMaps.CARD_SHA256} to {BlobWireBodies.UPLOAD_URL_WITH_USERINFO_STRIPPED} failed: {error.problem.detail}\n"
            f"Next step: {error.problem.next_step.detail}"
        ), topic
        serialized_problem = json.dumps(error.problem.as_wire())
        for credential in ("uploader", "pa55word", "Signature", "0123abcd", "#part"):
            assert credential not in str(error), topic
            assert credential not in serialized_problem, topic

    @pytest.mark.parametrize(
        ("topic", "url", "shown_url", "cause"),
        [
            (
                "a port that is no number",
                BlobWireBodies.UPLOAD_URL_WITH_INVALID_PORT,
                BlobWireBodies.UPLOAD_URL_WITH_INVALID_PORT_STRIPPED,
                httpx.InvalidURL,
            ),
            (
                "a scheme the client does not send to",
                BlobWireBodies.UPLOAD_URL_WITH_OTHER_SCHEME,
                BlobWireBodies.UPLOAD_URL_WITH_OTHER_SCHEME_STRIPPED,
                httpx.UnsupportedProtocol,
            ),
        ],
    )
    def test_an_upload_target_the_client_cannot_send_to_is_an_unusable_answer(
        self, topic: str, url: str, shown_url: str, cause: type[httpx.InvalidURL | httpx.UnsupportedProtocol]
    ) -> None:
        """Such a target is refused before anything leaves, and no repeat changes it: the answer that named it is one the client cannot use."""
        client = self._client()
        blob = MissingBlob(sha256=MethodFileMaps.CARD_SHA256, size=13, upload=UploadTarget(method="PUT", url=url, headers={}))

        with pytest.raises(BlobUploadError) as exc_info:
            asyncio.run(client.upload_blob(blob, MethodFileMaps.CARD))

        error = exc_info.value
        assert isinstance(error.__cause__, cause), topic
        assert error.problem.as_wire() == make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 200}).as_wire(), topic
        assert not error.problem.is_retryable, topic
        assert (error.upload_url, error.status, error.response_body) == (shown_url, None, None), topic
        assert str(error) == (
            f"The runner named an upload target for blob {MethodFileMaps.CARD_SHA256} that the client cannot send to: {shown_url}\n"
            "Next step: Report this to whoever runs the runtime, with the status and the body."
        ), topic
        for credential in ("uploader", "pa55word", "Signature", "0123abcd", "#part"):
            assert credential not in str(error), topic

    @pytest.mark.parametrize(("topic", "target_headers"), BlobWireBodies.UNWRITABLE_TARGET_HEADERS)
    def test_an_upload_target_whose_headers_cannot_be_written_is_an_unusable_answer(self, topic: str, target_headers: dict[str, str]) -> None:
        """Httpx's real transport refuses such a header before writing a byte, and no repeat changes it: never the retryable `client.unreachable`."""
        client = self._client()

        async def scenario() -> tuple[BlobUploadError, list[bytes]]:
            async with _silent_server() as (origin, received):
                target = UploadTarget(method="PUT", url=f"{origin}/org_1/blobs/card?X-Amz-Signature=0123abcd", headers=target_headers)
                blob = MissingBlob(sha256=MethodFileMaps.CARD_SHA256, size=13, upload=target)
                with pytest.raises(BlobUploadError) as exc_info:
                    await client.upload_blob(blob, MethodFileMaps.CARD)
            return exc_info.value, received

        error, received = asyncio.run(scenario())

        assert b"".join(received) == b"", topic
        assert error.problem.as_wire() == make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 200}).as_wire(), topic
        assert not error.problem.is_retryable, topic
        # The refusal is never chained, since h11's words quote the header's value.
        assert error.__cause__ is None, topic
        assert error.__suppress_context__, topic
        assert (error.status, error.response_body) == (None, None), topic
        assert str(error).startswith(f"The runner named an upload target for blob {MethodFileMaps.CARD_SHA256} that the client cannot send to: "), (
            topic
        )
        serialized_problem = json.dumps(error.problem.as_wire())
        for secret in (BlobWireBodies.HEADER_SECRET, "Signature", "0123abcd"):
            assert secret not in str(error), topic
            assert secret not in serialized_problem, topic

    # ── prepare_files ────────────────────────────────────────────

    def test_prepare_files_sends_a_small_tree_inline_without_asking(self, runner: _FakeRunner, tmp_path: Path) -> None:
        """A tree under the inline threshold travels whole, each file as its text or its Base64, with no round trip."""
        _write_tree(tmp_path)
        client = self._client()

        files = asyncio.run(client.prepare_files(list_method_tree(tmp_path)))

        assert files == {
            "logo.png": Base64FileEntry(base64="iVBORw0KGgo="),
            "main.mthds": MethodFileMaps.BUNDLE,
            "templates/card.html": MethodFileMaps.CARD.decode("utf-8"),
            "templates/copy.html": MethodFileMaps.CARD.decode("utf-8"),
        }
        assert list(files) == ["logo.png", "main.mthds", "templates/card.html", "templates/copy.html"]
        assert runner.requests == []

    def test_prepare_files_sends_inline_to_a_runner_without_a_blob_store(self, runner: _FakeRunner, tmp_path: Path) -> None:
        """A tree over the threshold still travels inline when the runner's handshake declares no blob store."""
        _write_tree(tmp_path)
        runner.blob_store = False
        client = self._client()

        files = asyncio.run(client.prepare_files(list_method_tree(tmp_path), inline_max_bytes=0))

        assert files["logo.png"] == Base64FileEntry(base64="iVBORw0KGgo=")
        assert files["main.mthds"] == MethodFileMaps.BUNDLE
        assert runner.api_paths == ["/v1/version"]

    def test_prepare_files_uploads_what_the_runner_lacks_then_names_every_file_by_hash(self, runner: _FakeRunner, tmp_path: Path) -> None:
        """Over the threshold, against a blob store: one missing-blobs check naming the tree, each missing blob uploaded once, every file by hash."""
        _write_tree(tmp_path)
        tree = list_method_tree(tmp_path)
        bundle_bytes = MethodFileMaps.BUNDLE.encode("utf-8")
        runner.held[sha256_hex(bundle_bytes)] = bundle_bytes
        client = self._client()

        async def scenario() -> dict[str, Any]:
            async with client:
                files = await client.prepare_files(tree, inline_max_bytes=0)
                await client.execute(files=files)
                return files

        files = asyncio.run(scenario())

        assert files == {tree_file.path: HashFileEntry(sha256=tree_file.sha256, size=tree_file.size) for tree_file in tree.files}
        assert runner.api_paths == ["/v1/version", "/v1/blobs/missing", "/v1/execute"]
        asked = json.loads(runner.requests[1].content)
        logo_sha256 = sha256_hex(MethodFileMaps.LOGO)
        assert asked == {
            "blobs": [
                {"sha256": logo_sha256, "size": len(MethodFileMaps.LOGO)},
                {"sha256": sha256_hex(bundle_bytes), "size": len(bundle_bytes)},
                {"sha256": MethodFileMaps.CARD_SHA256, "size": 13},
            ],
            "digest": tree.digest,
        }
        uploaded = {upload.url.path.rsplit("/", 1)[-1]: upload.content for upload in runner.uploads}
        assert uploaded == {logo_sha256: MethodFileMaps.LOGO, MethodFileMaps.CARD_SHA256: MethodFileMaps.CARD}
        assert all("authorization" not in upload.headers for upload in runner.uploads)
        execute_request = next(request for request in runner.requests if request.url.path == "/v1/execute")
        assert execute_request.content == b'{"files":' + to_json(files) + b"}"

    def test_prepare_files_counts_base64_as_the_request_spends_it(self, mocker: MockerFixture, runner: _FakeRunner, tmp_path: Path) -> None:
        """A binary file just under the threshold raw is a third larger as Base64, so its tree goes by hash.

        Each file is read and checked once: the bytes read to measure the map are the ones uploaded, never hashed again.
        """
        (tmp_path / "main.mthds").write_text(MethodFileMaps.BUNDLE, encoding="utf-8")
        (tmp_path / "data.bin").write_bytes(MethodFileMaps.BINARY_UNDER_THRESHOLD)
        tree = list_method_tree(tmp_path)
        assert sum(tree_file.size for tree_file in tree.files) < DEFAULT_INLINE_TREE_MAX_BYTES
        hashing_threads = _record_hashing(mocker)
        client = self._client()

        files = asyncio.run(client.prepare_files(tree))

        assert files == {tree_file.path: HashFileEntry(sha256=tree_file.sha256, size=tree_file.size) for tree_file in tree.files}
        assert runner.api_paths == ["/v1/version", "/v1/blobs/missing"]
        assert sorted(upload.content for upload in runner.uploads) == sorted(
            [MethodFileMaps.BUNDLE.encode("utf-8"), MethodFileMaps.BINARY_UNDER_THRESHOLD]
        )
        assert len(hashing_threads) == len(tree.files)

    @pytest.mark.parametrize(
        ("topic", "headroom", "expected_api_paths"),
        [
            ("a map exactly at the threshold travels inline", 0, []),
            ("a map one byte over it travels by hash", -1, ["/v1/version", "/v1/blobs/missing"]),
        ],
    )
    def test_prepare_files_from_contents_counts_the_map_with_its_escapes(
        self, runner: _FakeRunner, topic: str, headroom: int, expected_api_paths: list[str]
    ) -> None:
        """The inline map is measured as JSON with no whitespace, in UTF-8: escapes, multi-byte characters, Base64 text, keys and all."""
        contents = {"main.mthds": MethodFileMaps.ESCAPED_TEXT, "logo.png": MethodFileMaps.LOGO}
        wire_map = {"logo.png": {"base64": "iVBORw0KGgo="}, "main.mthds": MethodFileMaps.ESCAPED_TEXT.decode("utf-8")}
        encoded_size = len(json.dumps(wire_map, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        assert encoded_size > sum(len(data) for data in contents.values())
        client = self._client()

        files = asyncio.run(client.prepare_files_from_contents(contents, inline_max_bytes=encoded_size + headroom))

        assert runner.api_paths == expected_api_paths, topic
        if not expected_api_paths:
            assert files == {"logo.png": Base64FileEntry(base64="iVBORw0KGgo="), "main.mthds": MethodFileMaps.ESCAPED_TEXT.decode("utf-8")}

    @pytest.mark.parametrize(
        ("topic", "inline_max_bytes", "expected_hash_count"),
        [
            ("inline, every file read once", 1 << 20, 4),
            ("by hash, each missing blob read once and never hashed again for its upload", 0, 3),
        ],
    )
    @pytest.mark.usefixtures("runner")
    def test_prepare_files_reads_and_hashes_off_the_event_loop(
        self, mocker: MockerFixture, tmp_path: Path, topic: str, inline_max_bytes: int, expected_hash_count: int
    ) -> None:
        """Reading a file and checking its hash run in a thread, so a large tree does not stall the event loop."""
        _write_tree(tmp_path)
        tree = list_method_tree(tmp_path)
        hashing_threads = _record_hashing(mocker)
        client = self._client()

        asyncio.run(client.prepare_files(tree, inline_max_bytes=inline_max_bytes))

        assert len(hashing_threads) == expected_hash_count, topic
        assert threading.get_ident() not in hashing_threads

    @pytest.mark.parametrize(
        ("topic", "blob_store", "inline_max_bytes"),
        [
            ("inline", False, 1 << 20),
            ("by hash", True, 0),
        ],
    )
    def test_prepare_files_refuses_a_file_changed_after_listing(
        self, runner: _FakeRunner, tmp_path: Path, topic: str, blob_store: bool, inline_max_bytes: int
    ) -> None:
        """What travels is the tree the digest names: a file whose bytes changed since the listing is refused, never sent."""
        _write_tree(tmp_path)
        tree = list_method_tree(tmp_path)
        (tmp_path / "logo.png").write_bytes(b"GIF89a")
        runner.blob_store = blob_store
        client = self._client()

        with pytest.raises(TreeSourceError, match=r"'logo\.png' .* changed after the tree was listed"):
            asyncio.run(client.prepare_files(tree, inline_max_bytes=inline_max_bytes))

        assert all(upload.url.path.rsplit("/", 1)[-1] != sha256_hex(MethodFileMaps.LOGO) for upload in runner.uploads), topic

    @pytest.mark.parametrize(
        ("topic", "upload_status", "upload_failure", "expected_code"),
        [
            ("a target's refusal", 403, None, "client.response_unreadable"),
            ("an upload that got no answer", None, httpx.ConnectError, "client.unreachable"),
        ],
    )
    def test_prepare_files_raises_the_first_failed_upload(
        self,
        runner: _FakeRunner,
        tmp_path: Path,
        topic: str,
        upload_status: int | None,
        upload_failure: type[httpx.TransportError] | None,
        expected_code: str,
    ) -> None:
        """A failed upload, refused or unanswered, surfaces as the typed upload error once every upload has run to its end."""
        _write_tree(tmp_path)
        runner.upload_status = upload_status
        runner.upload_failure = upload_failure
        client = self._client()

        with pytest.raises(BlobUploadError) as exc_info:
            asyncio.run(client.prepare_files(list_method_tree(tmp_path), inline_max_bytes=0))

        assert exc_info.value.problem.code == expected_code, topic
        assert len(runner.uploads) == 3, topic

    @pytest.mark.parametrize(("topic", "target_headers"), BlobWireBodies.UNWRITABLE_TARGET_HEADERS)
    def test_prepare_files_raises_a_target_whose_headers_cannot_be_written(
        self, mocker: MockerFixture, runner: _FakeRunner, tmp_path: Path, topic: str, target_headers: dict[str, str]
    ) -> None:
        """A runner naming targets whose headers cannot be written gave an answer the client cannot use, which no retry of the tree changes."""
        _write_tree(tmp_path)
        tree = list_method_tree(tmp_path)
        runner.target_headers = target_headers
        client = self._client()
        # The runner's routes stay on the fake, while the uploads go through httpx's real transport, whose h11 refuses a line break.
        mocker.patch.object(client, "_make_upload_client", side_effect=_REAL_ASYNC_CLIENT)

        async def scenario() -> tuple[BlobUploadError, list[bytes]]:
            async with _silent_server() as (origin, received):
                runner.target_origin = origin
                with pytest.raises(BlobUploadError) as exc_info:
                    await client.prepare_files(tree, inline_max_bytes=0)
            return exc_info.value, received

        error, received = asyncio.run(scenario())

        assert b"".join(received) == b"", topic
        assert error.problem.as_wire() == make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 200}).as_wire(), topic
        assert not error.problem.is_retryable, topic
        for secret in (BlobWireBodies.HEADER_SECRET, "Signature", "0123abcd"):
            assert secret not in str(error), topic

    @pytest.mark.parametrize(
        ("topic", "unrequested_sha256"),
        [
            ("a hash the tree does not hold", "f" * 64),
            ("a hash the tree holds, at another size", MethodFileMaps.CARD_SHA256),
        ],
    )
    def test_prepare_files_refuses_a_blob_it_did_not_ask_for(self, runner: _FakeRunner, tmp_path: Path, topic: str, unrequested_sha256: str) -> None:
        """An answer naming a blob the request did not list, by hash or by size, is an unreadable success, and nothing is uploaded."""
        _write_tree(tmp_path)
        runner.unrequested_missing = [unrequested_sha256]
        client = self._client()

        with pytest.raises(ApiResponseError) as exc_info:
            asyncio.run(client.prepare_files(list_method_tree(tmp_path), inline_max_bytes=0))

        error = exc_info.value
        assert runner.uploads == [], topic
        assert error.problem.as_wire() == make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 200}).as_wire(), topic
        assert (error.status, error.request_url, error.request_id) == (200, f"{_BASE_URL}/v1/blobs/missing", _MISSING_BLOBS_REQUEST_ID), topic
        assert json.loads(error.response_body)["missing"][-1]["sha256"] == unrequested_sha256, topic
        assert str(error).split("\n")[0] == (
            "API POST /v1/blobs/missing failed (200): "
            "The runtime answered with the HTTP status 200 and a body that is not a problem document the client can read."
        ), topic

    def test_prepare_files_refuses_a_tree_not_listed_from_a_directory(self, runner: _FakeRunner) -> None:
        """A tree read from a map has no files on disk: its bytes go through `prepare_files_from_contents`."""
        tree = read_file_map(to_json(MethodFileMaps.ONE_BUNDLE).decode("utf-8")).tree
        client = self._client()

        with pytest.raises(PipelineRequestError, match="prepare_files_from_contents") as exc_info:
            asyncio.run(client.prepare_files(tree))

        assert runner.requests == []
        assert exc_info.value.problem.as_wire()["params"] == {"argument": "tree", "reason": "not_listed_from_a_directory"}

    def test_prepare_files_from_contents_sends_bytes_at_hand_by_hash(self, runner: _FakeRunner) -> None:
        """Bytes at hand follow the same rule: over the threshold, against a blob store, uploaded once and named by hash."""
        contents = {"main.mthds": MethodFileMaps.BUNDLE.encode("utf-8"), "logo.png": MethodFileMaps.LOGO}
        client = self._client()

        files = asyncio.run(client.prepare_files_from_contents(contents, inline_max_bytes=0))

        assert files == {tree_path: HashFileEntry(sha256=sha256_hex(data), size=len(data)) for tree_path, data in sorted(contents.items())}
        assert {upload.content for upload in runner.uploads} == set(contents.values())

    def test_prepare_files_from_contents_refuses_an_empty_tree(self, runner: _FakeRunner) -> None:
        client = self._client()

        with pytest.raises(PipelineRequestError, match="holds no file") as exc_info:
            asyncio.run(client.prepare_files_from_contents({}))

        assert runner.requests == []
        assert exc_info.value.problem.as_wire()["params"] == {"argument": "contents", "reason": "empty"}
