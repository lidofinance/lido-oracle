from enum import Enum
from typing import NewType

EpochIndexInFrame = NewType('EpochIndexInFrame', int)


class AttestationStatus(Enum):
    NO_DUTY = None
    MISSED = False
    INCLUDED = True


def calc_performance(included: int, missed: int) -> float:
    all_ = missed + included
    return included / all_ if all_ else 0


class AttestationSequence(list):
    """
    Duties sequence for a CSM performance oracle frame for validators.

    It is bits sequence where each pair of bits represents the duty status of a validator for a specific epoch:
     - None - no duty
     - False - missed. assigned but not included attestation
     - True - included attestation

    Every index in the sequence corresponds to epoch index in report frame.
    For example:
     Report frame is [100000 epoch, ..., 100510 epoch],
     We need to write duty status for epoch 100000 at index 0, for epoch 100001 at index 1, and so on.
    """

    def __init__(self, size: int):
        super().__init__([AttestationStatus.NO_DUTY] * size)

    def __str__(self):
        missed, included = self.count_missed(), self.count_included()
        return f"{self.__class__.__name__}({missed=}, {included=})"

    def _validate_range(self, from_index: EpochIndexInFrame, to_index: EpochIndexInFrame):
        if from_index < 0 or to_index > len(self) or from_index >= to_index:
            raise ValueError("Invalid range for from_index and to_index")

    def count_missed(
        self, from_index: EpochIndexInFrame = EpochIndexInFrame(0), to_index: EpochIndexInFrame | None = None
    ):
        if to_index is None:
            to_index = EpochIndexInFrame(len(self))
        self._validate_range(from_index, to_index)
        return self[from_index:to_index].count(AttestationStatus.MISSED)

    def count_included(
        self, from_index: EpochIndexInFrame = EpochIndexInFrame(0), to_index: EpochIndexInFrame | None = None
    ):
        if to_index is None:
            to_index = EpochIndexInFrame(len(self))
        self._validate_range(from_index, to_index)
        return self[from_index:to_index].count(AttestationStatus.INCLUDED)

    def get_duty_status(self, epoch_index: EpochIndexInFrame) -> AttestationStatus:
        return self[epoch_index]

    def set_duty_status(self, epoch_index: EpochIndexInFrame, duty_status: AttestationStatus):
        self[epoch_index] = duty_status
