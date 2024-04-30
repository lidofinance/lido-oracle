import logging
import time
from threading import Thread, Lock
from typing import Any, Iterable, cast

from src.modules.csm.typings import FramePerformance
from src.providers.consensus.client import ConsensusClient
from src.typings import EpochNumber, BlockRoot, SlotNumber, BlockStamp
from src.utils.web3converter import Web3Converter

logger = logging.getLogger(__name__)
lock = Lock()


class CheckpointsFactory:
    cc: ConsensusClient
    converter: Web3Converter
    frame_performance: FramePerformance

    # min checkpoint step is 10 because it's a reasonable number of epochs to process at once (~1 hour)
    MIN_CHECKPOINT_STEP = 10
    # max checkpoint step is 255 epochs because block_roots size from state is 8192 slots (256 epochs)
    # to check duty of every epoch, we need to check 64 slots (32 slots of duty epoch + 32 slots of next epoch)
    # in the end we got 255 committees and 8192 block_roots to check them for every checkpoint
    MAX_CHECKPOINT_STEP = 255

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

        def _max_in_seq(items: Iterable[Any]) -> Any:
            sorted_ = sorted(items)
            assert sorted_
            item = sorted_[0]
            for curr in sorted_:
                if curr - item > 1:
                    break
                item = curr
            return item

        l_epoch = _max_in_seq((l_epoch, *self.frame_performance.processed_epochs))
        processing_delay = finalized_epoch - l_epoch

        if l_epoch == r_epoch:
            logger.info({"msg": "All epochs processed, no checkpoints required"})
            return []

        if processing_delay < self.MIN_CHECKPOINT_STEP and finalized_epoch < r_epoch:
            logger.info({"msg": f"Minimum checkpoint step is not reached, current delay is {processing_delay}"})
            return []

        duty_epochs = cast(list[EpochNumber], list(range(l_epoch, r_epoch + 1)))
        checkpoints: list[Checkpoint] = []
        checkpoint_epochs = []
        for index, epoch in enumerate(duty_epochs, 1):
            checkpoint_epochs.append(epoch)
            if index % self.MAX_CHECKPOINT_STEP == 0 or epoch == r_epoch:
                checkpoint_slot = self.converter.get_epoch_last_slot(EpochNumber(epoch + 1))
                checkpoints.append(_prepare_checkpoint(checkpoint_slot, checkpoint_epochs))
                logger.info(
                    {"msg": f"Checkpoint slot {checkpoint_slot} with {len(checkpoint_epochs)} duty epochs is prepared"}
                )
                checkpoint_epochs = []
        logger.info({"msg": f"Checkpoints to process: {len(checkpoints)}"})
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
    block_roots: list[BlockRoot | None]  # max 8192 elements

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
            if duty_epoch in self.frame_performance.processed_epochs:
                continue
            if not self.block_roots:
                self._get_block_roots()
            roots_to_check = self._select_roots_to_check(duty_epoch)
            if not self.free_threads:
                self._await_oldest_thread()
            # TODO: handle error in the thread. wait all, then raise
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
    ) -> list[BlockRoot | None]:
        # inspired by the spec
        # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_block_root_at_slot
        roots_to_check = []
        slots = range(
            self.converter.get_epoch_first_slot(duty_epoch),
            self.converter.get_epoch_last_slot(EpochNumber(duty_epoch + 1)) + 1
        )
        for slot_to_check in slots:
            # TODO: get the magic number from the CL spec
            if self.slot - 8192 < slot_to_check <= self.slot:
                roots_to_check.append(self.block_roots[slot_to_check % 8192])
                continue
            raise ValueError("Slot is out of the state block roots range")
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
        checked_roots = set()
        committees = self._prepare_committees(last_finalized_blockstamp, EpochNumber(duty_epoch))
        for root in roots_to_check:
            if root is None:
                continue
            slot_data = self.cc.get_block_details_raw(BlockRoot(root))
            self._process_attestations(slot_data, committees)
            checked_roots.add(root)
        with lock:
            self.frame_performance.dump(duty_epoch, committees, checked_roots)
        logger.info({"msg": f"Epoch {duty_epoch} processed in {time.time() - start:.2f} seconds"})

    def _prepare_committees(self, last_finalized_blockstamp: BlockStamp, epoch: int) -> dict:
        start = time.time()
        committees = {}
        for committee in self.cc.get_attestation_committees(last_finalized_blockstamp, EpochNumber(epoch)):
            validators = []
            # Order of insertion is used to track the positions in the committees.
            for validator in committee.validators:
                data = {"index": validator, "included": False}
                validators.append(data)
            committees[f"{committee.slot}{committee.index}"] = validators
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
            for index_in_committee, validator in enumerate(committee):
                if validator['included']:
                    # validator has already fulfilled its duties
                    continue
                attested = att_bits[index_in_committee]
                if attested:
                    validator['included'] = True
                    committees[committee_id][index_in_committee] = validator
