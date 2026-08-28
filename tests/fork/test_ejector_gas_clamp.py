"""Fork test for the VEBO gas clamp on a large exit report

The daemon clamps the gas of every transaction to ``MAX_BLOCK_GAS_LIMIT`` (16M) in
``estimate_gas`` and runs the pre-flight ``eth_call`` at that clamped limit. After the VEBO
v3 upgrade every exit request costs ~26.5k gas (per-request ``getSigningKeys`` check), so a
report near the sanity-checker ceiling (``maxBalanceExitRequestedPerReportInEth`` = 19_200 ETH
=> ~600 requests) needs more than 16M gas. The pre-flight then reverts out-of-gas, the report
is silently not sent, and no error is raised.

This test builds the largest report the real ``ValidatorExitIterator`` can produce on a fork
with high exit demand and shows two things:
  1. The real daemon path drops that report - the report contract never advances.
  2. The same report is valid on chain when the clamp is lifted - so only the clamp blocks it.

Exit demand is created with real ``requestWithdrawals`` calls. Freshly minted stETH would sit
in the Lido buffer and cover the withdrawal itself (demand-neutral), so instead we impersonate
the wstETH contract, which holds millions of stETH backed by validators, and request a
withdrawal against that balance. That grows ``unfinalizedStETH`` without adding buffer, which is
what forces the ejector to exit validators.
"""

from unittest.mock import patch

import pytest
from eth_account import Account

from src import constants
from src.modules.common.types import FrameConfig
from src.modules.oracles.ejector.ejector import Ejector
from src.utils.range import sequence
from src.utils.transaction import build_transaction_params, sign_and_send_transaction
from src.web3py.extensions.tx_utils import TransactionUtils
from tests.fork.conftest import first_slot_of_epoch


# wstETH holds a few million stETH backed by validators - an unlimited source of real demand.
WSTETH_ADDRESS = "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0"

# One withdrawal request may lock at most MAX_STETH_WITHDRAWAL_AMOUNT = 1000 stETH.
CHUNK_STETH = 1000 * 10**18
# Demand well above the sanity-checker exit ceiling (19_200 ETH) so the iterator fills the
# report up to that ceiling and stops there, regardless of the predictable EL balance.
INJECTED_DEMAND_STETH = 150_000 * 10**18
# requestWithdrawals mints one NFT per element; keep batches small so a single tx fits the block.
REQUEST_BATCH = 30

# The wall: 595+ requests exceed the 16M clamp, 594 fit.
GAS_CLAMP_BOUNDARY_REQUESTS = 595
# Well above a full block, used to show the report is valid once the clamp is lifted.
UNCAPPED_GAS_LIMIT = 30_000_000


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/lido/HashConsensus_bin') as f:
        yield f.read()


@pytest.fixture
def ejector_module(web3):
    return Ejector(web3)


@pytest.fixture
def start_before_initial_epoch(frame_config: FrameConfig):
    _from = frame_config.initial_epoch - 1
    _to = frame_config.initial_epoch + 2
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


def _inject_exit_demand(web3, total_steth: int, chunk: int) -> None:
    """Grow the withdrawal queue by requesting withdrawals against wstETH-held stETH."""
    steth = web3.lido_contracts.lido
    withdrawal_queue = web3.lido_contracts.withdrawal_queue_nft

    web3.provider.make_request('anvil_setBalance', [WSTETH_ADDRESS, hex(10**20)])
    web3.eth.wait_for_transaction_receipt(
        steth.functions.approve(withdrawal_queue.address, total_steth).transact({'from': WSTETH_ADDRESS})
    )

    amounts = [chunk] * (total_steth // chunk)
    for start in range(0, len(amounts), REQUEST_BATCH):
        batch = amounts[start : start + REQUEST_BATCH]
        web3.eth.wait_for_transaction_receipt(
            withdrawal_queue.functions.requestWithdrawals(batch, WSTETH_ADDRESS).transact({'from': WSTETH_ADDRESS})
        )


@pytest.mark.fork
@pytest.mark.integration
@pytest.mark.parametrize('module', [ejector_module], indirect=True)
@pytest.mark.parametrize('running_finalized_slots', [start_before_initial_epoch], indirect=True)
def test_submit_report_data__report_over_gas_clamp__silently_dropped_but_valid_uncapped(
    module,
    web3,
    set_oracle_members,
    running_finalized_slots,
    account_from,
):
    # Arrange
    if module.report_contract.get_consensus_version('latest') != module.COMPATIBLE_CONSENSUS_VERSION:
        pytest.skip(f"VEBO consensus version on chain does not match expected {module.COMPATIBLE_CONSENSUS_VERSION}")
    assert module.report_contract.get_last_processing_ref_slot('latest') == 0, "Last processing ref slot should be 0"

    _inject_exit_demand(web3, INJECTED_DEMAND_STETH, CHUNK_STETH)
    members = set_oracle_members(count=2)

    # Act - run the real daemon cycle. The hash phase succeeds; the data phase is attempted and
    # silently dropped by the gas clamp. Capture the report the iterator built for the frame.
    ref_blockstamp = None
    report_data = None
    switch_finalized, _ = running_finalized_slots
    while switch_finalized():
        for _, private_key in members:
            with account_from(private_key):
                module.cycle_handler()
        candidate = module.get_blockstamp_for_report(module._receive_last_finalized_slot())  # noqa: SLF001
        if candidate is not None:
            ref_blockstamp = candidate
            report_data = module.build_report(candidate)

    # Assert - the iterator built a report past the boundary, but it was never submitted.
    assert ref_blockstamp is not None, "The contract never became reportable"
    assert report_data is not None
    requests_count = report_data[2]
    assert requests_count >= GAS_CLAMP_BOUNDARY_REQUESTS, (
        f"Real iterator built only {requests_count} requests, below the {GAS_CLAMP_BOUNDARY_REQUESTS} wall"
    )
    assert module.report_contract.get_last_processing_ref_slot('latest') == 0, "Report must not have been submitted"
    assert module.report_contract.get_processing_state('latest').data_submitted is False

    # Assert - the same report is valid on chain; only the 16M clamp blocks the daemon path.
    account = Account.from_key(members[0][1])  # pylint: disable=no-value-for-parameter
    transaction = module.report_contract.submit_report_data(report_data, module.COMPATIBLE_CONTRACT_VERSION)

    clamp = constants.MAX_BLOCK_GAS_LIMIT
    clamped_params = build_transaction_params(web3, transaction, account)
    assert clamped_params['gas'] == clamp, "Gas must be clamped to MAX_BLOCK_GAS_LIMIT"
    assert TransactionUtils._check_transaction(transaction, clamped_params) is False  # noqa: SLF001

    with patch.object(constants, 'MAX_BLOCK_GAS_LIMIT', UNCAPPED_GAS_LIMIT):
        uncapped_params = build_transaction_params(web3, transaction, account)
        assert uncapped_params['gas'] > clamp, "The report needs more than the clamp allows"
        assert TransactionUtils._check_transaction(transaction, uncapped_params) is True  # noqa: SLF001
        sign_and_send_transaction(web3, transaction, uncapped_params, account)

    assert module.report_contract.get_last_processing_ref_slot('latest') == ref_blockstamp.ref_slot, (
        "With the clamp lifted the same report submits successfully"
    )
