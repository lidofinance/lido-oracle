import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING

from eth_typing import ChecksumAddress, HexStr
from web3.module import Module

from src.constants import COMPOUNDING_WITHDRAWAL_PREFIX, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.providers.consensus.types import PendingDeposit, Validator
from src.providers.keys.types import LidoKey
from src.services.deposit_signature_verification import is_valid_deposit_signature
from src.types import BlockStamp, NodeOperatorGlobalIndex, NodeOperatorId, StakingModuleId
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.dataclass import FromResponse, Nested
from src.utils.types import hex_str_to_bytes


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.web3py.types import Web3  # pragma: no cover


class NodeOperatorLimitMode(Enum):
    # 0 == No priority ejections
    DISABLED = 0
    # 1 == Soft priority ejections
    SOFT = 1
    # 2 == Force priority ejections
    FORCE = 2


@dataclass
class StakingModule(FromResponse):
    # unique id of the staking module
    id: StakingModuleId
    # address of staking module
    staking_module_address: ChecksumAddress
    # part of the fee taken from staking rewards that goes to the staking module
    staking_module_fee: int
    # part of the fee taken from staking rewards that goes to the treasury
    treasury_fee: int
    # target percentage of total validators in protocol, in BP
    stake_share_limit: int
    # staking module status if staking module cannot accept
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
    # module's share threshold, upon crossing which, exits of validators from the module will be prioritized, in BP
    priority_exit_share_threshold: int
    # the maximum number of validators that can be deposited in a single block
    max_deposits_per_block: int
    # the minimum distance between deposits in blocks
    min_deposit_block_distance: int

    def __hash__(self):
        return hash(self.id)


@dataclass
class NodeOperator(Nested):
    id: NodeOperatorId
    is_active: bool
    is_target_limit_active: NodeOperatorLimitMode
    target_validators_count: int
    refunded_validators_count: int
    total_exited_validators: int
    total_deposited_validators: int
    depositable_validators_count: int
    staking_module: StakingModule

    @classmethod
    def from_response(cls, data, staking_module):
        (
            _id,
            is_active,
            (
                is_target_limit_active,
                target_validators_count,
                _stuck_validators_count,  # deprecated, https://github.com/lidofinance/core/blob/c7372de2d6999e6e655350f3fbde9a7cb86ef29b/contracts/0.8.9/StakingRouter.sol#L748
                refunded_validators_count,
                _stuck_penalty_end_timestamp,  # deprecated, https://github.com/lidofinance/core/blob/c7372de2d6999e6e655350f3fbde9a7cb86ef29b/contracts/0.8.9/StakingRouter.sol#L757
                total_exited_validators,
                total_deposited_validators,
                depositable_validators_count,
            ),
        ) = data

        return cls(
            _id,
            is_active,
            # In case mode > 2, consider its force priority
            NodeOperatorLimitMode(min(is_target_limit_active, 2)),
            target_validators_count,
            refunded_validators_count,
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
type PendingValidator = tuple[LidoKey, list[PendingDeposit]]


class LidoValidatorsProvider(Module):
    w3: Web3

    def get_active_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        return self._get_lido_validators_with_keys(blockstamp)[0]

    def get_lido_wc_list(self, blockstamp: BlockStamp) -> list[HexStr]:
        wc_address = self.w3.lido_contracts.lido_locator.withdrawal_vault(blockstamp.block_hash)[2:].lower()
        wc_postfix = '0' * 22 + wc_address

        return [
            HexStr(ETH1_ADDRESS_WITHDRAWAL_PREFIX + wc_postfix),
            HexStr(COMPOUNDING_WITHDRAWAL_PREFIX + wc_postfix),
        ]

    @lru_cache(maxsize=1)
    def get_pending_lido_validators(
        self,
        blockstamp: BlockStamp,
    ) -> dict[HexStr, PendingValidator]:
        """
        Return the list of Lido keys that already have pending deposits on the CL.

        Validates all BLS signatures and ensures there are no front-running attacks.
        """

        lido_wc_list = self.get_lido_wc_list(blockstamp)

        genesis_config = self.w3.cc.get_genesis()
        pending_deposits = self.w3.cc.get_pending_deposits(blockstamp)
        pending_lido_keys = self._get_lido_validators_with_keys(blockstamp)[1]
        pending_keys = {key.key: key for key in pending_lido_keys}

        pending_validators = {}
        invalid_keys = set()

        # Validate there are no frontrun
        for pending_deposit in pending_deposits:
            if pending_deposit.pubkey in pending_keys:
                # In case we already had a valid pending deposit for the key
                if pending_deposit.pubkey in pending_validators:
                    pending_validators[pending_deposit.pubkey][1].append(pending_deposit)
                    continue

                # If there already were valid validator with wrong wc
                if pending_deposit.pubkey in invalid_keys:
                    continue

                # In case if this is the first possibly valid pending deposit for the key
                if is_valid_deposit_signature(
                    pubkey=hex_str_to_bytes(pending_deposit.pubkey),
                    withdrawal_credentials=hex_str_to_bytes(pending_deposit.withdrawal_credentials),
                    amount=pending_deposit.amount,
                    signature=hex_str_to_bytes(pending_deposit.signature),
                    genesis_fork_version=hex_str_to_bytes(genesis_config.genesis_fork_version),
                    # Fork-agnostic domain since deposits are valid across forks
                    # genesis_validators_root=hex_str_to_bytes(genesis_config.genesis_validators_root),
                ):
                    lido_key = pending_keys[pending_deposit.pubkey]

                    if pending_deposit.withdrawal_credentials in lido_wc_list:
                        # Lido WC
                        pending_validators[pending_deposit.pubkey] = (lido_key, [pending_deposit])
                    else:
                        # Possible frontrun attack
                        invalid_keys.add(pending_deposit.pubkey)
                        logger.warning(
                            {
                                'msg': 'Ignoring key. Possible front run attack',
                                'value': pending_deposit.pubkey,
                            }
                        )

        return pending_validators

    @lru_cache(maxsize=1)
    def _get_lido_validators_with_keys(self, blockstamp: BlockStamp) -> tuple[list[LidoValidator], list[LidoKey]]:
        lido_keys = self.w3.kac.get_used_lido_keys(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp)
        self._kapi_sanity_check(len(lido_keys), blockstamp)

        return self.merge_validators_with_keys(lido_keys, validators)

    def _kapi_sanity_check(self, keys_count_received: int, blockstamp: BlockStamp):
        stats = self.w3.lido_contracts.lido.get_beacon_stat(blockstamp.block_hash)

        # Make sure that used keys fetched from Keys API are >= total number of
        # deposited validators from Staking Router.
        if keys_count_received < stats.deposited_validators:
            raise CountOfKeysDiffersException(
                f'Keys API Service returned lesser keys ({keys_count_received}) '
                f'than amount of deposited validators ({stats.deposited_validators}) returned from Staking Router'
            )

    @staticmethod
    def merge_validators_with_keys(
        keys: list[LidoKey],
        validators: list[Validator],
    ) -> tuple[list[LidoValidator], list[LidoKey]]:
        """Merging and filter non-lido validators."""
        validators_keys_dict = {validator.validator.pubkey: validator for validator in validators}

        lido_validators = []
        pending_lido_keys = []

        for key in keys:
            if key.key in validators_keys_dict:
                lido_validators.append(
                    LidoValidator(
                        lido_id=key,
                        **asdict(validators_keys_dict[key.key]),
                    )
                )
            else:
                pending_lido_keys.append(key)

        return lido_validators, pending_lido_keys

    @lru_cache(maxsize=1)
    def get_lido_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        merged_validators = self.get_active_lido_validators(blockstamp)
        no_operators = self.get_lido_node_operators(blockstamp)

        # Make sure even empty NO will be presented in dict
        no_validators: ValidatorsByNodeOperator = {
            (operator.staking_module.id, operator.id): [] for operator in no_operators
        }

        staking_module_address = {
            operator.staking_module.staking_module_address: operator.staking_module.id for operator in no_operators
        }

        for validator in merged_validators:
            global_no_id = (
                staking_module_address[validator.lido_id.moduleAddress],
                validator.lido_id.operatorIndex,
            )

            if global_no_id in no_validators:
                no_validators[global_no_id].append(validator)
            else:
                logger.warning(
                    {
                        'msg': f'Got global node operator id: {global_no_id}, '
                        f'but it`s not exist in staking router on block number: {blockstamp.block_number}',
                    }
                )

        return no_validators

    @lru_cache(maxsize=1)
    def get_lido_node_operators_by_modules(self, blockstamp: BlockStamp) -> dict[StakingModuleId, list[NodeOperator]]:
        result = {}

        modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        for module in modules:
            result[module.id] = self.w3.lido_contracts.staking_router.get_all_node_operator_digests(
                module, blockstamp.block_hash
            )

        return result

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> list[NodeOperator]:
        result = []

        for nos in self.get_lido_node_operators_by_modules(blockstamp).values():
            result.extend(nos)

        return result
