import dataclasses
from typing import assert_type

from typed_result import Err
from typed_result import Ok
from typed_result import Result


@dataclasses.dataclass(frozen=True, slots=True)
class Missing:
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class Invalid:
    pass


type DomainError = Missing | Invalid


def render(result: Result[int, DomainError]) -> str:
    match result:
        case Ok(value=value):
            assert_type(value, int)
            return str(value)
        case Err(error=error):
            assert_type(error, Missing | Invalid)
            match error:
                case Missing():
                    return "missing"
                case Invalid():
                    return "invalid"


def use_methods(result: Result[int, str]) -> None:
    assert_type(result.map(str), Ok[str] | Err[str])
    assert_type(result.map_err(len), Ok[int] | Err[int])
    assert_type(result.unwrap(), int)
    assert_type(result.unwrap_err(), str)
    assert_type(result.unwrap_or(0), int)
    assert_type(result.unwrap_or_raise(ValueError), int)
