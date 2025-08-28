import pytest

from src.utils.range import sequence


@pytest.mark.unit
def test_sequence():
    assert list(sequence(0, 3)) == [0, 1, 2, 3]
    assert list(sequence(1, 3)) == [1, 2, 3]
    assert list(sequence(3, 3)) == [3]

    assert list(sequence(-3, -3)) == [-3]
    assert list(sequence(-3, -1)) == [-3, -2, -1]
    assert list(sequence(-3, 0)) == [-3, -2, -1, 0]


@pytest.mark.unit
def test_sequence_raises():
    with pytest.raises(ValueError, match="start=3 > stop=1"):
        sequence(3, 1)
