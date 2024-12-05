import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING

from eth_typing import ChecksumAddress
from web3.module import Module

from src.constants import FAR_FUTURE_EPOCH, MIN_ACTIVATION_BALANCE
from src.providers.consensus.types import Validator
from src.providers.keys.types import LidoKey
from src.types import BlockStamp, StakingModuleId, NodeOperatorId, NodeOperatorGlobalIndex, StakingModuleAddress
from src.utils.dataclass import Nested
from src.utils.cache import global_lru_cache as lru_cache


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from src.web3py.types import Web3  # pragma: no cover


class NodeOperatorLimitMode(Enum):
    DISABLED = 0
    SOFT = 1
    FORCE = 2


@dataclass
class StakingModule:
    # unique id of the staking module
    id: StakingModuleId
    # address of staking module
    staking_module_address: ChecksumAddress
    # part of the fee taken from staking rewards that goes to the staking module
    staking_module_fee: int
    # part of the fee taken from staking rewards that goes to the treasury
    treasury_fee: int
    # target percent of total validators in protocol, in BP
    stake_share_limit: int
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
    # ---------------------
    # Available after SR2
    # ---------------------
    # module's share threshold, upon crossing which, exits of validators from the module will be prioritized, in BP
    priority_exit_share_threshold: int | None = None
    # the maximum number of validators that can be deposited in a single block
    max_deposits_per_block: int | None = None
    # the minimum distance between deposits in blocks
    min_deposit_block_distance: int | None = None

    @classmethod
    def from_response(cls, **staking_module):
        """
        To support both versions of StakingRouter, we map values by order instead of keys.

        Breaking changes are
        target_share -> stake_share_limit
        """
        # `target_share` renamed to `stake_share_limit`
        return cls(*staking_module.values())  # pylint: disable=no-value-for-parameter

    def __hash__(self):
        return hash(self.id)


@dataclass
class NodeOperator(Nested):
    id: NodeOperatorId
    is_active: bool
    is_target_limit_active: NodeOperatorLimitMode
    target_validators_count: int
    stuck_validators_count: int
    refunded_validators_count: int
    stuck_penalty_end_timestamp: int
    total_exited_validators: int
    total_deposited_validators: int
    depositable_validators_count: int
    staking_module: StakingModule

    @classmethod
    def from_response(cls, data, staking_module):
        _id, is_active, (
            is_target_limit_active,
            target_validators_count,
            stuck_validators_count,
            refunded_validators_count,
            stuck_penalty_end_timestamp,
            total_exited_validators,
            total_deposited_validators,
            depositable_validators_count,
        ) = data

        # Staking router v1 contract returns bool value in target limit mode
        # Staking router v1.5 introduce new limit mode (force) and updates is_target_limit_active to uint type
        #
        # False == 0 == No priority ejections
        # True  == 1 == Soft priority ejections
        #          2 == Force priority ejections
        is_target_limit_active = NodeOperatorLimitMode(min(is_target_limit_active, 2))

        return cls(
            _id,
            is_active,
            is_target_limit_active,
            target_validators_count,
            stuck_validators_count,
            refunded_validators_count,
            stuck_penalty_end_timestamp,
            total_exited_validators,
            total_deposited_validators,
            depositable_validators_count,
            staking_module,
        )


@dataclass
class LidoValidator(Validator):
    lido_id: LidoKey


class CountOfKeysDiffersException(Exception):
    pass


type ValidatorsByNodeOperator = dict[NodeOperatorGlobalIndex, list[LidoValidator]]


class LidoValidatorsProvider(Module):
    w3: 'Web3'

    @lru_cache(maxsize=1)
    def get_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        lido_keys = self.w3.kac.get_used_lido_keys(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp)

        self._kapi_sanity_check(len(lido_keys), blockstamp)

        return self.merge_validators_with_keys(lido_keys, validators)

    def _kapi_sanity_check(self, keys_count_received: int, blockstamp: BlockStamp):
        stats = self.w3.lido_contracts.lido.get_beacon_stat(blockstamp.block_hash)

        # Make sure that used keys fetched from Keys API >= total amount of total deposited validators from Staking Router
        if keys_count_received < stats.deposited_validators:
            raise CountOfKeysDiffersException(f'Keys API Service returned lesser keys ({keys_count_received}) '
                                              f'than amount of deposited validators ({stats.deposited_validators}) returned from Staking Router')

    @staticmethod
    def merge_validators_with_keys(keys: list[LidoKey], validators: list[Validator]) -> list[LidoValidator]:
        """Merging and filter non-lido validators."""
        validators_keys_dict = {validator.validator.pubkey: validator for validator in validators}

        lido_validators = []

        for key in keys:
            if key.key in validators_keys_dict:
                lido_validators.append(LidoValidator(
                    lido_id=key,
                    **asdict(validators_keys_dict[key.key]),
                ))

        return lido_validators

    @staticmethod
    def calculate_pending_deposits_sum(lido_validators: list[LidoValidator]) -> int:
        return sum(
            MIN_ACTIVATION_BALANCE
            for validator in lido_validators
            if int(validator.balance) == 0 and int(validator.validator.activation_epoch) == FAR_FUTURE_EPOCH
        )

    @lru_cache(maxsize=1)
    def get_lido_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        merged_validators = self.get_lido_validators(blockstamp)
        no_operators = self.get_lido_node_operators(blockstamp)

        # Make sure even empty NO will be presented in dict
        no_validators: ValidatorsByNodeOperator = {
            (operator.staking_module.id, operator.id): [] for operator in no_operators
        }

        staking_module_address = {
            operator.staking_module.staking_module_address: operator.staking_module.id
            for operator in no_operators
        }

        for validator in merged_validators:
            global_no_id = (
                staking_module_address[validator.lido_id.moduleAddress],
                NodeOperatorId(validator.lido_id.operatorIndex),
            )

            if global_no_id in no_validators:
                no_validators[global_no_id].append(validator)
            else:
                logger.warning({
                    'msg': f'Got global node operator id: {global_no_id}, '
                           f'but it`s not exist in staking router on block number: {blockstamp.block_number}',
                })

        return no_validators

    @lru_cache(maxsize=1)
    def get_module_validators_by_node_operators(self, module_address: StakingModuleAddress, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        """Get module validators by querying the KeysAPI for the module keys"""
        kapi = self.w3.kac.get_module_operators_keys(module_address, blockstamp)
        if (kapi_module_address := kapi['module']['stakingModuleAddress']) != module_address:
            raise ValueError(f"Module address mismatch: {kapi_module_address=} != {module_address=}")
        operators = kapi['operators']
        keys = {k['key']: k for k in kapi['keys']}
        validators = self.w3.cc.get_validators(blockstamp)

        module_id = StakingModuleId(int(kapi['module']['id']))

        # Make sure even empty NO will be presented in dict
        no_validators: ValidatorsByNodeOperator = {
            (module_id, NodeOperatorId(int(operator['index']))): [] for operator in operators
        }

        for validator in validators:
            lido_key = keys.get(validator.validator.pubkey)
            if not lido_key:
                continue
            global_id = (module_id, lido_key['operatorIndex'])
            no_validators[global_id].append(
                LidoValidator(
                    lido_id=LidoKey.from_response(**lido_key),
                    **asdict(validator),
                )
            )

        return no_validators

    @lru_cache(maxsize=1)
    def get_lido_node_operators_by_modules(self, blockstamp: BlockStamp) -> dict[StakingModuleId, list[NodeOperator]]:
        result = {}

        modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        for module in modules:
            result[module.id] = self.w3.lido_contracts.staking_router.get_all_node_operator_digests(module, blockstamp.block_hash)

        return result

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> list[NodeOperator]:
        result = []

        for nos in self.get_lido_node_operators_by_modules(blockstamp).values():
            result.extend(nos)

        return result
