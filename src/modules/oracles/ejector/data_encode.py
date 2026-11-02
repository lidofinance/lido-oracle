from dataclasses import dataclass

from src.constants import MAX_EFFECTIVE_BALANCE_ELECTRA, MIN_ACTIVATION_BALANCE
from src.types import Gwei, NodeOperatorId, StakingModuleId


MODULE_ID_LENGTH = 3
NODE_OPERATOR_ID_LENGTH = 5
KEY_INDEX_LENGTH = 8
AMOUNT_LENGTH = 8
RECORD_LENGTH = MODULE_ID_LENGTH + NODE_OPERATOR_ID_LENGTH + KEY_INDEX_LENGTH + AMOUNT_LENGTH

# VEBO rejects reports above this count: every record is written to the TriggerableWithdrawalsBus
# storage, and larger reports do not fit safely into a block.
MAX_REQUESTS_PER_REPORT = 400

# The CL never takes a validator below MIN_ACTIVATION_BALANCE, and balance above
# MAX_EFFECTIVE_BALANCE is swept automatically, so no PWR needs more than the difference.
MAX_PWR_AMOUNT = Gwei(MAX_EFFECTIVE_BALANCE_ELECTRA - MIN_ACTIVATION_BALANCE)

# `amount == 0` encodes a full withdrawal request (FWR).
FWR_AMOUNT = Gwei(0)


@dataclass(frozen=True)
class WithdrawalRequest:
    module_id: StakingModuleId
    node_operator_id: NodeOperatorId
    key_index: int
    amount: Gwei

    @property
    def is_full(self) -> bool:
        return self.amount == FWR_AMOUNT


class InvalidWithdrawalRequestsError(ValueError):
    pass


def encode_data(requests: list[WithdrawalRequest]) -> bytes:
    """
    Encodes withdrawal requests for the VEBO report.

    Records keep the input order: VEBO appends them to the TriggerableWithdrawalsBus FIFO queue
    in report order, so the order is the execution priority and must not be changed here.

    MSB <------------------------------------------------ LSB
    |  3 bytes   |  5 bytes   |  8 bytes   |    8 bytes     |
    |  moduleId  |  nodeOpId  |  keyIndex  |  amount (gwei) |

    amount == 0 is a full withdrawal (FWR), amount > 0 is a partial withdrawal (PWR).
    """
    validate_requests(requests)

    return b''.join(
        r.module_id.to_bytes(MODULE_ID_LENGTH)
        + r.node_operator_id.to_bytes(NODE_OPERATOR_ID_LENGTH)
        + r.key_index.to_bytes(KEY_INDEX_LENGTH)
        + r.amount.to_bytes(AMOUNT_LENGTH)
        for r in requests
    )


def validate_requests(requests: list[WithdrawalRequest]) -> None:
    """
    Rejects reports that VEBO would revert, and duplicates that VEBO no longer catches:
    the old sort-order check that guaranteed uniqueness is removed.
    """
    if len(requests) > MAX_REQUESTS_PER_REPORT:
        raise InvalidWithdrawalRequestsError(
            f'Too many requests in report: {len(requests)} > {MAX_REQUESTS_PER_REPORT}.'
        )

    seen: set[tuple[StakingModuleId, NodeOperatorId, int]] = set()
    for r in requests:
        key = (r.module_id, r.node_operator_id, r.key_index)
        if key in seen:
            raise InvalidWithdrawalRequestsError(f'Duplicate request for validator {key}.')
        seen.add(key)

        if r.amount > MAX_PWR_AMOUNT:
            raise InvalidWithdrawalRequestsError(
                f'PWR amount {r.amount} for validator {key} exceeds MAX_PWR_AMOUNT {MAX_PWR_AMOUNT}.'
            )
