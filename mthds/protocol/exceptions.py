from __future__ import annotations

from typing import TYPE_CHECKING, Any

from typing_extensions import override

if TYPE_CHECKING:
    from mthds.protocol.problem.models import Problem


class PipelineRequestError(Exception):
    """The root of every error a request to an MTHDS runner raises, carrying the failure as a problem.

    `problem` is the protocol's problem document for the failure: the runtime's own when it answered
    with one, and otherwise the problem the client states for it under a registered code, such as
    `client.argument_invalid` for an argument refused before any request left (the code this class
    carries when it is raised bare), `client.unreachable` for a runtime no connection reached, or
    `client.response_unreadable` for an answer that is no problem document. A program branches on
    `problem.code`, and on `problem.effective_domain`, `problem.effective_retry` and
    `problem.is_retryable`, never on the wording of the message, which is for a person: `str(exc)`
    is the message given, then the problem's next step on its own line, `Next step: …`, whichever
    error of this package raised it.

    A subclass survives pickling and copying whatever its `__init__` asks for: the error is rebuilt
    from its message and its instance attributes without calling `__init__` again, so a subclass
    whose `__init__` takes required or keyword-only arguments still crosses a process boundary (a
    process pool, a task queue) as itself rather than as a `TypeError`. A subclass that defines its
    own `__new__` or keeps state in `__slots__` provides its own `__reduce__`.
    """

    def __init__(self, message: str, *, problem: Problem) -> None:
        """Build the error; its message is `message` followed by the problem's next step on its own line.

        Args:
            message: What failed, for a person.
            problem: The failure as the protocol's problem document.
        """
        super().__init__(f"{message}\nNext step: {problem.next_step.detail}")
        self.problem = problem

    @override
    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild_request_error, (type(self), self.args), self.__dict__)


def _rebuild_request_error(cls: type[PipelineRequestError], args: tuple[Any, ...]) -> PipelineRequestError:
    """Recreate a request error from its `args`, leaving its attributes to the pickled state."""
    return cls.__new__(cls, *args)


def make_argument_invalid_error(message: str, *, argument: str, reason: str) -> PipelineRequestError:
    """The error for an argument refused before any request left: `client.argument_invalid`.

    Args:
        message: What is wrong with the argument, for a person.
        argument: The argument refused, by name.
        reason: Why it was refused, as an identifier such as `not_a_string` or `mutually_exclusive`.

    Returns:
        A `PipelineRequestError` carrying the problem `client.argument_invalid` with `argument` and `reason`.
    """
    # The registry loads when an argument is refused rather than when this module does: every protocol
    # module imports this one, and a light one such as `mthds.protocol.options`, which needs only the
    # standard library, would otherwise load the whole generated registry, and pydantic with it.
    from mthds.protocol.problem.client_problems import make_client_problem  # ruff: ignore[import-outside-top-level]
    from mthds.protocol.problem.registry import CoreCode  # ruff: ignore[import-outside-top-level]

    problem = make_client_problem(CoreCode.CLIENT_ARGUMENT_INVALID, params={"argument": argument, "reason": reason})
    return PipelineRequestError(message, problem=problem)
