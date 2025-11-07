import pytest

from src.modules.accounting.types import BatchState, WithdrawalRequestStatus
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.mainnet
@pytest.mark.integration
def test_withdrawal_queue(withdrawal_queue_nft_contract, caplog):
    check_contract(
        withdrawal_queue_nft_contract,
        [
            ('unfinalized_steth', None, check_is_instance_of(int)),
            ('bunker_mode_since_timestamp', None, check_is_instance_of(int)),
            ('get_last_finalized_request_id', None, check_is_instance_of(int)),
            ('get_withdrawal_status', (1,), check_is_instance_of(WithdrawalRequestStatus)),
            ('get_last_request_id', None, check_is_instance_of(int)),
            ('is_paused', None, check_is_instance_of(bool)),
            ('max_batches_length', None, check_is_instance_of(int)),
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
                    "latest",
                ),
                check_is_instance_of(BatchState),
            ),
        ],
        caplog,
    )
