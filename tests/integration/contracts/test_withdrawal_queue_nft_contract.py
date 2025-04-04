import pytest

from src.modules.accounting.types import BatchState, WithdrawalRequestStatus
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_withdrawal_queue(withdrawal_queue_nft_contract, caplog):
    check_contract(
        withdrawal_queue_nft_contract,
        [
            ('unfinalized_steth', None, lambda response: check_value_type(response, int)),
            ('bunker_mode_since_timestamp', None, lambda response: check_value_type(response, int)),
            ('get_last_finalized_request_id', None, lambda response: check_value_type(response, int)),
            ('get_withdrawal_status', (1,), lambda response: check_value_type(response, WithdrawalRequestStatus)),
            ('get_last_request_id', None, lambda response: check_value_type(response, int)),
            ('is_paused', None, lambda response: check_value_type(response, bool)),
            ('max_batches_length', None, lambda response: check_value_type(response, int)),
            (
                'calculate_finalization_batches',
                (
                    1167796098828864377325065539,
                    1716716759,
                    1000,
                    (
                        7937157558488263113651,
                        False,
                        (
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        ),
                        0,
                    ),
                    "0xcc74e3f3fe27f9f8da8b91c1aede727ebfa82d9c74cf4b873d81269e866dce72",
                ),
                lambda response: check_value_type(response, BatchState),
            ),
        ],
        caplog,
    )
