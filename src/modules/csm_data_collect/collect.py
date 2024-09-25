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
from typing import Callable, cast

from eth_typing import BlockNumber
from web3.contract.contract import ContractEvent
from web3.types import EventData

from src.constants import TOTAL_BASIS_POINTS
from src.modules.csm.checkpoint import FrameCheckpointsIterator, MinStepIsNotReached, FrameCheckpointProcessor
from src.modules.csm.csm import CSOracle
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.types import BlockStamp, NodeOperatorId, ValidatorIndex, EpochNumber
from src.utils.blockstamp import build_blockstamp
from src.utils.events import get_events_in_range
from src.utils.slot import get_next_non_missed_slot

logger = logging.getLogger(__name__)

START_EPOCH = EpochNumber(62213)  # beginning of 1 July
END_EPOCH = EpochNumber(82913)  # beginning of 1 October
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
        self.fetch_addresses(last_finalized_blockstamp)
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
        self.state.log_progress()

        if self.state.is_fulfilled:
            logger.info({"msg": "All epochs are already processed. Nothing to collect"})
            return True

        try:
            checkpoints = FrameCheckpointsIterator(
                converter, min(self.state.unprocessed_epochs) or l_epoch, r_epoch, finalized_epoch
            )
        except MinStepIsNotReached:
            return False

        processor = FrameCheckpointProcessor(self.w3.cc, self.state, converter, blockstamp)

        for checkpoint in checkpoints:
            processor.exec(checkpoint)
            # Recalculate performance after processing each checkpoint
            self.calculate_performance(blockstamp)

        return self.state.is_fulfilled

    def calculate_performance(self, blockstamp: BlockStamp):
        """Computes performance of fee shares at the given timestamp"""

        logger.info({"msg": "Calculating performance"})

        network_avg_perf = self.state.get_network_aggr().perf
        threshold = network_avg_perf - PERFORMANCE_LEEWAY_BP / TOTAL_BASIS_POINTS
        operators_to_validators = self.module_validators_by_node_operators(blockstamp)

        good_performers: dict[NodeOperatorId, dict] = defaultdict(dict)
        bad_performers: dict[NodeOperatorId, dict] = defaultdict(dict)
        not_enough_participation: dict[NodeOperatorId, dict] = defaultdict(dict)

        for (_, no_id), validators in operators_to_validators.items():
            unique_assigned = set()
            total_assigned = 0
            total_included = 0
            for v in validators:
                aggr = self.state.data.get(ValidatorIndex(int(v.index)))

                if aggr is None:
                    # It's possible that the validator is not assigned to any duty, hence it's performance
                    # is not presented in the aggregates (e.g. exited, pending for activation etc).
                    continue

                if v.validator.slashed is True:
                    # It means that validator was active during the frame and got slashed and didn't meet the exit
                    # epoch, so we should not count such validator for operator's share.
                    continue

                unique_assigned.update(
                    set(
                        range(
                            max(int(v.validator.activation_epoch), START_EPOCH),
                            min(int(v.validator.exit_epoch), END_EPOCH) + 1,
                        )
                    )
                )

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

        with open('out/threshold_info.json', 'w') as f:
            json.dump(
                {
                    "from_epoch": START_EPOCH,
                    "to_epoch": END_EPOCH,
                    "network_validators": len(self.state.data),
                    "network_avg_perf": network_avg_perf,
                    "perf_leeway": PERFORMANCE_LEEWAY_BP / TOTAL_BASIS_POINTS,
                    "perf_threshold": threshold,
                },
                f,
                indent=2,
            )

        with open('out/good_performers.json', 'w') as f:
            json.dump(good_performers, f, indent=2)

        with open('out/bad_performers.json', 'w') as f:
            json.dump(bad_performers, f, indent=2)

        with open(f'out/less_than_{MIN_ACTIVE_EPOCHS}_assigned.json', 'w') as f:
            json.dump(not_enough_participation, f, indent=2)

    def fetch_addresses(self, blockstamp: BlockStamp):
        logger.info({"msg": "Fetching addresses"})

        good_performers = json.load(open("out/good_performers.json", "r"))
        bad_performers = json.load(open("out/bad_performers.json", "r"))
        not_enough_participation = json.load(open(f"out/less_than_{MIN_ACTIVE_EPOCHS}_assigned.json", "r"))

        l_epoch = EpochNumber(59884)  # deploy date to fetch all needed events
        r_epoch = END_EPOCH
        converter = self.converter(blockstamp)

        l_slot = converter.get_epoch_first_slot(l_epoch)
        r_slot = converter.get_epoch_last_slot(r_epoch)

        l_blockstamp = build_blockstamp(
            get_next_non_missed_slot(
                self.w3.cc,
                l_slot,
                blockstamp.slot_number,
            )
        )

        r_blockstamp = build_blockstamp(
            get_next_non_missed_slot(
                self.w3.cc,
                # TODO: CHANGE TO r_slot
                min(r_slot, blockstamp.slot_number),
                blockstamp.slot_number,
            )
        )

        l_block_number = self.w3.eth.get_block(l_blockstamp.block_hash).get("number", BlockNumber(0))
        r_block_number = self.w3.eth.get_block(r_blockstamp.block_hash).get("number", BlockNumber(0))

        by_no_id: Callable[[EventData], int] = lambda e: e["args"]["nodeOperatorId"]

        node_operator_added_events = sorted(
            get_events_in_range(
                cast(ContractEvent, self.w3.csm.module.events.NodeOperatorAdded),
                l_block_number,
                r_block_number,
            ),
            key=by_no_id,
        )

        for e in node_operator_added_events:
            no_id = str(e["args"]["nodeOperatorId"])
            for operators in [good_performers, bad_performers, not_enough_participation]:
                if no_id in operators:
                    operators[no_id]["manager_address"] = e["args"]["managerAddress"]
                    operators[no_id]["used_addresses"] = list({e["args"]["managerAddress"], e["args"]["rewardAddress"]})

        bond_curve_events = sorted(
            get_events_in_range(
                cast(ContractEvent, self.w3.csm.accounting.events.BondCurveSet),
                l_block_number,
                r_block_number,
            ),
            key=by_no_id,
        )

        for e in bond_curve_events:
            no_id = str(e["args"]["nodeOperatorId"])
            for operators in [good_performers, bad_performers, not_enough_participation]:
                if no_id in operators:
                    operators[no_id]["testnet_ea_member"] = True

        settled_events = sorted(
            get_events_in_range(
                cast(ContractEvent, self.w3.csm.module.events.ELRewardsStealingPenaltySettled),
                l_block_number,
                r_block_number,
            ),
            key=by_no_id,
        )

        for e in settled_events:
            no_id = str(e["args"]["nodeOperatorId"])
            for operators in [good_performers, bad_performers, not_enough_participation]:
                if no_id in operators:
                    operators[no_id]["el_rewards_stealer"] = True

        manager_changed_events = sorted(
            get_events_in_range(
                cast(ContractEvent, self.w3.csm.module.events.NodeOperatorManagerAddressChanged),
                l_block_number,
                r_block_number,
            ),
            key=by_no_id,
        )

        for e in manager_changed_events:
            no_id = str(e["args"]["nodeOperatorId"])
            addr = e["args"]["newAddress"]
            for operators in [good_performers, bad_performers, not_enough_participation]:
                if no_id in operators:
                    operators[no_id]["used_addresses"] = list(set(operators[no_id]["used_addresses"]).union([addr]))
                    if not operators[no_id].get("testnet_ea_member", False):
                        operators[no_id]["manager_address"] = addr

        reward_changed_events = sorted(
            get_events_in_range(
                cast(ContractEvent, self.w3.csm.module.events.NodeOperatorRewardAddressChanged),
                l_block_number,
                r_block_number,
            ),
            key=by_no_id,
        )

        for e in reward_changed_events:
            no_id = str(e["args"]["nodeOperatorId"])
            addr = e["args"]["newAddress"]
            for operators in [good_performers, bad_performers, not_enough_participation]:
                if no_id in operators:
                    operators[no_id]["used_addresses"] = list(set(operators[no_id]["used_addresses"]).union([addr]))

        with open('out/good_performers.json', 'w') as f:
            json.dump(good_performers, f, indent=2)

        with open('out/bad_performers.json', 'w') as f:
            json.dump(bad_performers, f, indent=2)

        with open(f'out/less_than_{MIN_ACTIVE_EPOCHS}_assigned.json', 'w') as f:
            json.dump(not_enough_participation, f, indent=2)

        logger.info({"msg": "Addresses fetched"})
