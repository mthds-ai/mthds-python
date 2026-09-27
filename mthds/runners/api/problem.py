"""The problem document of a refused request — what a runner says when it answers non-2xx.

The MTHDS Protocol answers every error as an RFC 9457 (formerly 7807) `application/problem+json`
document: the standard's own members `type`, `title`, `status`, `detail` and `instance`. A runner
adds extension members that classify the failure, and the reference runner sends these: `request_id`
(the correlation id to hand to support), `error_type` (its exception class), `error_domain` (who can
fix it: `input`, `config` or `runtime`), `retryable` (whether the same request can succeed later),
`user_action` (the next step) and, when it refuses to run an invalid method, `validation_errors[]`.

`ProblemDocument` reads those members out of a response body, leniently: a member is kept only when
it has the type the document gives it, so a malformed member reads as absent rather than as a wrong
value, and a body that is not a problem document at all (an HTML gateway page, plain text, an empty
body) reads as a document with no members. The whole decoded object stays on `members`, so a member
this package does not name is never lost. `MthdsAPIClient` builds every `ApiResponseError` from it,
and a client built on this one reads the same members through the same parse.

These shapes mirror the problem members the `mthds` npm package's `ApiResponseError` keeps, in Python
naming: `type_uri` for the problem's `type`, which would shadow the builtin, and snake case throughout.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Self, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from mthds.protocol.models import ValidationDiagnostic

if TYPE_CHECKING:
    import httpx

REQUEST_ID_HEADER = "x-request-id"


class UserAction(BaseModel):
    """What the runner says the caller should do next — the problem document's `user_action` member.

    `kind` is the runner's coarse category of advice. The reference runner emits `wait_and_retry`,
    `check_billing`, `check_credentials`, `change_input`, `change_model`, `contact_support` and
    `unknown`; the vocabulary is the runner's, so it stays an open string. `detail` is the advice
    itself, in words, and is never empty: a `user_action` without it is no next step and reads as
    absent. Members a runner adds beyond these two ride `model_extra`.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    kind: str
    detail: str


class ProblemDocument(BaseModel):
    """The members of a non-2xx answer's problem document, each `None` when the answer did not carry it.

    - `type_uri`, `title`, `instance`: the RFC 9457 members — the stable URI naming the error class,
      its short human label, and the occurrence (a request path or a request URN).
    - `server_message`: the reason for this occurrence, the problem's `detail` string. Older answers
      nest it as `{"detail": {"error_type": ..., "message": ...}}` or put a top-level `message`; both
      are read too.
    - `error_type`: the runner's exception class name, from the same places.
    - `request_id`: the body's `request_id`, or the `X-Request-ID` response header when the body
      carries none (a gateway error page, a body that is no problem document).
    - `error_domain`, `retryable`, `user_action`: who can fix the failure, whether a retry can
      succeed (`None` means unknown, which is not `False`), and what to do next.
    - `validation_errors`: the per-error diagnostics of a run route's refusal to run an invalid
      method, typed as the protocol's neutral `ValidationDiagnostic`, whose locators (`pipe_code`,
      `field_path`, `suggestions`, …) ride `model_extra`. The list is kept only when every item is a
      diagnostic, so a list that is present is the runner's whole list.
    - `members`: the decoded JSON object whole, `None` when the body was not one.
    """

    model_config = ConfigDict(frozen=True)

    type_uri: str | None = None
    title: str | None = None
    instance: str | None = None
    server_message: str | None = None
    error_type: str | None = None
    request_id: str | None = None
    error_domain: str | None = None
    retryable: bool | None = None
    user_action: UserAction | None = None
    validation_errors: list[ValidationDiagnostic] | None = None
    members: dict[str, Any] | None = None

    @classmethod
    def make_from_response(cls, response: httpx.Response) -> Self:
        """Read the problem members of a response, with the `X-Request-ID` header as the request id's fallback.

        Args:
            response: The runner's non-2xx answer.

        Returns:
            The members the body carries, and the header's request id when the body names none.
        """
        document = cls.make_from_body(response.text)
        if document.request_id is not None:
            return document
        header_request_id = response.headers.get(REQUEST_ID_HEADER, "").strip()
        if not header_request_id:
            return document
        return document.model_copy(update={"request_id": header_request_id})

    @classmethod
    def make_from_body(cls, body: str) -> Self:
        """Read the problem members of a response body, leniently.

        Args:
            body: The response body as text.

        Returns:
            The members the body carries; a body that is not a JSON object carries none.
        """
        root = _decode_object(body)
        if root is None:
            return cls()

        error_type: str | None = None
        server_message: str | None = None
        detail = root.get("detail")
        if isinstance(detail, dict):
            detail_object = cast("dict[str, Any]", detail)
            error_type = _string_member(detail_object, "error_type")
            server_message = _string_member(detail_object, "message")
        elif isinstance(detail, str):
            server_message = detail
        if error_type is None:
            error_type = _string_member(root, "error_type")
        if server_message is None:
            server_message = _string_member(root, "message")

        raw_retryable = root.get("retryable")
        return cls(
            type_uri=_non_empty_string_member(root, "type"),
            title=_non_empty_string_member(root, "title"),
            instance=_non_empty_string_member(root, "instance"),
            server_message=server_message,
            error_type=error_type,
            request_id=_non_empty_string_member(root, "request_id"),
            error_domain=_non_empty_string_member(root, "error_domain"),
            retryable=raw_retryable if isinstance(raw_retryable, bool) else None,
            user_action=_user_action_of(root.get("user_action")),
            validation_errors=_validation_errors_of(root.get("validation_errors")),
            members=root,
        )


# Built once at import: the parse path of a problem's `validation_errors[]` into the protocol's neutral item.
_VALIDATION_DIAGNOSTICS_ADAPTER: TypeAdapter[list[ValidationDiagnostic]] = TypeAdapter(list[ValidationDiagnostic])


def _decode_object(body: str) -> dict[str, Any] | None:
    """Decode a body into its JSON object, or `None` for an empty, non-JSON or non-object body."""
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return cast("dict[str, Any]", parsed)


def _string_member(members: dict[str, Any], key: str) -> str | None:
    """A string member, or `None` when it is absent or not a string."""
    value = members.get(key)
    return value if isinstance(value, str) else None


def _non_empty_string_member(members: dict[str, Any], key: str) -> str | None:
    """A non-empty string member, or `None` when it is absent, empty or not a string."""
    return _string_member(members, key) or None


def _user_action_of(value: Any) -> UserAction | None:
    """A `user_action` member, kept only whole: an object with a string `kind` and a non-empty string `detail`."""
    if not isinstance(value, dict):
        return None
    action = cast("dict[str, Any]", value)
    kind = action.get("kind")
    detail = action.get("detail")
    if not isinstance(kind, str) or not isinstance(detail, str) or not detail:
        return None
    return UserAction.model_validate(action)


def _validation_errors_of(value: Any) -> list[ValidationDiagnostic] | None:
    """A `validation_errors` member, kept only when it is a list whose every item is a diagnostic."""
    if not isinstance(value, list):
        return None
    try:
        return _VALIDATION_DIAGNOSTICS_ADAPTER.validate_python(value)
    except ValidationError:
        return None
