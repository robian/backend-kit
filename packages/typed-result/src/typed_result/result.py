from __future__ import annotations

import dataclasses
import typing
from collections.abc import Callable


@typing.final
class UnwrapError(Exception):
    """Raised when unwrapping the absent variant of a result."""

    def __init__(self, message: str, value: object) -> None:
        self.value = value
        super().__init__(f"{message}: {value!r}")


@typing.final
@dataclasses.dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    def is_ok(self) -> typing.Literal[True]:
        return True

    def is_err(self) -> typing.Literal[False]:
        return False

    def map[U](self, function: Callable[[T], U]) -> Ok[U]:
        return Ok(function(self.value))

    def map_err[F](self, function: Callable[[typing.Never], F]) -> Ok[T]:
        del function
        return self

    def unwrap(self) -> T:
        return self.value

    def unwrap_err(self) -> typing.Never:
        raise UnwrapError("called unwrap_err() on an Ok value", self.value)

    def unwrap_or(self, default: object) -> T:
        del default
        return self.value

    def unwrap_or_raise(
        self,
        exception: Callable[[typing.Never], BaseException],
    ) -> T:
        del exception
        return self.value


@typing.final
@dataclasses.dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

    def is_ok(self) -> typing.Literal[False]:
        return False

    def is_err(self) -> typing.Literal[True]:
        return True

    def map[U](self, function: Callable[[typing.Never], U]) -> Err[E]:
        del function
        return self

    def map_err[F](self, function: Callable[[E], F]) -> Err[F]:
        return Err(function(self.error))

    def unwrap(self) -> typing.Never:
        raise UnwrapError("called unwrap() on an Err value", self.error)

    def unwrap_err(self) -> E:
        return self.error

    def unwrap_or[U](self, default: U) -> U:
        return default

    def unwrap_or_raise(
        self,
        exception: Callable[[E], BaseException],
    ) -> typing.Never:
        raise exception(self.error)


type Result[T, E] = Ok[T] | Err[E]
