import logging
from collections import defaultdict
from dataclasses import dataclass

from src.constants import TOTAL_BASIS_POINTS
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.submodules.types import ChainConfig
from src.services.validator_state import LidoValidatorStateService
from src.types import ReferenceBlockStamp, NodeOperatorGlobalIndex, StakingModuleId, Gwei
from src.utils.validator_state import is_on_exit, get_max_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator, StakingModule, NodeOperator, NodeOperatorLimitMode, \
    AllocationType
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


@dataclass
class StakingModuleStats:
    staking_module: StakingModule
    predictable_balance: Gwei = 0


@dataclass
class NodeOperatorStats:
    node_operator: NodeOperator
    module_stats: StakingModuleStats

    predictable_validators: int = 0
    predictable_balance: Gwei = 0

    weight: float = 1

    force_exit_to: int | None = None
    soft_exit_to: int | None = None


def get_validator_balance_by_index(lido_validators, source_index):
    for validators in lido_validators.values():
        for validator in validators:
            if validator.index == source_index:
                return validator.balance

    # If validator not found it is probably non-lido one. We can ignore it to optimize search
    return 0


def get_effective_balance(validator: LidoValidator, incoming_balance: Gwei = Gwei(0)) -> Gwei:
    return min(
        get_max_effective_balance(validator.validator),
        Gwei(validator.balance + incoming_balance),
    )



class ValidatorExitIterator:
    """
    To determine which validators to request for exit, the VEBO selects one entry
    from the sorted list of exitable Lido validators until the demand in WQ is covered by
    the exiting validators and future rewards, or until the limit per report is reached.

    Staking Router v2.0 ejection order.

    | Sorting | Module                                      | Node Operator                                         | Validator              |
    | ------- | ------------------------------------------- | ----------------------------------------------------- | ---------------------- |
    | V       |                                             | Highest number of targeted validators to boosted exit |                        |
    | V       |                                             | Highest number of targeted validators to smooth exit  |                        |
    | V       | Highest deviation from the exit share limit |                                                       |                        |
    | V       |                                             | Highest number of validators                          |                        |
    | V       |                                             |                                                       | Lowest validator index |
    """
    index: int = 0
    total_lido_predictable_balance: int = 0
    module_stats: dict[StakingModuleId, StakingModuleStats] = {}
    node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats] = {}
    exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]] = {}

    max_balance_to_exit: int = 0

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

    def _reset_attributes(self):
        self.module_stats = {}
        self.node_operators_stats = {}
        self.exitable_validators = {}

    @duration_meter()
    def __iter__(self) -> 'ValidatorExitIterator':
        self.exit_balance = 0
        self.total_lido_predictable_balance = 0
        self._reset_attributes()
        self._prepare_data_structure()
        self._calculate_lido_stats()
        self._load_blockchain_state()
        return self

    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        for node_operator in sorted(self.node_operators_stats.values(), key=self._no_predicate):
            gid = (
                node_operator.module_stats.staking_module.id,
                node_operator.node_operator.id,
            )
            # Check if there is exitable validators
            # get next node operator if yes
            if not self.exitable_validators[gid]:
                continue

            validator = self._eject_validator(gid)
            self.exit_balance += get_effective_balance(validator)

            if self.exit_balance > self.max_balance_to_exit:
                raise StopIteration

            return gid, validator

        raise StopIteration

    def _prepare_data_structure(self):
        modules = self.w3.lido_contracts.staking_router.get_staking_modules(self.blockstamp.block_hash)
        for module in modules:
            self.module_stats[module.id] = StakingModuleStats(module)

        node_operators = self.w3.lido_validators.get_lido_node_operators(self.blockstamp)
        for node_operator in node_operators:
            self.node_operators_stats[(node_operator.staking_module.id, node_operator.id)] = NodeOperatorStats(
                node_operator,
                self.module_stats[node_operator.staking_module.id],
            )

        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        for gid, validators_list in lido_validators.items():
            # All consolidation source validators has exit epoch and will be filtered here
            self.exitable_validators[gid] = list(filter(self.get_can_request_exit_predicate(gid), validators_list))
            self.exitable_validators[gid].sort(key=lambda val: val.index)

    def _calculate_lido_stats(self):
        # Calculate currents stats on CL
        self._calculate_lido_cl_stats()
        # Calculate all new validators coming, but not yet on CL
        self._calculate_lido_predictable_stats()


    def _calculate_lido_cl_stats(self):
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        state = self.w3.cc.get_state_view(self.blockstamp)

        # get all pending deposits
        pending_deposits_by_pubkey = defaultdict(list)
        for deposit in state.pending_deposits:
            pending_deposits_by_pubkey[deposit.pubkey].append(deposit)

        # Get all consolidations
        pending_consolidations_by_target_index = defaultdict(list)
        for consolidation in state.pending_consolidations:
            pending_consolidations_by_target_index[consolidation.target_index].append(consolidation)

        for gid, validators in self.exitable_validators.items():
            self.node_operators_stats[gid].predictable_validators += len(validators)

            if self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.FORCE:
                self.node_operators_stats[gid].force_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

            elif self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.SOFT:
                self.node_operators_stats[gid].soft_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

            # Calculate predictable effective balance by each NO
            for v in validators:
                # --- Calculate predictable effective balance ---
                validator_pending_deposits_balance = sum(pd.amount for pd in pending_deposits_by_pubkey[v.pubkey])
                # No double accounting of consolidations because each source validator can only have one valid consolidation request
                # Revise this if consolidations are allowed to be sent to multiple targets
                validator_pending_consolidations_balance = sum(get_validator_balance_by_index(lido_validators, pc.source_index) for pc in pending_consolidations_by_target_index[v.index])

                incoming_balance = Gwei(validator_pending_deposits_balance + validator_pending_consolidations_balance)
                validator_predictable_balance = get_effective_balance(v, incoming_balance)

                # --- Update lido stats ---
                self.total_lido_predictable_balance += validator_predictable_balance
                self.module_stats[gid[0]].predictable_balance += validator_predictable_balance
                self.node_operators_stats[gid].predictable_balance += validator_predictable_balance

    def _calculate_lido_predictable_stats(self):
        pass
    
    def _load_blockchain_state(self):
        self.max_balance_to_exit = self.w3.lido_contracts.oracle_daemon_config.max_validator_exit_balance_per_report(self.blockstamp.block_hash)

    def get_can_request_exit_predicate(self, gid: NodeOperatorGlobalIndex):
        """
        Validators that are presented but not yet activated on CL can be requested to exit in advance.

        There is an edge case when a validator's consolidation request is still in the queue to be processed.
        Theoretically, we can check it and verify if it is valid. If it is valid, the validator won't be excitable soon,
        but the check is very complex and requires more additional data and some prediction to make. Decided to skip it.
        """
        indexes = self.lvs.get_recently_requested_to_exit_validators_by_node_operator(self.chain_config.seconds_per_slot, self.blockstamp)

        def is_validator_exitable(validator: LidoValidator):
            """Returns True if the validator is exitable: not on exit and not requested to exit"""
            return not is_on_exit(validator) and validator.index not in indexes[gid]

        return is_validator_exitable

    def _eject_validator(self, gid: NodeOperatorGlobalIndex) -> LidoValidator:
        lido_validator = self.exitable_validators[gid].pop(0)

        exit_balance = get_effective_balance(lido_validator)

        # Change lido total
        self.total_lido_predictable_balance -= exit_balance
        # Change module total
        self.module_stats[gid[0]].predictable_balance -= exit_balance
        # Change node operator stats
        self.node_operators_stats[gid].predictable_validators -= 1
        self.node_operators_stats[gid].predictable_balance -= exit_balance

        logger.debug({
            'msg': 'Iterator state change. Eject validator.',
            'total_lido_predictable_balance': self.total_lido_predictable_balance,
            'no_gid': gid[0],
            'module_stats': self.module_stats[gid[0]].predictable_balance,
            'no_stats_exitable_validators': self.node_operators_stats[gid].predictable_balance,
        })

        return lido_validator

    def _no_predicate(self, node_operator: NodeOperatorStats) -> tuple:
        return (
            - self._no_force_predicate(node_operator),
            - self._no_soft_predicate(node_operator),
            - self._max_share_rate_coefficient_predicate(node_operator),
            - self._no_weight_predicate(node_operator),
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
        if expected is not None:
            if current > expected:
                return current - expected
        return 0

    def _max_share_rate_coefficient_predicate(self, node_operator: NodeOperatorStats) -> int:
        """
        The higher coefficient the higher priority to eject validator
        """
        max_share_rate = node_operator.module_stats.staking_module.priority_exit_share_threshold / TOTAL_BASIS_POINTS

        max_validators_count = int(max_share_rate * self.total_lido_predictable_balance)
        return max(node_operator.module_stats.predictable_balance - max_validators_count, 0)

    def _no_weight_predicate(self, node_operator: NodeOperatorStats) -> float:
        return node_operator.predictable_balance / node_operator.weight

    def _lowest_validator_index_predicate(self, node_operator: NodeOperatorStats) -> int:
        validators = self.exitable_validators[(
            node_operator.node_operator.staking_module.id,
            node_operator.node_operator.id,
        )]

        # If NO doesn't have exitable validators - sorting by validator index doesn't matter
        first_val_index = 0
        if validators:
            first_val_index = validators[0].index

        return first_val_index

    def get_remaining_forced_validators(self) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        """
        Returns a list of validators from NOs that are requested for forced exit.
        This includes an additional scenario where enough validators have been ejected to fulfill the withdrawal requests,
        but forced ejections are still necessary.
        """
        result: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []

        # Extra validators limited by VEBO report
        while self.index < self.max_balance_to_exit:
            for no_stats in sorted(self.node_operators_stats.values(), key=self.no_remaining_forced_predicate):
                if self._no_force_predicate(no_stats) == 0:
                    # The current and all further NOs in the list have no forced validators to exit. Cycle done
                    return result

                gid = (
                    no_stats.node_operator.staking_module.id,
                    no_stats.node_operator.id,
                )

                if self.exitable_validators[gid]:
                    # When found Node Operator
                    self.index += 1
                    result.append((gid, self._eject_validator(gid)))
                    break
            else:
                break

        return result

    def no_remaining_forced_predicate(self, no: NodeOperatorStats) -> tuple:
        return (
            -self._no_force_predicate(no),
            self._lowest_validator_index_predicate(no),
        )
