import pytest

from src.modules.csm.duties.attestation import AttestationSequence, AttestationStatus


def test_initialization():
    seq = AttestationSequence(5)
    assert len(seq) == 5
    assert all(status == AttestationStatus.NO_DUTY for status in seq)


def test_str_representation():
    seq = AttestationSequence(5)
    seq.set_duty_status(0, AttestationStatus.MISSED)
    seq.set_duty_status(1, AttestationStatus.INCLUDED)
    assert str(seq) == "AttestationSequence(missed=1, included=1)"


def test_set_and_get_duty_status():
    seq = AttestationSequence(5)
    seq.set_duty_status(2, AttestationStatus.INCLUDED)
    assert seq.get_duty_status(2) == AttestationStatus.INCLUDED
    seq.set_duty_status(3, AttestationStatus.MISSED)
    assert seq.get_duty_status(3) == AttestationStatus.MISSED


def test_count_missed():
    seq = AttestationSequence(5)
    seq.set_duty_status(1, AttestationStatus.MISSED)
    seq.set_duty_status(3, AttestationStatus.MISSED)
    assert seq.count_missed() == 2
    assert seq.count_missed(0, 3) == 1
    assert seq.count_missed(4) == 0


def test_count_included():
    seq = AttestationSequence(5)
    seq.set_duty_status(0, AttestationStatus.INCLUDED)
    seq.set_duty_status(2, AttestationStatus.INCLUDED)
    assert seq.count_included() == 2
    assert seq.count_included(1, 4) == 1
    assert seq.count_included(3) == 0


def test_invalid_range():
    seq = AttestationSequence(5)
    with pytest.raises(ValueError):
        seq.count_missed(3, 2)
    with pytest.raises(ValueError):
        seq.count_included(-1, 3)
    with pytest.raises(ValueError):
        seq.count_missed(0, 6)
