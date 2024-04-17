import logging
import time
from threading import Thread
from typing import cast

from src.modules.csm.typings import FramePerformance, AttestationsAggregate
from src.providers.consensus.client import ConsensusClient
from src.typings import EpochNumber, BlockRoot, SlotNumber, BlockStamp, ValidatorIndex
from src.utils.web3converter import Web3Converter

logger = logging.getLogger(__name__)


class CheckpointsFactory:
    cc: ConsensusClient
    converter: Web3Converter
    frame_performance: FramePerformance

    def __init__(self, cc: ConsensusClient, converter: Web3Converter, frame_performance: FramePerformance):
        self.cc = cc
        self.converter = converter
        self.frame_performance = frame_performance

    def prepare_checkpoints(
        self,
        l_epoch: EpochNumber,
        r_epoch: EpochNumber,
        finalized_epoch: EpochNumber
    ):
        def _prepare_checkpoint(_slot: SlotNumber, _duty_epochs: list[EpochNumber]):
            return Checkpoint(self.cc, self.converter, self.frame_performance, _slot, _duty_epochs)

        processing_delay = finalized_epoch - (max(self.frame_performance.processed, default=0) or l_epoch)
        # - max checkpoint step is 255 because it should be less than
        #   the state block roots size (8192 blocks = 256 epochs) to check 64 roots per committee from one state
        # - min checkpoint step is 10 because it's a reasonable number of epochs to process at once (~1 hour)
        checkpoint_step = min(255, max(processing_delay, 10))
        duty_epochs = cast(list[EpochNumber], list(range(l_epoch, r_epoch + 1)))

        checkpoints: list[Checkpoint] = []
        for index, epoch in enumerate(duty_epochs, 1):
            if index % checkpoint_step != 0 and epoch != r_epoch:
                continue
            slot = self.converter.get_epoch_last_slot(EpochNumber(epoch + 1))
            if epoch == r_epoch:
                checkpoints.append(_prepare_checkpoint(slot, duty_epochs[index - index % checkpoint_step: index]))
            else:
                checkpoints.append(_prepare_checkpoint(slot, duty_epochs[index - checkpoint_step: index]))
        return checkpoints


class Checkpoint:
    # TODO: should be configurable or calculated based on the system resources
    MAX_THREADS: int = 4

    cc: ConsensusClient
    converter: Web3Converter

    threads: list[Thread]
    frame_performance: FramePerformance

    slot: SlotNumber  # last slot of the epoch
    duty_epochs: list[EpochNumber]  # max 255 elements
    block_roots: list[BlockRoot]  # max 8192 elements

    def __init__(
        self,
        cc: ConsensusClient,
        converter: Web3Converter,
        frame_performance: FramePerformance,
        slot: SlotNumber,
        duty_epochs: list[EpochNumber]
    ):
        self.cc = cc
        self.converter = converter
        self.slot = slot
        self.duty_epochs = duty_epochs
        self.block_roots = []
        self.threads = []
        self.frame_performance = frame_performance

    @property
    def free_threads(self):
        return self.MAX_THREADS - len(self.threads)

    def process(self, last_finalized_blockstamp: BlockStamp):
        for duty_epoch in self.duty_epochs:
            if duty_epoch in self.frame_performance.processed:
                continue
            if not self.block_roots:
                self._get_block_roots()
            roots_to_check = self._select_roots_to_check(duty_epoch)
            if not self.free_threads:
                self._await_oldest_thread()
            thread = Thread(
                target=self._process_epoch, args=(last_finalized_blockstamp, duty_epoch, roots_to_check)
            )
            thread.start()
            self.threads.append(thread)
        self._await_all_threads()

    def _await_oldest_thread(self):
        old = self.threads.pop(0)
        old.join()

    def _await_all_threads(self):
        for thread in self.threads:
            thread.join()

    def _select_roots_to_check(
        self, duty_epoch: EpochNumber
    ) -> list[BlockRoot]:
        # copy of
        # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_block_root_at_slot
        roots_to_check = []
        slots = range(
            self.converter.get_epoch_first_slot(duty_epoch),
            self.converter.get_epoch_last_slot(EpochNumber(duty_epoch + 1))
        )
        for slot in slots:
            # TODO: get the magic number from the CL spec
            if slot + 8192 < self.slot < slot:
                raise ValueError("Slot is out of the state block roots range")
            roots_to_check.append(self.block_roots[slot % 8192])
        return roots_to_check

    def _get_block_roots(self):
        logger.info({"msg": f"Get block roots for slot {self.slot}"})
        # checkpoint for us like a time point, that's why we use slot, not root
        br = self.cc.get_state_block_roots(self.slot)
        # replace duplicated roots to None to mark missed slots
        self.block_roots = [None if br[i] == br[i - 1] else br[i] for i in range(len(br))]

    def _process_epoch(
        self,
        last_finalized_blockstamp: BlockStamp,
        duty_epoch: EpochNumber,
        roots_to_check: list[BlockRoot]
    ):
        logger.info({"msg": f"Process epoch {duty_epoch}"})
        start = time.time()
        committees = self._prepare_committees(last_finalized_blockstamp, EpochNumber(duty_epoch))
        for root in roots_to_check:
            if root is None:
                continue
            slot_data = self.cc.get_block_details_raw(BlockRoot(root))
            self._process_attestations(slot_data, committees)

        self.frame_performance.processed.add(EpochNumber(duty_epoch))
        self.frame_performance.dump()
        logger.info({"msg": f"Epoch {duty_epoch} processed in {time.time() - start:.2f} seconds"})

    def _prepare_committees(self, last_finalized_blockstamp: BlockStamp, epoch: int) -> dict:
        start = time.time()
        committees = {}
        for committee in self.cc.get_attestation_committees(last_finalized_blockstamp, EpochNumber(epoch)):
            committees[f"{committee.slot}{committee.index}"] = committee.validators
            for validator in committee.validators:
                val = self.frame_performance.aggr_per_val.get(
                    ValidatorIndex(int(validator)), AttestationsAggregate(0, 0)
                )
                val.assigned += 1
                self.frame_performance.aggr_per_val[ValidatorIndex(int(validator))] = val
        logger.info({"msg": f"Committees for epoch {epoch} processed in {time.time() - start:.2f} seconds"})
        return committees

    def _process_attestations(self, slot_data: dict, committees: dict) -> None:
        def to_bits(aggregation_bits: str):
            # copied from https://github.com/ethereum/py-ssz/blob/main/ssz/sedes/bitvector.py#L66
            att_bytes = bytes.fromhex(aggregation_bits[2:])
            return [
                bool((att_bytes[bit_index // 8] >> bit_index % 8) % 2) for bit_index in range(len(att_bytes) * 8)
            ]

        for attestation in slot_data['message']['body']['attestations']:
            committee_id = f"{attestation['data']['slot']}{attestation['data']['index']}"
            committee = committees.get(committee_id)
            att_bits = to_bits(attestation['aggregation_bits'])
            if not committee:
                continue
            for index, validator in enumerate(committee):
                if validator is None:
                    # validator has already fulfilled its duties
                    continue
                attested = att_bits[index]
                if attested:
                    self.frame_performance.aggr_per_val[ValidatorIndex(int(validator))].included += 1
                    # duty is fulfilled, so we can remove validator from the committee
                    committees[committee_id][index] = None
