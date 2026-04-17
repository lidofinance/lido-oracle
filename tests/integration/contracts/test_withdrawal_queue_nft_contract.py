import pytest

from modules.oracles.accounting.types import BatchState, WithdrawalRequestStatus
from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.mainnet
@pytest.mark.integration
def test_withdrawal_queue(withdrawal_queue_nft_contract, caplog):
    check_contract(
        withdrawal_queue_nft_contract,
        [
            ('unfinalized_steth', None, make_checker(int)),
            ('bunker_mode_since_timestamp', None, make_checker(int)),
            ('get_last_finalized_request_id', None, make_checker(int)),
            ('get_withdrawal_status', (1,), make_checker(WithdrawalRequestStatus)),
            ('get_last_request_id', None, make_checker(int)),
            ('is_paused', None, make_checker(bool)),
            ('max_batches_length', None, make_checker(int)),
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
                make_checker(BatchState),
            ),
        ],
        caplog,
    )
