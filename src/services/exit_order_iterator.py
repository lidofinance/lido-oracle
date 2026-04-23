import logging
from dataclasses import dataclass
from typing import cast

from src.constants import (
    CURATED_V1_TYPE,
    CURATED_V2_TYPE,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    TOTAL_BASIS_POINTS,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.common.types import ChainConfig
from src.providers.execution.contracts.curated_staking_module import CuratedStakingModuleContract
from src.providers.execution.contracts.meta_registry import MetaRegistryContract, OperatorGroup
from src.services.validator_state import LidoValidatorStateService
from src.types import Gwei, NodeOperatorGlobalIndex, ReferenceBlockStamp, StakingModuleId
from src.utils.validator_balance import get_predictable_balance
from src.utils.validator_state import get_max_effective_balance, is_on_exit
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    NodeOperator,
    NodeOperatorLimitMode,
    StakingModule,
)
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


type CMv1 = tuple[StakingModuleId, CuratedStakingModuleContract]
type CMv2 = tuple[StakingModuleId, CuratedStakingModuleContract]


@dataclass
class StakingModuleStats:
    staking_module: StakingModule
    predictable_balance: Gwei = Gwei(0)

    total_stake: Gwei = Gwei(0)
    total_weight: float = 0


@dataclass
class NodeOperatorStats:
    node_operator: NodeOperator
    module_stats: StakingModuleStats

    predictable_validators: int = 0
    predictable_balance: Gwei = Gwei(0)

    total_stake: Gwei = Gwei(0)

    # Link to group if NO is internal to CMv2
    internal_operator_group: OperatorGroup | None = None
    # Link to group if NO is external to CMv2
    external_operator_group: OperatorGroup | None = None

    weight: float = 10 * TOTAL_BASIS_POINTS

    force_exit_to: int | None = None
    soft_exit_to: int | None = None


class NodeOperatorAlreadyGroupedError(Exception):
    """
    Exception raised when trying to group a node operator that is already part of a group.
    Avoiding double accounting of the same node operator in different groups better do not build report at all
    """


class NodeOperatorExpectedToBeInCMv1Error(Exception):
    """
    Exception raised when an external node operator has other than CMv1 staking module.
    """


class WeightsNotUpdatedError(Exception):
    """
    In rare case weight could be unbalanced on the VEBO reference slot. In this case hope somebody will trigger
    a permissionless handle and a report will be generated on next frame.
    """


class CuratedModuleNotFoundError(Exception):
    """
    Exception raised when Curated Module v1 and Curated Module v2 not found.
    """


class ModulesWithSameTypeError(Exception):
    """
    Exception raised when multiple curated module v1 or v2 found.
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
    | V       |                                                                       | Highest deviation from the target stake               |                        |
    | V       |                                                                       |                                                       | Lowest validator index |
    """  # noqa: E501

    max_current_exit_balance: Gwei
    exit_limit_in_gwei: Gwei
    total_lido_predictable_balance: Gwei
    module_stats: dict[StakingModuleId, StakingModuleStats]
    node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats]
    exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]]

    cm_v2_id: StakingModuleId

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
        self.exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]] = {}

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
        for _, node_operators in sm_node_operators.items():
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

    def _prepare_validator_stats(self):
        recently_requested_indexes = self.lvs.get_recently_requested_to_exit_validators_by_node_operator(
            self.chain_config.seconds_per_slot,
            self.blockstamp,
        )
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        for gid, validators_list in lido_validators.items():
            self.exitable_validators[gid] = sorted(
                filter(self._make_exit_predicate(gid, recently_requested_indexes), validators_list),
                key=lambda v: v.index,
            )

    def _calculate_lido_stats(self):
        # Calculate current stats on CL
        self._calculate_current_cl_balance()
        self._calculate_pending_validator_cl_balance()
        self._finalize_cm_v1_and_cm_v2_stats()
        self._calculate_sm_weights()

    def _calculate_current_cl_balance(self):
        for gid, validators in self.exitable_validators.items():
            self.node_operators_stats[gid].predictable_validators += len(validators)

            # Calculate predictable effective balance by each NO
            for v in validators:
                validator_predictable_balance = get_predictable_balance(v)

                # --- Update lido stats ---
                self.total_lido_predictable_balance += validator_predictable_balance
                self.module_stats[gid[0]].total_stake += validator_predictable_balance
                self.module_stats[gid[0]].predictable_balance += validator_predictable_balance
                self.node_operators_stats[gid].predictable_balance += validator_predictable_balance
                self.node_operators_stats[gid].total_stake += validator_predictable_balance

    def _calculate_pending_validator_cl_balance(self):
        pending_validators = self.w3.lido_validators.get_pending_lido_validators(self.blockstamp)

        sm_by_address = self.w3.lido_contracts.staking_router.get_staking_modules_by_address(self.blockstamp.block_hash)

        for _, (lido_key, deposits) in pending_validators.items():
            sm_id = sm_by_address[lido_key.module_address].id

            predictable_balance = min(
                sum(d.amount for d in deposits),
                MAX_EFFECTIVE_BALANCE
                if deposits[0].withdrawal_credentials[:4] == ETH1_ADDRESS_WITHDRAWAL_PREFIX
                else MAX_EFFECTIVE_BALANCE_ELECTRA,
            )

            self.total_lido_predictable_balance += predictable_balance
            self.module_stats[sm_id].predictable_balance += predictable_balance
            self.module_stats[sm_id].total_stake += predictable_balance
            self.node_operators_stats[(sm_id, lido_key.operator_index)].predictable_validators += 1
            self.node_operators_stats[(sm_id, lido_key.operator_index)].predictable_balance += predictable_balance
            self.node_operators_stats[(sm_id, lido_key.operator_index)].total_stake += predictable_balance

    def _finalize_cm_v1_and_cm_v2_stats(self):
        cm_v1, cm_v2 = self._fetch_curated_modules()

        self._setup_weights(cm_v2)
        self._setup_meta_connections(cm_v1, cm_v2)
        self.cm_v2_id = cm_v2[0]

    def _fetch_curated_modules(self) -> tuple[CMv1, CMv2]:
        cm_v1_id = None
        cm_v1_contract = None
        cm_v2_id = None
        cm_v2_contract = None

        for module in self.module_stats.values():
            sm_contract = cast(
                CuratedStakingModuleContract,
                self.w3.eth.contract(
                    address=module.staking_module.staking_module_address,
                    ContractFactoryClass=CuratedStakingModuleContract,
                    decode_tuples=True,
                ),
            )

            sm_type = sm_contract.get_type(self.blockstamp.block_hash)

            if sm_type == CURATED_V1_TYPE:
                if cm_v1_id is not None:
                    raise ModulesWithSameTypeError(
                        f'Multiple curated module v1 found: {cm_v1_id} and {module.staking_module.id}'
                    )
                cm_v1_id = module.staking_module.id
                cm_v1_contract = sm_contract

            elif sm_type == CURATED_V2_TYPE:
                if cm_v2_id is not None:
                    raise ModulesWithSameTypeError(
                        f'Multiple curated module v2 found: {cm_v2_id} and {module.staking_module.id}'
                    )
                cm_v2_id = module.staking_module.id
                cm_v2_contract = sm_contract

        if not (cm_v1_id and cm_v1_contract and cm_v2_id and cm_v2_contract):
            msg = f'Curated Module v1 or v2 not found. CMv1 id: {cm_v1_id} | CMV2 id: {cm_v2_id}'

            logger.error({'msg': msg})
            raise CuratedModuleNotFoundError(msg)

        return (cm_v1_id, cm_v1_contract), (cm_v2_id, cm_v2_contract)

    def _setup_weights(self, curated_module: CMv2) -> None:
        staking_module_id, sm_contract = curated_module

        no_ids = [
            no.node_operator.id
            for no in self.node_operators_stats.values()
            if no.module_stats.staking_module.id == staking_module_id
        ]

        to_update_count = sm_contract.get_node_operator_deposit_info_to_update_count(self.blockstamp.block_hash)
        if to_update_count != 0:
            msg = f'Weights are not updated for Curated Module v2 (id: {staking_module_id}).'
            logger.error({'msg': msg})
            raise WeightsNotUpdatedError(msg)

        weights = sm_contract.get_operator_weights(no_ids, self.blockstamp.block_hash)

        for index, no_id in enumerate(no_ids):
            self.node_operators_stats[(staking_module_id, no_id)].weight = weights[index]

    def _setup_meta_connections(self, cm_v1: CMv1, cm_v2: CMv2) -> None:
        _, cm_v2_contract = cm_v2

        # Get meta-registry and connect all NO
        meta_registry = cast(
            MetaRegistryContract,
            self.w3.eth.contract(
                address=cm_v2_contract.get_meta_registry_address(self.blockstamp.block_hash),
                ContractFactoryClass=MetaRegistryContract,
                decode_tuples=True,
            ),
        )

        for group in meta_registry.get_all_groups(self.blockstamp.block_hash):
            self._process_group(group, cm_v1, cm_v2)

    def _process_group(self, group: OperatorGroup, cm_v1: CMv1, cm_v2: CMv2) -> None:
        cm_v1_id, _ = cm_v1
        cm_v2_id, _ = cm_v2

        external_balance = Gwei(0)
        external_gids = []

        for no in group.external_operators:
            gid = no.get_gid()

            if gid[0] != cm_v1_id:
                raise NodeOperatorExpectedToBeInCMv1Error(
                    f"Node operator {gid} is expected to be in CMv1, but it is not. CMv1 id: {cm_v1_id}"
                )

            if (
                self.node_operators_stats[gid].internal_operator_group
                or self.node_operators_stats[gid].external_operator_group
            ):
                raise NodeOperatorAlreadyGroupedError(f"Node operator {gid} is already persists in a group.")
            self.node_operators_stats[gid].external_operator_group = group

            external_gids.append(gid)
            external_balance += self.node_operators_stats[gid].predictable_balance

        internal_weight = 0
        internal_balance = Gwei(0)

        for no in group.sub_node_operators:
            gid = (cm_v2_id, no.node_operator_id)

            if (
                self.node_operators_stats[gid].internal_operator_group
                or self.node_operators_stats[gid].external_operator_group
            ):
                raise NodeOperatorAlreadyGroupedError(f"Node operator {gid} is already persists in a group.")
            self.node_operators_stats[gid].internal_operator_group = group

            internal_balance += self.node_operators_stats[gid].predictable_balance
            internal_weight += self.node_operators_stats[gid].weight

        if not group.has_connection():
            # Case if the group is not fulfilled, it means that the group doesn't have connections
            # We can skip additional calculations.
            return

        for no in group.sub_node_operators:
            gid = (cm_v2_id, no.node_operator_id)
            self.node_operators_stats[gid].total_stake += (
                external_balance * self.node_operators_stats[gid].weight / internal_weight
            )

        for gid in external_gids:
            self.node_operators_stats[gid].total_stake += internal_balance / len(external_gids)
            self.node_operators_stats[gid].weight += internal_weight / len(external_gids)

        self.module_stats[cm_v1_id].total_stake += internal_balance
        self.module_stats[cm_v2_id].total_stake += external_balance

    def _calculate_sm_weights(self) -> None:
        for (sm_id, _), node_operator in self.node_operators_stats.items():
            self.module_stats[sm_id].total_weight += node_operator.weight

    def _get_report_limits(self) -> None:
        self.exit_limit_in_gwei = Gwei(
            self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(
                self.blockstamp.block_hash,
            ).max_balance_exit_requested_per_report_in_eth
            * 10**9
        )

    # --- Iterator ---
    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        for node_operator in sorted(self.node_operators_stats.values(), key=self._no_predicate):
            gid = (
                node_operator.module_stats.staking_module.id,
                node_operator.node_operator.id,
            )
            # Check if there are exitable validators
            # get the next node operator if yes
            if not self.exitable_validators[gid]:
                continue

            v: LidoValidator = self._eject_validator(gid)
            self.max_current_exit_balance += get_max_effective_balance(v.validator)

            if self.max_current_exit_balance > self.exit_limit_in_gwei:
                raise StopIteration

            return gid, v

        raise StopIteration

    @staticmethod
    def _make_exit_predicate(gid: NodeOperatorGlobalIndex, indexes: dict):
        def is_validator_exitable(validator: LidoValidator) -> bool:
            """Returns True if the validator is exitable: not on exit and not requested to exit"""
            return (
                not is_on_exit(validator)
                and validator.index not in indexes[gid]
                and validator.consolidating_as_source is None
            )

        return is_validator_exitable

    def _eject_validator(self, gid: NodeOperatorGlobalIndex) -> LidoValidator:
        lido_validator = self.exitable_validators[gid].pop(0)

        exit_balance = get_predictable_balance(lido_validator)

        # Change lido total
        self.total_lido_predictable_balance -= exit_balance
        # Change module total
        self.module_stats[gid[0]].predictable_balance -= exit_balance
        # Change node operator stats
        self.node_operators_stats[gid].predictable_validators -= 1
        self.node_operators_stats[gid].predictable_balance -= exit_balance

        self._decrease_affected_stake(gid, exit_balance)

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

    def _decrease_affected_stake(self, gid: NodeOperatorGlobalIndex, exit_balance: Gwei) -> None:
        self.module_stats[gid[0]].total_stake -= exit_balance
        self.node_operators_stats[gid].total_stake -= exit_balance

        i_group = self.node_operators_stats[gid].internal_operator_group
        if i_group and i_group.has_connection():
            self.module_stats[i_group.external_operators[0].get_gid()[0]].total_stake -= exit_balance

            for op in i_group.external_operators:
                self.node_operators_stats[op.get_gid()].total_stake -= exit_balance / len(i_group.external_operators)

        e_group = self.node_operators_stats[gid].external_operator_group
        if e_group and e_group.has_connection():
            self.module_stats[self.cm_v2_id].total_stake -= exit_balance

            total_weight = sum(
                self.node_operators_stats[(self.cm_v2_id, no.node_operator_id)].weight
                for no in e_group.sub_node_operators
            )
            for op in e_group.sub_node_operators:
                self.node_operators_stats[(self.cm_v2_id, op.node_operator_id)].total_stake -= (
                    exit_balance * self.node_operators_stats[(self.cm_v2_id, op.node_operator_id)].weight / total_weight
                )

    def _no_predicate(self, node_operator: NodeOperatorStats) -> tuple:
        return (
            -self._no_force_predicate(node_operator),
            -self._no_soft_predicate(node_operator),
            -self._max_share_rate_coefficient_predicate(node_operator),
            -self._no_target_balance_deviation_predicate(node_operator),
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
        Sort staking modules by share rate coefficient predicate.
        If a SM has a share rate coefficient that is higher than the maximum share rate coefficient,
        NOs in this module have high priority to exit.
        If there is no higher share rate, we look at SM size. Bigger SM size means higher priority.

        if  0 <  result     - sm has excess balance.
        if -1 <= result < 0 - sm has ok balance.
        if -2 == result     - sm has no balance.

        -------- -2 ------------ -1 -------------------------- 0 ----------------------------> Higher exit priority
        ---- sm with balance --- -1 --- sm with ok balance --- 0 --- sm with a lot of ETH --->
        """
        if node_operator.module_stats.predictable_balance == 0:
            return -2

        max_share_rate = node_operator.module_stats.staking_module.priority_exit_share_threshold / TOTAL_BASIS_POINTS
        max_module_predictable_balance = int(max_share_rate * float(self.total_lido_predictable_balance))

        if node_operator.module_stats.predictable_balance > max_module_predictable_balance:
            return node_operator.module_stats.predictable_balance - max_module_predictable_balance

        return -1 / node_operator.module_stats.predictable_balance

    @staticmethod
    def _no_target_balance_deviation_predicate(node_operator: NodeOperatorStats) -> Gwei:
        """
        Highest deviation current balance from target stake rate by weight.
        """
        target_no_stake = (
            node_operator.module_stats.total_stake * node_operator.weight / node_operator.module_stats.total_weight
        )

        return Gwei(node_operator.total_stake - target_no_stake)

    def _lowest_validator_index_predicate(self, node_operator: NodeOperatorStats) -> int:
        """
        --- 0 -----------------------------------------------> Lower exit priority
        ---------- val 100 ------ val 200 ----- val 340 ----->
        """
        gid = (node_operator.module_stats.staking_module.id, node_operator.node_operator.id)
        validators = self.exitable_validators[gid]
        # all validators in exitable_validators are sorted
        # If NO doesn't have exitable validators - sorting by validator index doesn't matter
        return validators[0].index if validators else 0

    def get_remaining_forced_validators(self) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        """
        Returns a list of validators from NOs that are requested for forced exit.
        This includes an additional scenario where enough validators have been ejected
        to fulfill the withdrawal requests, but forced ejections are still necessary.
        """
        result: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []

        while True:
            for no_stats in sorted(self.node_operators_stats.values(), key=self.no_remaining_forced_predicate):
                if self._no_force_predicate(no_stats) == 0:
                    # The current and all further NOs in the list have no forced validators to exit. Cycle done
                    return result

                gid = (
                    no_stats.node_operator.staking_module.id,
                    no_stats.node_operator.id,
                )

                if self.exitable_validators[gid]:
                    v = self._eject_validator(gid)
                    self.max_current_exit_balance += get_max_effective_balance(v.validator)

                    if self.max_current_exit_balance > self.exit_limit_in_gwei:
                        return result

                    result.append((gid, v))
                    break
            else:
                break

        return result

    def no_remaining_forced_predicate(self, no: NodeOperatorStats) -> tuple:
        return (
            -self._no_force_predicate(no),
            self._lowest_validator_index_predicate(no),
        )
