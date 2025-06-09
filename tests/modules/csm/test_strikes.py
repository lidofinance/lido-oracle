import pytest
from eth_utils.types import is_list_like

from src.modules.csm.types import StrikesList


@pytest.mark.unit
def test_create_empty():
    strikes = StrikesList([])
    assert not len(strikes)

    strikes = StrikesList()
    assert not len(strikes)


@pytest.mark.unit
def test_create_not_empty():
    strikes = StrikesList([1, 2, 3])
    assert strikes == [1, 2, 3]


@pytest.mark.unit
def test_eq():
    assert StrikesList([1, 2, 3]) == StrikesList([1, 2, 3])
    assert StrikesList([1, 2, 3]) != StrikesList([1, 2])
    assert StrikesList([1, 2, 3]) == [1, 2, 3]


@pytest.mark.unit
def test_create_maxlen_smaller_than_iterable():
    strikes = StrikesList([1, 2, 3], maxlen=5)
    assert strikes == [1, 2, 3, 0, 0]


@pytest.mark.unit
def test_create_maxlen_larger_than_iterable():
    strikes = StrikesList([1, 2, 3], maxlen=2)
    assert strikes == [1, 2]


@pytest.mark.unit
def test_create_resize_to_smaller():
    strikes = StrikesList([1, 2, 3])
    strikes.resize(2)
    assert strikes == [1, 2]


@pytest.mark.unit
def test_create_resize_to_larger():
    strikes = StrikesList([1, 2, 3])
    strikes.resize(5)
    assert strikes == [1, 2, 3, 0, 0]


@pytest.mark.unit
def test_push_element():
    strikes = StrikesList([1, 2, 3])
    strikes.push(4)
    assert strikes == [4, 1, 2, 3]


@pytest.mark.unit
def test_is_list_like():
    strikes = StrikesList([1, 2, 3])
    assert is_list_like(strikes)

    arr = [4, 5]
    arr.extend(strikes)
    assert arr == [4, 5, 1, 2, 3]

    assert sum(strikes) == 6
