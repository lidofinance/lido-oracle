from dataclasses import asdict
from unittest.mock import Mock

import pytest
from eth_typing import HexStr

from src.constants import FAR_FUTURE_EPOCH
from src.services.validator_state import LidoValidatorStateService
from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import Validator, ValidatorState
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp, ReferenceBlockStamp
from src.web3py.extentions.lido_validators import (
    NodeOperator, StakingModule, LidoValidatorsProvider, LidoValidator,
    ValidatorsByNodeOperator, StakingModuleId, NodeOperatorId,
)

TESTING_REF_EPOCH = 100

blockstamp = ReferenceBlockStamp(
    ref_slot=9000,
    ref_epoch=TESTING_REF_EPOCH,
    block_root=None,
    state_root=None,
    slot_number='',
    block_hash='',
    block_number=0,
    block_timestamp=0,
)


class MockValidatorsProvider(LidoValidatorsProvider):

    def get_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        raise NotImplementedError

    def get_lido_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        def validator(index: int, exit_epoch: int, pubkey: HexStr):
            return LidoValidator(
                lido_id=LidoKey(
                    key=pubkey,
                    depositSignature="",
                    operatorIndex=-1,
                    used=True,
                    moduleAddress="",
                ),
                **asdict(Validator(
                    index=str(index),
                    balance="0",
                    status="",
                    validator=ValidatorState(
                        pubkey=pubkey,
                        withdrawal_credentials="0x1",
                        effective_balance="0",
                        slashed=False,
                        activation_eligibility_epoch="0",
                        activation_epoch="0",
                        exit_epoch=str(exit_epoch),
                        withdrawable_epoch="0",
                    ),
                )),
            )

        return {
            (StakingModuleId(1), NodeOperatorId(0)): [
                validator(index=1, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x1'),  # Stuck
                validator(index=2, exit_epoch=30, pubkey='0x2'),
                validator(index=3, exit_epoch=50, pubkey='0x3'),
                validator(index=4, exit_epoch=TESTING_REF_EPOCH, pubkey='0x4'),
            ],
            (StakingModuleId(1), NodeOperatorId(1)): [
                validator(index=5, exit_epoch=20, pubkey='0x5'),
                validator(index=6, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x6'),
            ],
        }

    def get_staking_modules(self, blockstamp: BlockStamp) -> list[StakingModule]:
        return [StakingModule(id=1,
                              staking_module_address='0x8a1E2986E52b441058325c315f83C9D4129bDF72',
                              staking_module_fee=500, treasury_fee=500, target_share=10000,
                              status=0,
                              name='NodeOperatorsRegistry', last_deposit_at=1676386968,
                              last_deposit_block=89677, exited_validators_count=0)]

    def get_lido_node_operators(self, blockstamp: BlockStamp) -> list[NodeOperator]:
        def operator(id: int, total_exited_validators: int):
            return NodeOperator(id=id, is_active=True, is_target_limit_active=False, target_validators_count=0,
                                stuck_validators_count=0, refunded_validators_count=0, stuck_penalty_end_timestamp=0,
                                total_exited_validators=total_exited_validators, total_deposited_validators=5,
                                depositable_validators_count=0,
                                staking_module=module)

        module = self.get_staking_modules(blockstamp)[0]
        return [operator(id=0, total_exited_validators=0),
                operator(id=1, total_exited_validators=1)]


@pytest.fixture
def lido_validators(web3):
    web3.attach_modules({
        'lido_validators': MockValidatorsProvider,
    })


@pytest.fixture
def validator_state(web3, contracts, consensus_client, lido_validators):
    service = LidoValidatorStateService(web3)
    requested_indexes = [3, 6]
    service._get_last_requested_validator_indices = Mock(return_value=requested_indexes)
    return service


@pytest.fixture
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


def test_get_lido_new_stuck_validators(web3, validator_state, chain_config):
    validator_state.get_last_requested_to_exit_pubkeys = Mock(return_value={"0x6"})
    validator_state.get_validator_delinquent_timeout_in_slot = Mock(return_value=0)
    stuck_validators = validator_state.get_lido_newly_stuck_validators(blockstamp, chain_config)
    assert stuck_validators == {(1, 0): 1}


@pytest.mark.unit
def test_get_operators_with_last_exited_validator_indexes(web3, validator_state):
    indexes = validator_state.get_operators_with_last_exited_validator_indexes(blockstamp)
    assert indexes == {(1, 0): 3,
                       (1, 1): 6}


@pytest.mark.unit
def test_get_lido_new_exited_validators(web3, validator_state):
    exited_validators = validator_state.get_lido_newly_exited_validators(blockstamp)
    # We didn't expect the second validator because total_exited_validators hasn't changed
    assert exited_validators == {(1, 0): 3}
