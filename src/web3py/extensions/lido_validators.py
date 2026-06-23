import logging
from dataclasses import asdict, dataclass
from enum import Enum
from itertools import chain
from typing import TYPE_CHECKING, Final

from eth_typing import ChecksumAddress, HexStr
from web3.module import Module

from src.constants import COMPOUNDING_WITHDRAWAL_PREFIX, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.providers.consensus.types import PendingConsolidation, PendingDeposit, Validator
from src.providers.keys.types import LidoKey
from src.services.deposit_signature_verification import is_valid_deposit_signature
from src.types import BlockStamp, Gwei, NodeOperatorGlobalIndex, NodeOperatorId, StakingModuleId
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.dataclass import FromResponse, Nested
from src.utils.types import hex_str_to_bytes
from src.utils.validator_state import get_max_effective_balance


class _Uninitialized:
    def __repr__(self) -> str:
        return "UNINITIALIZED"


UNINITIALIZED: Final = _Uninitialized()


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
    # WC Type
    withdrawal_credentials_type: int
    # Total staking module validators balance
    validators_balance_gwei: Gwei

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

    def __init__(
        self,
        lido_id: LidoKey,
        pending_topups: list[PendingDeposit] | None = None,
        consolidating_as_source: ConsolidationRequest | None | _Uninitialized = UNINITIALIZED,
        consolidating_as_target: list[ConsolidationRequest] | None = None,
        **kwargs,
    ):
        self.lido_id = lido_id

        super().__init__(**kwargs)

        self._pending_topups = pending_topups
        self._consolidating_as_source = consolidating_as_source
        self._consolidating_as_target = consolidating_as_target

    # ----- Extended relations for LidoValidator -----
    # These attributes track additional validator state from the consensus layer:
    # - pending_topups: List of pending deposits that will top up this validator's balance
    # - consolidating_as_source: Consolidation request where this validator is the source (donating balance)
    # - consolidating_as_target: List of consolidation requests where this validator is the target (receiving balance)
    # All these attributes must be explicitly initialized before access via their respective property setters.

    @property
    def pending_topups(self) -> list[PendingDeposit]:
        if self._pending_topups is None:
            raise RuntimeError("pending_topups has not been initialized")
        return self._pending_topups

    @property
    def consolidating_as_source(self) -> ConsolidationRequest | None:
        if isinstance(self._consolidating_as_source, _Uninitialized):
            raise RuntimeError("consolidating_as_source has not been initialized")
        return self._consolidating_as_source

    @property
    def consolidating_as_target(self) -> list[ConsolidationRequest]:
        if self._consolidating_as_target is None:
            raise RuntimeError("consolidating_as_target has not been initialized")
        return self._consolidating_as_target


@dataclass
class ConsolidationRequest(PendingConsolidation):
    amount: Gwei


class CountOfKeysDiffersException(Exception):
    pass


type ValidatorsByNodeOperator = dict[NodeOperatorGlobalIndex, list[LidoValidator]]
type PendingValidator = tuple[LidoKey, list[PendingDeposit]]


class LidoValidatorsProvider(Module):
    w3: Web3

    @lru_cache(maxsize=1)
    def get_active_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        deposits_by_pubkey: dict[str, list[PendingDeposit]] = {}
        for deposit in self.w3.cc.get_pending_deposits(blockstamp):
            deposits_by_pubkey.setdefault(deposit.pubkey, []).append(deposit)

        validators_by_index = self.w3.cc.get_validators_by_indexes(blockstamp)

        consolidation_by_source: dict[int, ConsolidationRequest] = {}
        consolidation_by_target: dict[int, list[ConsolidationRequest]] = {}
        for consolidation in self.w3.cc.get_pending_consolidations(blockstamp):
            source_validator = validators_by_index[consolidation.source_index]

            # Skip consolidations whose source validator is slashed.
            # https://github.com/ethereum/consensus-specs/blob/master/specs/electra/beacon-chain.md#new-process_pending_consolidations
            if source_validator.validator.slashed:
                continue

            req = ConsolidationRequest(
                source_index=consolidation.source_index,
                target_index=consolidation.target_index,
                # only 0x01 validators will be consolidated, so all incoming excess balances will be swept
                amount=Gwei(min(source_validator.balance, get_max_effective_balance(source_validator.validator))),
            )
            consolidation_by_source[consolidation.source_index] = req
            consolidation_by_target.setdefault(consolidation.target_index, []).append(req)

        lido_validators, _ = self._get_lido_validators_with_keys(blockstamp)
        return [
            LidoValidator(
                **asdict(lido_validator),
                pending_topups=deposits_by_pubkey.get(lido_validator.validator.pubkey, []),
                consolidating_as_source=consolidation_by_source.get(lido_validator.index),
                consolidating_as_target=consolidation_by_target.get(lido_validator.index, []),
            )
            for lido_validator in lido_validators
        ]

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

        Validates BLS signatures and filters out deposits with non-Lido withdrawal credentials.
        """
        lido_wc_list = self.get_lido_wc_list(blockstamp)
        genesis_config = self.w3.cc.get_genesis()
        pending_deposits = self.w3.cc.get_pending_deposits(blockstamp)
        (_, pending_lido_keys) = self._get_lido_validators_with_keys(blockstamp)
        pending_keys: dict[str, LidoKey] = {key.key: key for key in pending_lido_keys}

        valid = self._collect_valid_pending_deposits(
            pending_deposits,
            set(pending_keys.keys()),
            lido_wc_list,
            hex_str_to_bytes(genesis_config.genesis_fork_version),
        )
        return {HexStr(pubkey): (pending_keys[pubkey], deposits) for pubkey, deposits in valid.items()}

    @staticmethod
    def _collect_valid_pending_deposits(
        pending_deposits: list[PendingDeposit],
        filter_pubkeys: set[str],
        lido_wc_list: list[HexStr],
        genesis_fork_version: bytes,
    ) -> dict[str, list[PendingDeposit]]:
        """Core frontrun-detection loop.

        Returns pending deposits grouped by pubkey, only for pubkeys in filter_pubkeys.
        A key whose first valid-signature deposit uses non-Lido WC is treated as a
        frontrun and excluded entirely along with any subsequent deposits for that key.
        """
        result: dict[str, list[PendingDeposit]] = {}
        invalid_keys: set[str] = set()

        for d in pending_deposits:
            if d.pubkey not in filter_pubkeys:
                continue

            if d.pubkey in result:
                result[d.pubkey].append(d)
                continue

            if d.pubkey in invalid_keys:
                continue

            if not is_valid_deposit_signature(
                pubkey=hex_str_to_bytes(d.pubkey),
                withdrawal_credentials=hex_str_to_bytes(d.withdrawal_credentials),
                amount=d.amount,
                signature=hex_str_to_bytes(d.signature),
                genesis_fork_version=genesis_fork_version,
                # Fork-agnostic domain since deposits are valid across forks
                # genesis_validators_root=hex_str_to_bytes(genesis_config.genesis_validators_root),
            ):
                continue

            if d.withdrawal_credentials in lido_wc_list:
                result[d.pubkey] = [d]
            else:
                invalid_keys.add(d.pubkey)
                logger.warning(
                    {
                        'msg': 'Ignoring key. Possible front run attack',
                        'value': d.pubkey,
                    }
                )

        return result

    @lru_cache(maxsize=1)
    def _get_lido_validators_with_keys(self, blockstamp: BlockStamp) -> tuple[list[LidoValidator], list[LidoKey]]:
        lido_keys = self.w3.kac.get_used_lido_keys(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp)
        self._kapi_sanity_check(len(lido_keys), blockstamp)

        return self.compute_lido_validators(lido_keys, validators)

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
    def compute_lido_validators(
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
                staking_module_address[validator.lido_id.module_address],
                validator.lido_id.operator_index,
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
        modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        return {
            module.id: self.w3.lido_contracts.staking_router.get_all_node_operator_digests(
                module,
                blockstamp.block_hash,
            )
            for module in modules
        }

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> list[NodeOperator]:
        return list(chain.from_iterable(self.get_lido_node_operators_by_modules(blockstamp).values()))
