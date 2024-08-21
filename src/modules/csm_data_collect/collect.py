"""
(totalNoAttestationsSubmitted / totalNoAttestationsAssigned) >
    (totalNetworkAttestationsSubmitted / totalNetworkAttestationsAssigned) - 5% (1 July - 30 September)
AND totalUniqueEpochsAssigned > 6750

Prepares lists:
    - Good-performers
    - Bad-performers
    - Not enough participation
"""
import json
import logging
import sys
from collections import defaultdict

from src.constants import TOTAL_BASIS_POINTS
from src.modules.csm.checkpoint import FrameCheckpointsIterator, MinStepIsNotReached, FrameCheckpointProcessor
from src.modules.csm.csm import CSOracle
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.types import BlockStamp, NodeOperatorId, ValidatorIndex, EpochNumber

logger = logging.getLogger(__name__)

START_EPOCH = EpochNumber(62213)  # beginning of 1 July
END_EPOCH = EpochNumber(82913)    # beginning of 1 October
MIN_ACTIVE_EPOCHS = 6750  # 1 month
PERFORMANCE_LEEWAY_BP = 500  # 5%


class CSMDataCollect(CSOracle):
    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        collected = self.collect_data(last_finalized_blockstamp)
        if not collected:
            logger.info(
                {"msg": "Data required for the report is not fully collected yet. Waiting for the next finalized epoch"}
            )
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.calculate_performance(last_finalized_blockstamp)
        logger.info({"msg": "Data collected. Performance report is ready"})
        sys.exit(0)

    def collect_data(self, blockstamp: BlockStamp) -> bool:
        """Ongoing report data collection for the estimated reference slot"""

        l_epoch, r_epoch = START_EPOCH, END_EPOCH

        logger.info({"msg": f"Collecting data from {l_epoch} to {r_epoch}"})

        converter = self.converter(blockstamp)

        # Finalized slot is the first slot of justifying epoch, so we need to take the previous
        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(blockstamp.slot_number) - 1)
        if l_epoch > finalized_epoch:
            return False

        self.state.migrate(l_epoch, r_epoch)
        self.state.log_status()

        if done := self.state.is_fulfilled:
            logger.info({"msg": "All epochs are already processed. Nothing to collect"})
            return done

        try:
            checkpoints = FrameCheckpointsIterator(
                converter, min(self.state.unprocessed_epochs) or l_epoch, r_epoch, finalized_epoch
            )
        except MinStepIsNotReached:
            return False

        processor = FrameCheckpointProcessor(self.w3.cc, self.state, converter, blockstamp)

        for checkpoint in checkpoints:
            processor.exec(checkpoint)

        return self.state.is_fulfilled

    def calculate_performance(self, blockstamp: BlockStamp):
        """Computes performance of fee shares at the given timestamp"""

        logger.info({"msg": "Calculating performance"})

        threshold = self.state.avg_perf - PERFORMANCE_LEEWAY_BP / TOTAL_BASIS_POINTS
        operators_to_validators = self.module_validators_by_node_operators(blockstamp)

        # Build the map of the current distribution operators.
        good_performers: dict[NodeOperatorId, dict] = defaultdict(dict)
        bad_performers: dict[NodeOperatorId, dict] = defaultdict(dict)
        not_enough_participation: dict[NodeOperatorId, dict] = defaultdict(dict)
        for (_, no_id), validators in operators_to_validators.items():
            unique_assigned = set()
            total_assigned = 0
            total_included = 0
            for v in validators:
                try:
                    aggr = self.state.data[ValidatorIndex(int(v.index))]
                except KeyError:
                    # It's possible that the validator is not assigned to any duty, hence it's performance
                    # is not presented in the aggregates (e.g. exited, pending for activation etc).
                    continue
                else:
                    if v.validator.slashed:
                        continue
                    unique_assigned.update(set(range(
                        max(int(v.validator.activation_epoch), START_EPOCH),
                        min(int(v.validator.exit_epoch), END_EPOCH) + 1
                    )))

                total_assigned += aggr.assigned
                total_included += aggr.included

            total_perf = total_included / total_assigned if total_assigned else 0

            data = {
                "validators": len(validators),
                "unique_assigned": len(unique_assigned),
                "total_perf": total_perf,
                "total_assigned": total_assigned,
                "total_included": total_included,
            }

            if len(unique_assigned) >= MIN_ACTIVE_EPOCHS:
                if total_perf > threshold:
                    good_performers[no_id] = data
                else:
                    bad_performers[no_id] = data
            else:
                not_enough_participation[no_id] = data

        with open('out/good_performers.json', 'w') as f:
            json.dump(good_performers, f, indent=2)

        with open('out/bad_performers.json', 'w') as f:
            json.dump(bad_performers, f, indent=2)

        with open(f'out/less_than_{MIN_ACTIVE_EPOCHS}_assigned.json', 'w') as f:
            json.dump(not_enough_participation, f, indent=2)
