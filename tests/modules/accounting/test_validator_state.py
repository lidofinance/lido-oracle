from dataclasses import asdict
from unittest.mock import Mock

import pytest
from eth_typing import HexStr

from src.constants import COMPOUNDING_WITHDRAWAL_PREFIX, ETH1_ADDRESS_WITHDRAWAL_PREFIX, FAR_FUTURE_EPOCH
from src.modules.common.types import ChainConfig
from src.providers.consensus.types import PendingPartialWithdrawal, Validator, ValidatorState
from src.providers.execution.contracts.triggerable_withdrawals_bus import WithdrawalIntent
from src.providers.execution.withdrawal_request_queue import QueuedWithdrawalRequest
from src.providers.keys.types import LidoKey
from src.services.validator_state import (
    InFlightInbound,
    InFlightWithdrawals,
    LidoValidatorStateService,
    get_in_flight_inbound,
)
from src.types import EpochNumber, Gwei, NodeOperatorId, StakingModuleId, ValidatorIndex
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    NodeOperator,
    StakingModule,
)
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


TESTING_REF_EPOCH = 100

blockstamp = ReferenceBlockStampFactory.build(
    ref_slot=9024,
    ref_epoch=TESTING_REF_EPOCH,
)


@pytest.fixture
def lido_validators(web3):
    sm = StakingModule(
        id=1,
        staking_module_address='0x8a1E2986E52b441058325c315f83C9D4129bDF72',
        staking_module_fee=500,
        treasury_fee=500,
        stake_share_limit=10000,
        status=0,
        name='NodeOperatorsRegistry',
        last_deposit_at=1676386968,
        last_deposit_block=89677,
        exited_validators_count=0,
        priority_exit_share_threshold=0,
        max_deposits_per_block=0,
        min_deposit_block_distance=0,
        withdrawal_credentials_type=0,
        validators_balance_gwei=Gwei(0),
    )

    web3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm])

    web3.lido_contracts.staking_router.get_all_node_operator_digests = Mock(
        return_value=[
            NodeOperator(
                id=0,
                is_active=True,
                is_target_limit_active=False,
                target_validators_count=0,
                refunded_validators_count=0,
                total_exited_validators=0,
                total_deposited_validators=5,
                depositable_validators_count=0,
                staking_module=sm,
            ),
            NodeOperator(
                id=1,
                is_active=True,
                is_target_limit_active=False,
                target_validators_count=0,
                refunded_validators_count=0,
                total_exited_validators=1,
                total_deposited_validators=5,
                depositable_validators_count=0,
                staking_module=sm,
            ),
        ]
    )

    def validator(index: int, exit_epoch: int, pubkey: HexStr, activation_epoch: int = 0, consolidating_as_source=None):
        return LidoValidator(
            lido_id=LidoKey(
                index=index,
                key=pubkey,
                deposit_signature="",
                operator_index=NodeOperatorId(-1),
                used=True,
                module_address="",
            ),
            **asdict(
                Validator(
                    index=ValidatorIndex(index),
                    balance=Gwei(0),
                    validator=ValidatorState(
                        pubkey=pubkey,
                        withdrawal_credentials="0x1",
                        effective_balance=0,
                        slashed=False,
                        activation_eligibility_epoch=EpochNumber(0),
                        activation_epoch=EpochNumber(activation_epoch),
                        exit_epoch=EpochNumber(exit_epoch),
                        withdrawable_epoch=EpochNumber(0),
                    ),
                )
            ),
            pending_topups=[],
            consolidating_as_source=consolidating_as_source,
            consolidating_as_target=[],
        )

    web3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            (StakingModuleId(1), NodeOperatorId(0)): [
                validator(index=1, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x1'),  # Stuck
                validator(index=2, exit_epoch=30, pubkey='0x2'),
                validator(index=3, exit_epoch=50, pubkey='0x3'),
                validator(index=4, exit_epoch=TESTING_REF_EPOCH, pubkey='0x4'),
            ],
            (StakingModuleId(1), NodeOperatorId(1)): [
                validator(index=5, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x5', activation_epoch=290),  # Stuck but newest
                validator(
                    index=6, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x6', activation_epoch=282
                ),  # Stuck in the same epoch
                validator(index=7, exit_epoch=20, pubkey='0x7'),
                validator(index=8, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x8'),
            ],
        }
    )


@pytest.fixture
def validator_state(web3, lido_validators):
    return LidoValidatorStateService(web3)


WITHDRAWAL_VAULT = '0xB9D7934878B5FB9610B3fE8A5e441e8fad7E293f'
OTHER_SOURCE = '0x00000000000000000000000000000000000000Aa'


@pytest.fixture
def eip7002_queue(web3, monkeypatch):
    """Requests in the EIP-7002 queue; empty unless a test sets `return_value`."""
    web3.lido_contracts.lido_locator.withdrawal_vault = Mock(return_value=WITHDRAWAL_VAULT)
    queue = Mock(return_value=[])
    monkeypatch.setattr('src.services.validator_state.get_queued_withdrawal_requests', queue)
    return queue


@pytest.fixture
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.mark.unit
def test_get_lido_new_exited_validators(web3, validator_state):
    exited_validators = validator_state.get_lido_newly_exited_validators(blockstamp)
    # We didn't expect the second validator because total_exited_validators hasn't changed
    assert exited_validators == {(1, 0): 3}


@pytest.mark.unit
def test_get_in_flight_withdrawals__cl_pending_and_bus_intents__aggregated_by_validator(
    web3, validator_state, eip7002_queue
):
    # Arrange: validator 1 has a 3 ETH partial on the CL and a 2 ETH PWR in the Bus, validator 8 a 5 ETH PWR,
    # validator 6 an FWR. One intent targets a key outside Lido.
    web3.cc.get_state_view = Mock(
        return_value=Mock(
            pending_partial_withdrawals=[
                PendingPartialWithdrawal(
                    validator_index=ValidatorIndex(1), amount=Gwei(3 * 10**9), withdrawable_epoch=EpochNumber(0)
                )
            ]
        )
    )
    web3.lido_contracts.triggerable_withdrawals_bus.get_unprocessed_intents = Mock(
        return_value=[
            WithdrawalIntent(pubkey=HexStr('0x1'), amount=Gwei(2 * 10**9)),
            WithdrawalIntent(pubkey=HexStr('0x8'), amount=Gwei(5 * 10**9)),
            WithdrawalIntent(pubkey=HexStr('0x6'), amount=Gwei(0)),
            WithdrawalIntent(pubkey=HexStr('0x' + 'ab' * 48), amount=Gwei(0)),
        ]
    )

    # Act
    in_flight = validator_state.get_in_flight_withdrawals(blockstamp)

    # Assert
    assert in_flight.pwr_amounts == {1: Gwei(5 * 10**9), 8: Gwei(5 * 10**9)}
    assert in_flight.fwr_validators == frozenset({6})
    assert in_flight.cl_pending_pwr_amounts == {1: Gwei(3 * 10**9)}
    assert in_flight.cl_pending_withdrawable_epochs == {1: EpochNumber(0)}


@pytest.mark.unit
def test_get_in_flight_withdrawals__several_cl_partials__latest_withdrawable_epoch_kept(
    web3, validator_state, eip7002_queue
):
    # Arrange
    web3.cc.get_state_view = Mock(
        return_value=Mock(
            pending_partial_withdrawals=[
                PendingPartialWithdrawal(
                    validator_index=ValidatorIndex(1), amount=Gwei(1 * 10**9), withdrawable_epoch=EpochNumber(300)
                ),
                PendingPartialWithdrawal(
                    validator_index=ValidatorIndex(1), amount=Gwei(2 * 10**9), withdrawable_epoch=EpochNumber(200)
                ),
            ]
        )
    )
    web3.lido_contracts.triggerable_withdrawals_bus.get_unprocessed_intents = Mock(return_value=[])

    # Act
    in_flight = validator_state.get_in_flight_withdrawals(blockstamp)

    # Assert
    assert in_flight.cl_pending_pwr_amounts == {1: Gwei(3 * 10**9)}
    assert in_flight.cl_pending_withdrawable_epochs == {1: EpochNumber(300)}


@pytest.mark.unit
def test_get_in_flight_withdrawals__eip7002_queue__lido_requests_merged_with_bus_and_cl(
    web3, validator_state, eip7002_queue
):
    # Arrange: validator 1 has a 3 ETH partial on the CL, a 4 ETH PWR in the EIP-7002 queue and a 2 ETH PWR
    # in the Bus; validator 6 has an FWR in the EIP-7002 queue; validator 8 has a PWR queued by someone else.
    web3.cc.get_state_view = Mock(
        return_value=Mock(
            pending_partial_withdrawals=[
                PendingPartialWithdrawal(
                    validator_index=ValidatorIndex(1), amount=Gwei(3 * 10**9), withdrawable_epoch=EpochNumber(0)
                )
            ]
        )
    )
    eip7002_queue.return_value = [
        QueuedWithdrawalRequest(WITHDRAWAL_VAULT, HexStr('0x1'), Gwei(4 * 10**9)),
        QueuedWithdrawalRequest(WITHDRAWAL_VAULT, HexStr('0x6'), Gwei(0)),
        QueuedWithdrawalRequest(OTHER_SOURCE, HexStr('0x8'), Gwei(7 * 10**9)),
    ]
    web3.lido_contracts.triggerable_withdrawals_bus.get_unprocessed_intents = Mock(
        return_value=[WithdrawalIntent(pubkey=HexStr('0x1'), amount=Gwei(2 * 10**9))]
    )

    # Act
    in_flight = validator_state.get_in_flight_withdrawals(blockstamp)

    # Assert
    assert in_flight.pwr_amounts == {1: Gwei(9 * 10**9)}
    assert in_flight.fwr_validators == frozenset({6})
    eip7002_queue.assert_called_once_with(web3, blockstamp.block_hash)


ETH = 10**9


def _in_flight_validator(
    index: int,
    balance_eth: float,
    *,
    effective_balance_eth: int = 32,
    exit_epoch: int = FAR_FUTURE_EPOCH,
    withdrawable_epoch: int = FAR_FUTURE_EPOCH,
    slashed: bool = False,
    consolidating_as_source: Mock | None = None,
) -> LidoValidator:
    return LidoValidatorFactory.build(
        index=ValidatorIndex(index),
        balance=Gwei(int(balance_eth * ETH)),
        validator=ValidatorStateFactory.build(
            effective_balance=Gwei(effective_balance_eth * ETH),
            withdrawal_credentials=(
                COMPOUNDING_WITHDRAWAL_PREFIX if effective_balance_eth > 32 else ETH1_ADDRESS_WITHDRAWAL_PREFIX
            ),
            exit_epoch=EpochNumber(exit_epoch),
            withdrawable_epoch=EpochNumber(withdrawable_epoch),
            slashed=slashed,
        ),
        consolidating_as_source=consolidating_as_source,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ('validator', 'in_flight', 'expected'),
    [
        pytest.param(
            _in_flight_validator(1, 32, exit_epoch=10, withdrawable_epoch=266, consolidating_as_source=Mock()),
            InFlightWithdrawals(),
            InFlightInbound(),
            id='consolidation_source__zero',
        ),
        pytest.param(
            _in_flight_validator(1, 31, exit_epoch=10, withdrawable_epoch=8202, slashed=True),
            InFlightWithdrawals(fwr_validators=frozenset({ValidatorIndex(1)})),
            InFlightInbound(),
            id='slashed__zero_and_no_horizon',
        ),
        pytest.param(
            _in_flight_validator(1, 32.5, exit_epoch=10, withdrawable_epoch=266),
            InFlightWithdrawals(pwr_amounts={ValidatorIndex(1): Gwei(5 * ETH)}),
            InFlightInbound(amount=Gwei(int(32.5 * ETH)), latest_cl_withdrawable_epoch=EpochNumber(266)),
            id='exit_initiated__balance_and_partials_ignored',
        ),
        pytest.param(
            _in_flight_validator(1, 40, effective_balance_eth=40),
            InFlightWithdrawals(
                pwr_amounts={ValidatorIndex(1): Gwei(3 * ETH)}, fwr_validators=frozenset({ValidatorIndex(1)})
            ),
            InFlightInbound(amount=Gwei(40 * ETH), queued_churn=Gwei(40 * ETH)),
            id='queued_fwr__balance_and_effective_balance_churn',
        ),
        pytest.param(
            _in_flight_validator(1, 50, effective_balance_eth=50),
            InFlightWithdrawals(
                pwr_amounts={ValidatorIndex(1): Gwei(5 * ETH)},
                fwr_validators=frozenset({ValidatorIndex(1)}),
                cl_pending_pwr_amounts={ValidatorIndex(1): Gwei(2 * ETH)},
                cl_pending_withdrawable_epochs={ValidatorIndex(1): EpochNumber(300)},
            ),
            InFlightInbound(
                amount=Gwei(5 * ETH), queued_churn=Gwei(3 * ETH), latest_cl_withdrawable_epoch=EpochNumber(300)
            ),
            id='queued_fwr_with_cl_partial__fwr_dropped_partials_count',
        ),
        pytest.param(
            _in_flight_validator(1, 35, effective_balance_eth=35),
            InFlightWithdrawals(pwr_amounts={ValidatorIndex(1): Gwei(10 * ETH)}),
            InFlightInbound(amount=Gwei(3 * ETH), queued_churn=Gwei(3 * ETH)),
            id='partials__capped_at_balance_above_activation_balance',
        ),
        pytest.param(
            _in_flight_validator(1, 33, effective_balance_eth=33),
            InFlightWithdrawals(
                pwr_amounts={ValidatorIndex(1): Gwei(5 * ETH)},
                cl_pending_pwr_amounts={ValidatorIndex(1): Gwei(2 * ETH)},
                cl_pending_withdrawable_epochs={ValidatorIndex(1): EpochNumber(300)},
            ),
            InFlightInbound(amount=Gwei(1 * ETH), latest_cl_withdrawable_epoch=EpochNumber(300)),
            id='cap_below_cl_partials__no_queued_churn',
        ),
        pytest.param(
            _in_flight_validator(1, 40, effective_balance_eth=32),
            InFlightWithdrawals(),
            InFlightInbound(),
            id='nothing_requested__zero_even_above_cap',
        ),
    ],
)
def test_get_in_flight_inbound__single_validator__counted_by_first_matching_rule(validator, in_flight, expected):
    assert get_in_flight_inbound([validator], in_flight) == expected


@pytest.mark.unit
def test_get_in_flight_inbound__several_validators__each_counted_once_and_summed():
    # Arrange: an exiting validator (32.5 ETH, withdrawable at 266), a queued FWR (40 ETH),
    # and a validator with a 2 ETH CL partial (withdrawable at 300) and a 3 ETH queued PWR.
    validators = [
        _in_flight_validator(1, 32.5, exit_epoch=10, withdrawable_epoch=266),
        _in_flight_validator(2, 40, effective_balance_eth=40),
        _in_flight_validator(3, 50, effective_balance_eth=50),
        _in_flight_validator(4, 32),
    ]
    in_flight = InFlightWithdrawals(
        pwr_amounts={ValidatorIndex(3): Gwei(5 * ETH)},
        fwr_validators=frozenset({ValidatorIndex(2)}),
        cl_pending_pwr_amounts={ValidatorIndex(3): Gwei(2 * ETH)},
        cl_pending_withdrawable_epochs={ValidatorIndex(3): EpochNumber(300)},
    )

    # Act
    result = get_in_flight_inbound(validators, in_flight)

    # Assert
    assert result == InFlightInbound(
        amount=Gwei(int((32.5 + 40 + 5) * ETH)),
        queued_churn=Gwei((40 + 3) * ETH),
        latest_cl_withdrawable_epoch=EpochNumber(300),
    )
