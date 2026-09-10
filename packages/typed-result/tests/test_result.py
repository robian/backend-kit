from typing import Never
from typing import assert_never

import pytest

from typed_result import Err
from typed_result import Ok
from typed_result import UnwrapError


def test_ok() -> None:
    result = Ok(3)

    assert result.is_ok()
    assert not result.is_err()
    assert result.map(str) == Ok("3")
    assert result.map_err(_never_to_str) is result
    assert result.unwrap() == 3
    assert result.unwrap_or(4) == 3
    assert result.unwrap_or_raise(_never_to_exception) == 3

    with pytest.raises(UnwrapError) as raised:
        result.unwrap_err()

    assert raised.value.value == 3


def test_err() -> None:
    result = Err("invalid")

    assert not result.is_ok()
    assert result.is_err()
    assert result.map(_never_to_str) is result
    assert result.map_err(str.upper) == Err("INVALID")
    assert result.unwrap_err() == "invalid"
    assert result.unwrap_or(4) == 4

    with pytest.raises(UnwrapError) as unwrap_error:
        result.unwrap()

    assert unwrap_error.value.value == "invalid"

    with pytest.raises(ValueError, match="invalid"):
        result.unwrap_or_raise(ValueError)


def _never_to_str(value: Never) -> str:
    assert_never(value)


def _never_to_exception(value: Never) -> BaseException:
    assert_never(value)
