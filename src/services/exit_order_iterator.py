import logging
from dataclasses import dataclass
from typing import cast

from eth_typing import ChecksumAddress

from src.constants import (
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    TOTAL_BASIS_POINTS,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.common.types import ChainConfig
from src.providers.execution.contracts.curated_staking_module import CuratedStakingModuleContract
from src.providers.execution.contracts.meta_registry import MetaRegistryContract
from src.services.validator_state import LidoValidatorStateService
from src.types import Gwei, NodeOperatorGlobalIndex, NodeOperatorId, ReferenceBlockStamp, StakingModuleId
from src.utils.validator_balance import get_predictable_balance
from src.utils.validator_state import get_max_effective_balance, is_on_exit
from src.web3py.extensions.lido_validators import (
    ExtendedLidoValidator,
    NodeOperator,
    NodeOperatorLimitMode,
    StakingModule,
)
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


@dataclass
class StakingModuleStats:
    staking_module: StakingModule
    predictable_balance: Gwei = Gwei(0)


@dataclass
class NodeOperatorStats:
    node_operator: NodeOperator
    module_stats: StakingModuleStats

    predictable_validators: int = 0
    predictable_balance: Gwei = Gwei(0)

    weight: float = 1.0

    force_exit_to: int | None = None
    soft_exit_to: int | None = None
    # If this NO exists in some group in MetaRegistry already
    grouped: bool = False


class NodeOperatorAlreadyGrouped(Exception):
    """
    Exception raised when trying to group a node operator that is already part of a group.
    Avoiding double accounting of the same node operator in different groups better do not build report at all
    """


class WeightsRevert(Exception):
    """
    In rare case weight could be unbalanced on the VEBO reference slot. In this case hope somebody will trigger
    a permissionless handle and a report will be generated on next frame.
    """


class ValidatorExitIterator:
    """
    To determine which validators to request for exit, the VEBO selects one entry
    from the sorted list of exitable Lido validators until the demand in WQ is covered by
    the exiting validators and future rewards, or until the limit per report is reached.

    Staking Router v2.0 ejection order.

    | Sorting | Staking Module                                                        | Node Operator                                         | Validator              |
    | ------- | --------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------- |
    | V       |                                                                       | Highest number of targeted validators to boosted exit |                        |
    | V       |                                                                       | Highest number of targeted validators to smooth exit  |                        |
    | V       | Highest deviation from the exit share limit or the biggest by balance |                                                       |                        |
    | V       |                                                                       | Highest rate weight to effective balance              |                        |
    | V       |                                                                       |                                                       | Lowest validator index |
    """  # noqa: E501

    max_current_exit_balance: Gwei
    exit_limit_in_gwei: Gwei
    total_lido_predictable_balance: Gwei
    module_stats: dict[StakingModuleId, StakingModuleStats]
    node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats]
    exitable_validators: dict[NodeOperatorGlobalIndex, list[ExtendedLidoValidator]]

    def __init__(
        self,
        w3: Web3,
        blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        self.w3 = w3
        self.blockstamp = blockstamp
        self.chain_config = chain_config
        self.lvs = LidoValidatorStateService(self.w3)

    # --- Iterator initialization ---
    @duration_meter()
    def __iter__(self) -> ValidatorExitIterator:
        # Sum of all max effective balances for validators going to exit. Required to make sure we pass a sanity check.
        self.max_current_exit_balance = Gwei(0)

        self._reset_iterator_data()
        self._prepare_data_structure()
        self._calculate_lido_stats()
        self._get_report_limits()

        return self

    def _reset_iterator_data(self):
        self.total_lido_predictable_balance = Gwei(0)
        self.module_stats: dict[StakingModuleId, StakingModuleStats] = {}
        self.node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats] = {}
        self.exitable_validators: dict[NodeOperatorGlobalIndex, list[ExtendedLidoValidator]] = {}

    def _prepare_data_structure(self):
        self._prepare_module_stats()
        self._prepare_node_operator_stats()
        self._prepare_validator_stats()

    def _prepare_module_stats(self):
        modules = self.w3.lido_contracts.staking_router.get_staking_modules(self.blockstamp.block_hash)
        for module in modules:
            self.module_stats[module.id] = StakingModuleStats(module)

    def _prepare_node_operator_stats(self):
        sm_node_operators = self.w3.lido_validators.get_lido_node_operators_by_modules(self.blockstamp)
        for sm_id, node_operators in sm_node_operators.items():
            for node_operator in node_operators:
                self.node_operators_stats[(node_operator.staking_module.id, node_operator.id)] = NodeOperatorStats(
                    node_operator=node_operator,
                    module_stats=self.module_stats[node_operator.staking_module.id],
                    force_exit_to=(
                        node_operator.target_validators_count
                        if node_operator.is_target_limit_active == NodeOperatorLimitMode.FORCE
                        else None
                    ),
                    soft_exit_to=(
                        node_operator.target_validators_count
                        if node_operator.is_target_limit_active == NodeOperatorLimitMode.SOFT
                        else None
                    ),
                )

            # fetch weights for curated V2
            self._setup_cm_data(
                staking_module_id=sm_id,
                staking_module_address=self.module_stats[sm_id].staking_module.staking_module_address,
                no_ids=[no.id for no in node_operators],
            )

    def _setup_cm_data(
        self,
        staking_module_id: StakingModuleId,
        staking_module_address: ChecksumAddress,
        no_ids: list[NodeOperatorId],
    ) -> None:
        sm_contract = cast(
            CuratedStakingModuleContract,
            self.w3.eth.contract(
                address=staking_module_address,
                ContractFactoryClass=CuratedStakingModuleContract,
                decode_tuples=True,
            ),
        )
        sm_type = sm_contract.get_type(self.blockstamp.block_hash)

        if sm_type in []:
            self._setup_weights(staking_module_id, sm_contract, no_ids)
            self._setup_meta_connections(staking_module_id, sm_contract)

    def _setup_weights(
        self,
        staking_module_id: StakingModuleId,
        sm_contract: CuratedStakingModuleContract,
        no_ids: list[NodeOperatorId],
    ):
        try:
            weights = sm_contract.get_node_operator_weight(no_ids, self.blockstamp.block_hash)
        except Exception as e:
            raise WeightsRevert(f"Failed to get weights for node operators: {no_ids}") from e

        for index, no_id in enumerate(no_ids):
            self.node_operators_stats[(staking_module_id, no_id)].weight = weights[index]

    def _setup_meta_connections(
        self,
        staking_module_id: StakingModuleId,
        sm_contract: CuratedStakingModuleContract,
    ):
        # Get meta registy and connect all NO
        meta_registry = cast(
            MetaRegistryContract,
            self.w3.eth.contract(
                address=sm_contract.get_metaregistry_address(self.blockstamp.block_hash),
                ContractFactoryClass=MetaRegistryContract,
                decode_tuples=True,
            ),
        )

        groups = meta_registry.get_all_groups(self.blockstamp.block_hash)
        for group in groups:
            gids = []
            total_group_balance = Gwei(0)

            for no in group.sub_node_operators:
                gid = (staking_module_id, no.node_operator_id)
                gids.append(gid)
                total_group_balance += self.node_operators_stats[gid].predictable_balance

            for no in group.external_operators:
                gid = no.get_gid()
                total_group_balance += self.node_operators_stats[gid].predictable_balance
                gids.append(gid)

            for gid in gids:
                if self.node_operators_stats[gid].grouped:
                    raise NodeOperatorAlreadyGrouped(f"Node operator {gid} is already persists in a group.")

                self.node_operators_stats[gid].grouped = True
                self.node_operators_stats[gid].predictable_balance = total_group_balance

    def _prepare_validator_stats(self):
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        for gid, validators_list in lido_validators.items():
            self.exitable_validators[gid] = list(filter(self.get_can_request_exit_predicate(gid), validators_list))
            self.exitable_validators[gid].sort(key=lambda val: val.index)

    def _calculate_lido_stats(self):
        # Calculate current stats on CL
        self._calculate_current_cl_balance()
        self._calculate_pending_validator_cl_balance()

    def _calculate_current_cl_balance(self):
        for gid, validators in self.exitable_validators.items():
            self.node_operators_stats[gid].predictable_validators += len(validators)

            # Calculate predictable effective balance by each NO
            for v in validators:
                validator_predictable_balance = get_predictable_balance(v)

                # --- Update lido stats ---
                self.total_lido_predictable_balance += validator_predictable_balance
                self.module_stats[gid[0]].predictable_balance += validator_predictable_balance
                self.node_operators_stats[gid].predictable_balance += validator_predictable_balance

    def _calculate_pending_validator_cl_balance(self):
        pending_validators = self.w3.lido_validators.get_pending_lido_validators(self.blockstamp)

        sm_by_address = self.w3.lido_contracts.staking_router.get_staking_modules_by_address(self.blockstamp.block_hash)

        for _, (lido_key, deposits) in pending_validators.items():
            sm_id = sm_by_address[lido_key.moduleAddress].id

            predictable_balance = min(
                sum(d.amount for d in deposits),
                MAX_EFFECTIVE_BALANCE
                if deposits[0].withdrawal_credentials[:4] == ETH1_ADDRESS_WITHDRAWAL_PREFIX
                else MAX_EFFECTIVE_BALANCE_ELECTRA,
            )

            self.total_lido_predictable_balance += predictable_balance
            self.module_stats[sm_id].predictable_balance += predictable_balance
            self.node_operators_stats[(sm_id, lido_key.operatorIndex)].predictable_balance += predictable_balance

    def _get_report_limits(self):
        self.exit_limit_in_gwei = Gwei(
            self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(
                self.blockstamp.block_hash,
            ).max_balance_exit_requested_per_report_in_eth * 10**9
        )

    # --- Iterator ---
    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, ExtendedLidoValidator]:
        for node_operator in sorted(self.node_operators_stats.values(), key=self._no_predicate):
            gid = (
                node_operator.module_stats.staking_module.id,
                node_operator.node_operator.id,
            )
            # Check if there are exitable validators
            # get the next node operator if yes
            if not self.exitable_validators[gid]:
                continue

            v: ExtendedLidoValidator = self._eject_validator(gid)
            self.max_current_exit_balance += get_max_effective_balance(v.validator)

            if self.max_current_exit_balance > self.exit_limit_in_gwei:
                raise StopIteration

            return gid, v

        raise StopIteration

    def get_can_request_exit_predicate(self, gid: NodeOperatorGlobalIndex):
        """
        Validators that are presented but not yet activated on CL can be requested to exit in advance.

        There is an edge case when a validator's consolidation request is still in the queue to be processed.
        Theoretically, we can check it and verify if it is valid. If it is valid, the validator won't be excitable soon,
        but the check is very complex and requires more additional data and some prediction to make. Decided to skip it.
        """
        indexes = self.lvs.get_recently_requested_to_exit_validators_by_node_operator(
            self.chain_config.seconds_per_slot,
            self.blockstamp,
        )

        def is_validator_exitable(validator: ExtendedLidoValidator):
            """Returns True if the validator is exitable: not on exit and not requested to exit"""
            return (
                not is_on_exit(validator)
                and validator.index not in indexes[gid]
                and validator.consolidating_as_source is None
            )

        return is_validator_exitable

    def _eject_validator(self, gid: NodeOperatorGlobalIndex) -> ExtendedLidoValidator:
        lido_validator = self.exitable_validators[gid].pop(0)

        exit_balance = get_predictable_balance(lido_validator)

        # Change lido total
        self.total_lido_predictable_balance -= exit_balance
        # Change module total
        self.module_stats[gid[0]].predictable_balance -= exit_balance
        # Change node operator stats
        self.node_operators_stats[gid].predictable_validators -= 1
        self.node_operators_stats[gid].predictable_balance -= exit_balance

        logger.debug(
            {
                'msg': 'Iterator state change. Eject validator.',
                'total_lido_predictable_balance': self.total_lido_predictable_balance,
                'no_gid': gid[0],
                'module_stats': self.module_stats[gid[0]].predictable_balance,
                'no_stats_exitable_validators': self.node_operators_stats[gid].predictable_balance,
            }
        )

        return lido_validator

    def _no_predicate(self, node_operator: NodeOperatorStats) -> tuple:
        return (
            -self._no_force_predicate(node_operator),
            -self._no_soft_predicate(node_operator),
            -self._max_share_rate_coefficient_predicate(node_operator),
            -self._no_weight_predicate(node_operator),
            self._lowest_validator_index_predicate(node_operator),
        )

    @staticmethod
    def _no_force_predicate(node_operator: NodeOperatorStats) -> int:
        return ValidatorExitIterator._get_expected_validators_diff(
            node_operator.predictable_validators,
            node_operator.force_exit_to,
        )

    @staticmethod
    def _no_soft_predicate(node_operator: NodeOperatorStats) -> int:
        return ValidatorExitIterator._get_expected_validators_diff(
            node_operator.predictable_validators,
            node_operator.soft_exit_to,
        )

    @staticmethod
    def _get_expected_validators_diff(current: int, expected: int | None):
        if expected is not None and current > expected:
            return current - expected
        return 0

    def _max_share_rate_coefficient_predicate(self, node_operator: NodeOperatorStats) -> float:
        """
        The higher coefficient the higher priority to eject validator.

        if  0 <  result     - node operator has excess balance.
        if -1 <= result < 0 - node operators has ok balance.
        if -2 == result     - node operator has no balance.
        """
        if node_operator.module_stats.predictable_balance == 0:
            return -2

        max_share_rate = node_operator.module_stats.staking_module.priority_exit_share_threshold / TOTAL_BASIS_POINTS
        max_module_predictable_balance = int(max_share_rate * float(self.total_lido_predictable_balance))

        if node_operator.module_stats.predictable_balance > max_module_predictable_balance:
            return node_operator.module_stats.predictable_balance - max_module_predictable_balance

        return -1 / node_operator.module_stats.predictable_balance

    @staticmethod
    def _no_weight_predicate(node_operator: NodeOperatorStats) -> float:
        if node_operator.predictable_balance == 0:
            return 0

        return node_operator.predictable_balance / node_operator.weight

    def _lowest_validator_index_predicate(self, node_operator: NodeOperatorStats) -> int:
        validators = self.exitable_validators[
            (
                node_operator.node_operator.staking_module.id,
                node_operator.node_operator.id,
            )
        ]

        # If NO doesn't have exitable validators - sorting by validator index doesn't matter
        first_val_index = 0
        if validators:
            first_val_index = validators[0].index

        return first_val_index
