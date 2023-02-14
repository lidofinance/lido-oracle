from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Tuple, TYPE_CHECKING

from eth_typing import Address
from web3.module import Module

from src.providers.consensus.typings import Validator
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp
from src.utils.dataclass import Nested
from src.web3_extentions import LidoContracts

if TYPE_CHECKING:
    from src.web3_extentions.typings import Web3

NodeOperatorIndex = Tuple[Address, int]


@dataclass
class StakingModule:
    # unique id of the staking module
    id: int
    # address of staking module
    stakingModuleAddress: Address
    # part of the fee taken from staking rewards that goes to the staking module
    stakingModuleFee: int
    # part of the fee taken from staking rewards that goes to the treasury
    treasuryFee: int
    # target percent of total validators in protocol, in BP
    targetShare: int
    # staking module status if staking module can not accept
    # the deposits or can participate in further reward distribution
    status: int
    # name of staking module
    name: str
    # block.timestamp of the last deposit of the staking module
    lastDepositAt: int
    # block.number of the last deposit of the staking module
    lastDepositBlock: int
    # number of exited validators
    exitedValidatorsCount: int


@dataclass
class NodeOperator(Nested):
    id: int
    isActive: bool
    isTargetLimitActive: bool
    targetValidatorsCount: int
    stuckValidatorsCount: int
    refundedValidatorsCount: int
    stuckPenaltyEndTimestamp: int
    totalExitedValidators: int
    totalDepositedValidators: int
    depositableValidatorsCount: int
    stakingModule: StakingModule


@dataclass
class LidoValidator(Nested):
    key: LidoKey
    validator: Validator


class LidoValidatorsProvider(Module):
    w3: 'Web3'

    @lru_cache(maxsize=1)
    def get_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        lido_keys = self.w3.kac.get_all_lido_keys(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp.state_root)

        return self._merge_validators(lido_keys, validators)

    @staticmethod
    def _merge_validators(keys: list[LidoKey], validators: list[Validator]) -> list[LidoValidator]:
        """Merging and filter non-lido validators."""
        validators_keys_dict = {validator.validator.pubkey: validator for validator in validators}

        lido_validators = []

        for key in keys:
            if key.key in validators_keys_dict:
                lido_validators.append(LidoValidator(
                    key=key,
                    validator=validators_keys_dict[key.key],
                ))

        return lido_validators

    @lru_cache(maxsize=1)
    def get_lido_validators_by_node_operators(self, blockstamp: BlockStamp) -> Dict[NodeOperatorIndex, LidoValidator]:
        merged_validators = self.get_lido_validators(blockstamp)
        no_operators = self.get_lido_node_operators(blockstamp)

        # Make sure even empty NO will be presented in dict
        no_validators = {(operator.stakingModule.stakingModuleAddress, operator.id): [] for operator in no_operators}

        for validator in merged_validators:
            no_validators[(validator.key.moduleAddress, validator.key.operatorIndex)].append(validator)

        return dict(no_validators)

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> list[NodeOperator]:

        operators = []

        for module in self._get_staking_modules(blockstamp):
            module_operators = self.w3.lido_contracts.staking_router.functions.getAllNodeOperatorDigests(
                module.id
            ).call(block_identifier=blockstamp.block_hash)
            for operator in module_operators:
                _id, is_active, summary = operator
                operator = NodeOperator(_id, is_active, *summary, stakingModule=module)
                operators.append(operator)

        return operators

    def _get_staking_modules(self, blockstamp: BlockStamp) -> list[StakingModule]:
        modules = self.w3.lido_contracts.staking_router.functions.getStakingModules().call(
            block_identifier=blockstamp.block_hash,
        )
        return [StakingModule(*module) for module in modules]
