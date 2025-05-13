from dataclasses import asdict
from unittest.mock import Mock

import pytest
from eth_typing import HexStr

from src.constants import FAR_FUTURE_EPOCH
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import Validator, ValidatorState
from src.providers.keys.types import LidoKey
from src.services.validator_state import LidoValidatorStateService
from src.types import EpochNumber, Gwei, NodeOperatorId, StakingModuleId, ValidatorIndex
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperator, StakingModule
from tests.factory.blockstamp import ReferenceBlockStampFactory

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
    )

    web3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm])

    web3.lido_contracts.staking_router.get_all_node_operator_digests = Mock(
        return_value=[
            NodeOperator(
                id=0,
                is_active=True,
                is_target_limit_active=False,
                target_validators_count=0,
                stuck_validators_count=0,
                refunded_validators_count=0,
                stuck_penalty_end_timestamp=0,
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
                stuck_validators_count=0,
                refunded_validators_count=0,
                stuck_penalty_end_timestamp=0,
                total_exited_validators=1,
                total_deposited_validators=5,
                depositable_validators_count=0,
                staking_module=sm,
            ),
        ]
    )

    def validator(index: int, exit_epoch: int, pubkey: HexStr, activation_epoch: int = 0):
        return LidoValidator(
            lido_id=LidoKey(
                key=pubkey,
                depositSignature="",
                operatorIndex=NodeOperatorId(-1),
                used=True,
                moduleAddress="",
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
    service = LidoValidatorStateService(web3)
    service.w3.lido_contracts.validators_exit_bus_oracle.get_last_requested_validator_indices = Mock(
        return_value=[3, 8]
    )
    return service


@pytest.fixture
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.mark.unit
def test_get_lido_new_stuck_validators(web3, validator_state, chain_config):
    validator_state.get_last_requested_to_exit_pubkeys = Mock(return_value={"0x8"})
    validator_state.w3.lido_contracts.oracle_daemon_config.validator_delinquent_timeout_in_slots = Mock(return_value=0)
    stuck_validators = validator_state.get_lido_newly_stuck_validators(blockstamp, chain_config)
    assert stuck_validators == {(1, 0): 1}


@pytest.mark.unit
def test_get_operators_with_last_exited_validator_indexes(web3, validator_state):
    indexes = validator_state.get_operators_with_last_exited_validator_indexes(blockstamp)
    assert indexes == {(1, 0): 3, (1, 1): 8}


@pytest.mark.unit
def test_get_lido_new_exited_validators(web3, validator_state):
    exited_validators = validator_state.get_lido_newly_exited_validators(blockstamp)
    # We didn't expect the second validator because total_exited_validators hasn't changed
    assert exited_validators == {(1, 0): 3}


@pytest.mark.unit
def test_get_recently_requested_validators_by_operator(monkeypatch, web3, validator_state):
    mocked_events = [
        {'args': {'stakingModuleId': 1, 'nodeOperatorId': 0, 'validatorIndex': 1}},
        {'args': {'stakingModuleId': 1, 'nodeOperatorId': 0, 'validatorIndex': 2}},
    ]
    mock_get_events_in_past = Mock(return_value=mocked_events)
    monkeypatch.setattr('src.services.validator_state.get_events_in_past', mock_get_events_in_past)
    web3.lido_contracts.oracle_daemon_config.validator_delayed_timeout_in_slots = Mock(return_value=7200)

    global_indexes = validator_state.get_recently_requested_validators_by_operator(12, blockstamp)

    assert global_indexes == {(1, 0): {1, 2}, (1, 1): set()}
    mock_get_events_in_past.assert_called_once_with(
        web3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest,
        to_blockstamp=blockstamp,
        for_slots=7200,
        seconds_per_slot=12,
    )


@pytest.mark.unit
def test_get_recently_requested_but_not_exited_validators(monkeypatch, web3, chain_config, validator_state):
    mocked_events = [
        {'args': {'stakingModuleId': 1, 'nodeOperatorId': 0, 'validatorIndex': 1}},
        {'args': {'stakingModuleId': 1, 'nodeOperatorId': 0, 'validatorIndex': 2}},
    ]
    mock_get_events_in_past = Mock(return_value=mocked_events)
    monkeypatch.setattr('src.services.validator_state.get_events_in_past', mock_get_events_in_past)
    web3.lido_contracts.oracle_daemon_config.validator_delayed_timeout_in_slots = Mock(return_value=7200)

    blockstamp = ReferenceBlockStampFactory.build(
        ref_slot=15392,
        ref_epoch=481,
    )
    recently_requested_validators = validator_state.get_recently_requested_but_not_exited_validators(
        blockstamp, chain_config
    )

    assert [int(v.index) for v in recently_requested_validators] == [1, 5, 6]
