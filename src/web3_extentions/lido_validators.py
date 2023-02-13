from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Tuple, TYPE_CHECKING

from eth_typing import Address
from web3.module import Module

from src.providers.consensus.typings import Validator
from src.providers.keys.typings import LidoKey, LidoValidator
from src.typings import BlockStamp
from src.web3_extentions import LidoContracts

if TYPE_CHECKING:
    from src.web3_extentions.typings import Web3

NodeOperatorIndex = Tuple[Address, int]


@dataclass
class Operator:
    id: int
    isActive: bool
    isTargetLimitActive: bool
    targetValidatorsCount: int
    stuckValidatorsCount: int
    refundedValidatorsCount: int
    stuckPenaltyEndTimestamp: int
    validatorsReport: tuple[int, int, int]  # totalExited, totalDeposited, depositable


@dataclass
class OperatorExpanded(Operator):
    stakingModuleAddress: Address


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
        no_validators = {(operator.stakingModuleAddress, operator.id): [] for operator in no_operators}

        for validator in merged_validators:
            no_validators[(validator.key.moduleAddress, validator.key.operatorIndex)].append(validator)

        return dict(no_validators)

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> list[OperatorExpanded]:

        operators = []

        staking_modules = self.w3.lido_contracts.staking_router.functions.getStakingModules().call(
            block_identifier=blockstamp.block_hash,
        )
        for module in staking_modules:
            module_id, module_address, *_ = module
            module_contract = self.w3.eth.contract(address=module_address, abi=LidoContracts.load_abi('IStakingModule'))
            nos_count = module_contract.functions.getNodeOperatorsCount().call(block_identifier=blockstamp.block_hash)
            module_operators = self.w3.lido_contracts.staking_router.functions.getNodeOperatorReports(
                module_id, 0, nos_count
            ).call(block_identifier=blockstamp.block_hash)
            for operator in module_operators:
                operator = OperatorExpanded(*operator, stakingModuleAddress=module_address)
                operators.append(operator)

        return operators

