import logging
import math
from dataclasses import dataclass
from typing import cast

from src.constants import (
    CURATED_V1_MODULE_NAME,
    CURATED_V1_TYPE,
    CURATED_V2_MODULE_NAME,
    CURATED_V2_TYPE,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MIN_ACTIVATION_BALANCE,
    SHARD_COMMITTEE_PERIOD,
    TOTAL_BASIS_POINTS,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.oracles.ejector.data_encode import FWR_AMOUNT, MAX_PWR_AMOUNT, WithdrawalRequest
from src.providers.execution.contracts.curated_staking_module import CuratedStakingModuleContract
from src.providers.execution.contracts.meta_registry import MetaRegistryContract, OperatorGroup
from src.services.validator_state import InFlightWithdrawals, LidoValidatorStateService
from src.types import Gwei, NodeOperatorGlobalIndex, ReferenceBlockStamp, StakingModuleId, ValidatorIndex
from src.utils.validator_balance import get_predictable_inbound_balance
from src.utils.validator_state import has_compounding_withdrawal_credential, is_on_exit
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

# LIP-38: a validator is PWR-eligible while its balance is at least 1 ETH above MIN_ACTIVATION_BALANCE.
MIN_PWR_HEADROOM = Gwei(10**9)

GWEI_PER_ETH = 10**9


@dataclass(frozen=True)
class WithdrawalStep:
    """One iterator step: a chunk of demand given to one validator."""

    gid: NodeOperatorGlobalIndex
    validator: LidoValidator
    # PWR amount taken in this step, or FWR_AMOUNT for a full withdrawal.
    amount: Gwei
    # ETH the step adds to what the report brings in. An FWR counts the validator's balance
    # minus the PWRs it replaces, because those were already counted.
    inbound: Gwei


@dataclass
class _Allocation:
    gid: NodeOperatorGlobalIndex
    validator: LidoValidator
    amount: Gwei


@dataclass
class StakingModuleStats:
    staking_module: StakingModule
    partial_withdrawals_allowed: bool = False
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


class InvalidCuratedModuleConfigError(Exception):
    """
    Exception raised when curated modules cannot be uniquely identified from the current SR config.
    """


class ValidatorExitIterator:
    """
    Builds the VEBO report as withdrawal requests (LIP-38). Each step gives one EXIT_ITERATION_CHUNK
    of demand to the highest-ranked node operator, then ranks again.

    Phase 1 (`__next__`) runs until the caller sees the WQ demand covered.
    Phase 2 (`allocate_forced_exits`) then covers what is left of the forced exits.
    Both phases share one per-report exit limit and the cap on records per report.

    Within the selected operator:
    - an operator over its force-exit limit always gets an FWR;
    - otherwise a PWR from a validator that already has a PWR in this report, while it stays eligible;
    - otherwise a PWR from the PWR-eligible validator with the smallest balance;
    - otherwise an FWR for the validator with the lowest index.

    Node operator order:

    | Sorting | Staking Module                                                        | Node Operator                                         | Validator              |
    | ------- | --------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------- |
    | V       |                                                                       | Highest number of targeted validators to boosted exit |                        |
    | V       |                                                                       | Highest number of targeted validators to smooth exit  |                        |
    | V       | Highest deviation from the exit share limit or the biggest by balance |                                                       |                        |
    | V       |                                                                       | Highest deviation from the target stake               |                        |
    | V       |                                                                       |                                                       | Lowest validator index |
    """  # noqa: E501

    exit_limit_in_gwei: Gwei
    max_exit_requests_per_report: int
    fwr_weight_by_wc_type: dict[int, Gwei]
    chunk: Gwei
    in_flight: InFlightWithdrawals
    total_lido_predictable_balance: Gwei
    module_stats: dict[StakingModuleId, StakingModuleStats]
    node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats]
    exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]]

    cm_v2_id: StakingModuleId

    def __init__(self, w3: Web3, blockstamp: ReferenceBlockStamp):
        self.w3 = w3
        self.blockstamp = blockstamp
        self.lvs = LidoValidatorStateService(self.w3)

    # --- Iterator initialization ---
    @duration_meter()
    def __iter__(self) -> ValidatorExitIterator:
        self._reset_iterator_data()
        self._prepare_data_structure()
        self._calculate_lido_stats()
        self._get_report_limits()

        return self

    def _reset_iterator_data(self):
        self.total_lido_predictable_balance = Gwei(0)
        # Report records by validator, in report order. A PWR merged with a later step or replaced
        # by an FWR keeps its position.
        self._allocations: dict[ValidatorIndex, _Allocation] = {}
        self._pwr_total = Gwei(0)
        self._fwr_weight = Gwei(0)
        self.module_stats: dict[StakingModuleId, StakingModuleStats] = {}
        self.node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats] = {}
        self.exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]] = {}

    def _prepare_data_structure(self):
        self._prepare_module_stats()
        self._prepare_node_operator_stats()
        self._prepare_validator_stats()

    def _prepare_module_stats(self):
        modules = self.w3.lido_contracts.staking_router.get_staking_modules(self.blockstamp.block_hash)
        staking_router = self.w3.lido_contracts.staking_router
        for module in modules:
            self.module_stats[module.id] = StakingModuleStats(
                module,
                partial_withdrawals_allowed=staking_router.is_partial_withdrawals_allowed(
                    module.id, self.blockstamp.block_hash
                ),
            )

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
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        self.in_flight = self.lvs.get_in_flight_withdrawals(self.blockstamp)
        for gid, validators_list in lido_validators.items():
            self.exitable_validators[gid] = sorted(
                filter(self._is_validator_exitable, validators_list),
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
                validator_predictable_balance = get_predictable_inbound_balance(v)

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
        cm_v1_modules: list[CMv1] = []
        cm_v2_modules: list[CMv2] = []

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

            if sm_type == CURATED_V1_TYPE and module.staking_module.name == CURATED_V1_MODULE_NAME:
                cm_v1_modules.append((module.staking_module.id, sm_contract))

            elif sm_type == CURATED_V2_TYPE and module.staking_module.name == CURATED_V2_MODULE_NAME:
                cm_v2_modules.append((module.staking_module.id, sm_contract))

        errors = []
        if len(cm_v1_modules) != 1:
            errors.append(
                f'expected exactly one curated module named {CURATED_V1_MODULE_NAME}, '
                f'found ids: {[module_id for module_id, _ in cm_v1_modules]}'
            )
        if len(cm_v2_modules) != 1:
            errors.append(
                f'expected exactly one curated module v2 named {CURATED_V2_MODULE_NAME}, '
                f'found ids: {[module_id for module_id, _ in cm_v2_modules]}'
            )

        if errors:
            msg = '; '.join(errors)
            logger.error({'msg': msg})
            raise InvalidCuratedModuleConfigError(msg)

        return cm_v1_modules[0], cm_v2_modules[0]

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
            if internal_weight:
                self.node_operators_stats[gid].total_stake += (
                    external_balance * self.node_operators_stats[gid].weight / internal_weight
                )
            else:
                # In case if all NOs have weight == 0, split external stake by shares.
                self.node_operators_stats[gid].total_stake += external_balance * no.share / TOTAL_BASIS_POINTS

        for gid in external_gids:
            self.node_operators_stats[gid].total_stake += internal_balance / len(external_gids)
            self.node_operators_stats[gid].weight = internal_weight / len(external_gids)

        self.module_stats[cm_v1_id].total_stake += internal_balance
        self.module_stats[cm_v2_id].total_stake += external_balance

    def _calculate_sm_weights(self) -> None:
        for (sm_id, _), node_operator in self.node_operators_stats.items():
            self.module_stats[sm_id].total_weight += node_operator.weight

    def _get_report_limits(self) -> None:
        limits = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(
            self.blockstamp.block_hash,
        )
        self.exit_limit_in_gwei = Gwei(limits.max_balance_exit_requested_per_report_in_eth * GWEI_PER_ETH)
        # VEBO weighs an FWR at the max-EB weight of its module's WC type, read from the sanity checker.
        self.fwr_weight_by_wc_type = {
            1: Gwei(limits.max_effective_balance_weight_wc_type01 * GWEI_PER_ETH),
            2: Gwei(limits.max_effective_balance_weight_wc_type02 * GWEI_PER_ETH),
        }
        self.chunk = Gwei(
            self.w3.lido_contracts.oracle_daemon_config.exit_iteration_chunk_eth(self.blockstamp.block_hash)
            * GWEI_PER_ETH
        )
        self.max_exit_requests_per_report = (
            self.w3.lido_contracts.validators_exit_bus_oracle.get_max_requests_per_report(
                self.blockstamp.block_hash,
            )
        )

    # --- Iterator ---
    @duration_meter()
    def __next__(self) -> WithdrawalStep:
        """Phase 1: the next chunk of WQ demand."""
        for node_operator in sorted(self.node_operators_stats.values(), key=self._no_predicate):
            gid = (
                node_operator.module_stats.staking_module.id,
                node_operator.node_operator.id,
            )
            if not self.exitable_validators[gid]:
                continue

            pick = self._pick(gid, forced=self._no_force_predicate(node_operator) > 0)
            if pick is None:
                continue

            step = self._allocate(gid, *pick)
            if step is None:
                raise StopIteration
            return step

        raise StopIteration

    def allocate_forced_exits(self) -> list[WithdrawalStep]:
        """
        Phase 2: FWRs for node operators still over their force-exit limit after the WQ demand is covered.
        """
        steps: list[WithdrawalStep] = []

        while True:
            for no_stats in sorted(self.node_operators_stats.values(), key=self.no_remaining_forced_predicate):
                if self._no_force_predicate(no_stats) == 0:
                    # The current and all further NOs in the list have no forced validators to exit. Cycle done
                    return steps

                gid = (
                    no_stats.node_operator.staking_module.id,
                    no_stats.node_operator.id,
                )
                validator = self._pick_fwr_validator(gid)
                if validator is None:
                    continue

                step = self._allocate(gid, validator, FWR_AMOUNT)
                if step is None:
                    return steps
                steps.append(step)
                break
            else:
                return steps

    def get_requests(self) -> list[WithdrawalRequest]:
        """The report records, in report order."""
        return [
            WithdrawalRequest(
                module_id=allocation.gid[0],
                node_operator_id=allocation.gid[1],
                key_index=allocation.validator.lido_id.index,
                amount=allocation.amount,
            )
            for allocation in self._allocations.values()
        ]

    # --- Selection ---
    def _pick(self, gid: NodeOperatorGlobalIndex, forced: bool) -> tuple[LidoValidator, Gwei] | None:
        """PWR preferred; an operator over its force-exit limit always gets an FWR."""
        if not forced:
            pwr = self._pick_pwr_validator(gid)
            if pwr is not None:
                return pwr

        validator = self._pick_fwr_validator(gid)
        if validator is None:
            return None
        return validator, FWR_AMOUNT

    def _pick_pwr_validator(self, gid: NodeOperatorGlobalIndex) -> tuple[LidoValidator, Gwei] | None:
        if not self.module_stats[gid[0]].partial_withdrawals_allowed:
            return None

        candidates = [
            validator
            for validator in self.exitable_validators[gid]
            if self._is_selectable(validator) and self._pwr_headroom(validator) > 0
        ]
        if not candidates:
            return None

        # Keep taking from validators already in this report, then from the eligible one with the smallest balance.
        validator = min(
            candidates,
            key=lambda v: (v.index not in self._allocations, self._remaining_balance(v), v.index),
        )
        return validator, Gwei(min(self.chunk, self._pwr_headroom(validator)))

    def _pick_fwr_validator(self, gid: NodeOperatorGlobalIndex) -> LidoValidator | None:
        """
        Lowest index first. A validator with a PWR from an earlier report is skipped: the CL rejects
        an FWR while a PWR for the same validator is unprocessed.
        """
        for validator in self.exitable_validators[gid]:
            if self._is_selectable(validator) and validator.index not in self.in_flight.pwr_amounts:
                return validator
        return None

    def _is_selectable(self, validator: LidoValidator) -> bool:
        """The CL drops withdrawal requests for validators active for less than SHARD_COMMITTEE_PERIOD."""
        return validator.validator.activation_epoch + SHARD_COMMITTEE_PERIOD <= self.blockstamp.ref_epoch

    def _pwr_headroom(self, validator: LidoValidator) -> Gwei:
        """How much a PWR can still take from the validator in this report, 0 if it is not PWR-eligible."""
        if not has_compounding_withdrawal_credential(validator.validator):
            return Gwei(0)

        remaining = self._remaining_balance(validator) - MIN_ACTIVATION_BALANCE
        if remaining < MIN_PWR_HEADROOM:
            return Gwei(0)
        return Gwei(max(0, min(remaining, MAX_PWR_AMOUNT - self._report_pwr_amount(validator))))

    def _remaining_balance(self, validator: LidoValidator) -> Gwei:
        """Balance left after the PWRs requested in earlier reports and in this one."""
        return Gwei(
            validator.balance
            - self.in_flight.pwr_amounts.get(validator.index, Gwei(0))
            - self._report_pwr_amount(validator)
        )

    def _report_pwr_amount(self, validator: LidoValidator) -> Gwei:
        allocation = self._allocations.get(validator.index)
        return allocation.amount if allocation else Gwei(0)

    # --- Allocation ---
    def _allocate(self, gid: NodeOperatorGlobalIndex, validator: LidoValidator, amount: Gwei) -> WithdrawalStep | None:
        """Adds the step to the report, or returns None if it does not fit the report limits."""
        allocation = self._allocations.get(validator.index)
        in_report_pwr = allocation.amount if allocation else Gwei(0)

        if amount == FWR_AMOUNT:
            pwr_total = Gwei(self._pwr_total - in_report_pwr)
            fwr_weight = Gwei(self._fwr_weight + self._get_fwr_weight(gid))
            new_amount = FWR_AMOUNT
            inbound = Gwei(max(0, get_predictable_inbound_balance(validator) - in_report_pwr))
        else:
            pwr_total = Gwei(self._pwr_total + amount)
            fwr_weight = self._fwr_weight
            new_amount = Gwei(in_report_pwr + amount)
            inbound = amount

        records = len(self._allocations) + (0 if allocation else 1)
        if records > self.max_exit_requests_per_report:
            logger.info(
                {
                    'msg': 'Reached the max exit requests per report. '
                    'Dropped requests will be reported in the following frames.',
                    'limit': self.max_exit_requests_per_report,
                }
            )
            return None

        if self._get_exit_weight(pwr_total, fwr_weight) > self.exit_limit_in_gwei:
            return None

        self._pwr_total = pwr_total
        self._fwr_weight = fwr_weight
        if allocation:
            allocation.amount = new_amount
        else:
            self._allocations[validator.index] = _Allocation(gid, validator, new_amount)

        if new_amount == FWR_AMOUNT:
            self.exitable_validators[gid].remove(validator)
            self.node_operators_stats[gid].predictable_validators -= 1

        self._decrease_predictable_balance(gid, inbound)

        return WithdrawalStep(gid=gid, validator=validator, amount=amount, inbound=inbound)

    @staticmethod
    def _get_exit_weight(pwr_total: Gwei, fwr_weight: Gwei) -> Gwei:
        """Same weighing as the VEBO sanity check: PWR amounts are summed and rounded up to whole ETH."""
        return Gwei(math.ceil(pwr_total / GWEI_PER_ETH) * GWEI_PER_ETH + fwr_weight)

    def _get_fwr_weight(self, gid: NodeOperatorGlobalIndex) -> Gwei:
        wc_type = self.module_stats[gid[0]].staking_module.withdrawal_credentials_type
        if wc_type not in self.fwr_weight_by_wc_type:
            raise ValueError(f'Unknown withdrawal credentials type {wc_type} of staking module {gid[0]}.')
        return self.fwr_weight_by_wc_type[wc_type]

    def _decrease_predictable_balance(self, gid: NodeOperatorGlobalIndex, exit_balance: Gwei) -> None:
        self.total_lido_predictable_balance -= exit_balance
        self.module_stats[gid[0]].predictable_balance -= exit_balance
        self.node_operators_stats[gid].predictable_balance -= exit_balance

        self._decrease_affected_stake(gid, exit_balance)

        logger.debug(
            {
                'msg': 'Iterator state change. Allocate withdrawal.',
                'total_lido_predictable_balance': self.total_lido_predictable_balance,
                'no_gid': gid[0],
                'module_stats': self.module_stats[gid[0]].predictable_balance,
                'no_stats_exitable_validators': self.node_operators_stats[gid].predictable_balance,
            }
        )

    def _is_validator_exitable(self, validator: LidoValidator) -> bool:
        """Not on exit, no full withdrawal queued in the Bus, not a consolidation source."""
        return (
            not is_on_exit(validator)
            and validator.index not in self.in_flight.fwr_validators
            and validator.consolidating_as_source is None
        )

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
                if total_weight:
                    self.node_operators_stats[(self.cm_v2_id, op.node_operator_id)].total_stake -= (
                        exit_balance
                        * self.node_operators_stats[(self.cm_v2_id, op.node_operator_id)].weight
                        / total_weight
                    )
                else:
                    self.node_operators_stats[(self.cm_v2_id, op.node_operator_id)].total_stake -= (
                        exit_balance * op.share / TOTAL_BASIS_POINTS
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
        if node_operator.module_stats.total_weight == 0:
            return Gwei(node_operator.total_stake)

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

    def no_remaining_forced_predicate(self, no: NodeOperatorStats) -> tuple:
        return (
            -self._no_force_predicate(no),
            self._lowest_validator_index_predicate(no),
        )
