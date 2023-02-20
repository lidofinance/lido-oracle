from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Tuple, TYPE_CHECKING, NewType

from eth_typing import Address
from web3.module import Module

from src.providers.consensus.typings import Validator
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp
from src.utils.dataclass import Nested

if TYPE_CHECKING:
    from src.web3py.typings import Web3

StakingModuleId = NewType('StakingModuleId', int)
NodeOperatorId = NewType('NodeOperatorId', int)
NodeOperatorIndex = Tuple[StakingModuleId, NodeOperatorId]


@dataclass
class StakingModule:
    # unique id of the staking module
    id: StakingModuleId
    # address of staking module
    staking_module_address: Address
    # part of the fee taken from staking rewards that goes to the staking module
    staking_module_fee: int
    # part of the fee taken from staking rewards that goes to the treasury
    treasury_fee: int
    # target percent of total validators in protocol, in BP
    target_share: int
    # staking module status if staking module can not accept
    # the deposits or can participate in further reward distribution
    status: int
    # name of staking module
    name: str
    # block.timestamp of the last deposit of the staking module
    last_deposit_at: int
    # block.number of the last deposit of the staking module
    last_deposit_block: int
    # number of exited validators
    exited_validators_count: int


@dataclass
class NodeOperator(Nested):
    id: NodeOperatorId
    is_active: bool
    is_target_limit_active: bool
    target_validators_count: int
    stuck_validators_count: int
    refunded_validators_count: int
    stuck_penalty_end_timestamp: int
    total_exited_validators: int
    total_deposited_validators: int
    depositable_validators_count: int
    staking_module: StakingModule


@dataclass
class LidoValidator(Validator):
    key: LidoKey


ValidatorsByNodeOperator = dict[NodeOperatorIndex, list[LidoValidator]]


class LidoValidatorsProvider(Module):
    w3: 'Web3'

    @lru_cache(maxsize=1)
    def get_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        lido_keys = self.w3.kac.get_all_lido_keys(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp.state_root)

        return self.merge_validators_with_keys(lido_keys, validators)

    @staticmethod
    def merge_validators_with_keys(keys: list[LidoKey], validators: list[Validator]) -> list[LidoValidator]:
        """Merging and filter non-lido validators."""
        validators_keys_dict = {validator.validator.pubkey: validator for validator in validators}

        lido_validators = []

        for key in keys:
            if key.key in validators_keys_dict:
                lido_validators.append(LidoValidator(
                    key=key,
                    **asdict(validators_keys_dict[key.key]),
                ))

        return lido_validators

    @lru_cache(maxsize=1)
    def get_lido_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        merged_validators = self.get_lido_validators(blockstamp)
        no_operators = self.get_lido_node_operators(blockstamp)

        # Make sure even empty NO will be presented in dict
        no_validators = {(operator.staking_module.id, operator.id): [] for operator in no_operators}

        staking_module_address = {
            operator.staking_module.staking_module_address: operator.staking_module.id
            for operator in no_operators
        }

        for validator in merged_validators:
            no_validators[(
                staking_module_address[validator.key.moduleAddress],
                validator.key.operatorIndex,
            )].append(validator)

        return no_validators

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> list[NodeOperator]:
        operators = []

        for module in self.get_staking_modules(blockstamp):
            # Replace with getAllNodeOperatorDigests after update
            module_operators = self.w3.lido_contracts.staking_router.functions.getAllNodeOperatorReports(
                module.id
            ).call(block_identifier=blockstamp.block_hash)
            for operator in module_operators:
                # _id, is_active, summary = operator
                # operator = NodeOperator(_id, is_active, *summary, stakingModule=module)
                (
                    _id,
                    isActive,
                    isTargetLimitActive,
                    targetValidatorsCount,
                    stuckValidatorsCount,
                    refundedValidatorsCount,
                    stuckPenaltyEndTimestamp,
                    (
                        totalExited,
                        totalDeposited,
                        depositable,
                    )
                ) = operator

                operator = NodeOperator(
                    id=_id,
                    is_active=isActive,
                    is_target_limit_active=isTargetLimitActive,
                    target_validators_count=targetValidatorsCount,
                    stuck_validators_count=stuckValidatorsCount,
                    refunded_validators_count=refundedValidatorsCount,
                    stuck_penalty_end_timestamp=stuckPenaltyEndTimestamp,
                    total_exited_validators=totalExited,
                    total_deposited_validators=totalDeposited,
                    depositable_validators_count=depositable,
                    staking_module=module,
                )
                operators.append(operator)

        return operators

    @lru_cache(maxsize=1)
    def get_staking_modules(self, blockstamp: BlockStamp) -> list[StakingModule]:
        modules = self.w3.lido_contracts.staking_router.functions.getStakingModules().call(
            block_identifier=blockstamp.block_hash,
        )
        return [StakingModule(*module) for module in modules]
