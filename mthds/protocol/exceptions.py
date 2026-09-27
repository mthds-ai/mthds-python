from __future__ import annotations

from typing import Any

from typing_extensions import override


class PipelineRequestError(Exception):
    """Raised when a request to an MTHDS runner is malformed or fails client-side.

    A subclass survives pickling and copying whatever its `__init__` asks for: the error is rebuilt
    from its message and its instance attributes without calling `__init__` again, so a subclass
    whose `__init__` takes required or keyword-only arguments still crosses a process boundary (a
    process pool, a task queue) as itself rather than as a `TypeError`. A subclass that defines its
    own `__new__` or keeps state in `__slots__` provides its own `__reduce__`.
    """

    @override
    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild_request_error, (type(self), self.args), self.__dict__)


def _rebuild_request_error(cls: type[PipelineRequestError], args: tuple[Any, ...]) -> PipelineRequestError:
    """Recreate a request error from its `args`, leaving its attributes to the pickled state."""
    return cls.__new__(cls, *args)
