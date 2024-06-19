import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from typing import Iterable, cast

from timeout_decorator import TimeoutError as DecoratorTimeoutError

from src import variables
from src.constants import SLOTS_PER_HISTORICAL_ROOT
from src.modules.csm.state import State
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BlockAttestation
from src.types import BlockRoot, BlockStamp, EpochNumber, SlotNumber, ValidatorIndex
from src.utils.range import sequence
from src.utils.web3converter import Web3Converter

logger = logging.getLogger(__name__)
lock = Lock()


class MinStepIsNotReached(Exception):
    ...


@dataclass
class Checkpoint:
    slot: SlotNumber  # last slot of the epoch
    duty_epochs: list[EpochNumber]  # max 255 elements


class CheckpointsIterator:
    converter: Web3Converter

    l_epoch: EpochNumber
    r_epoch: EpochNumber

    # Min checkpoint step is 10 because it's a reasonable number of epochs to process at once (~1 hour)
    MIN_CHECKPOINT_STEP = 10
    # Max checkpoint step is 255 epochs because block_roots size from state is 8192 slots (256 epochs)
    # to check duty of every epoch, we need to check 64 slots (32 slots of duty epoch + 32 slots of next epoch).
    # In the end we got 255 committees and 8192 block_roots to check them for every checkpoint.
    MAX_CHECKPOINT_STEP = 255

    def __init__(
        self, converter: Web3Converter, l_epoch: EpochNumber, r_epoch: EpochNumber, finalized_epoch: EpochNumber
    ):
        if l_epoch > r_epoch:
            raise ValueError("Left border epoch should be less or equal right border epoch")
        self.converter = converter
        self.l_epoch = l_epoch
        self.r_epoch = self._get_adjusted_r_epoch(r_epoch, finalized_epoch)

    def __iter__(self):

        duty_epochs = cast(list[EpochNumber], list(sequence(self.l_epoch, self.r_epoch)))

        checkpoint_epochs = []
        for index, epoch in enumerate(duty_epochs, 1):
            checkpoint_epochs.append(epoch)
            if index % self.MAX_CHECKPOINT_STEP == 0 or epoch == self.r_epoch:
                # We need to get the first slot of the next of next epoch to get fit to
                # 8192 roots in `checkpoint_slot` state block_roots to check duties in every epoch in checkpoint.
                # To check duties in the current epoch you need to
                # get 32 slots of the current epoch and 32 slots of the next epoch.
                checkpoint_slot = SlotNumber(self.converter.get_epoch_last_slot(EpochNumber(epoch + 1)) + 1)
                logger.info(
                    {"msg": f"Checkpoint slot {checkpoint_slot} with {len(checkpoint_epochs)} duty epochs is prepared"}
                )
                yield Checkpoint(checkpoint_slot, checkpoint_epochs)
                checkpoint_epochs = []

    def _get_adjusted_r_epoch(self, r_epoch: EpochNumber, finalized_epoch: EpochNumber):
        processing_delay = finalized_epoch - self.l_epoch
        if processing_delay < self.MIN_CHECKPOINT_STEP and finalized_epoch <= r_epoch:
            logger.info(
                {
                    "msg": f"Minimum checkpoint step is not reached, current delay is {processing_delay} epochs",
                    "finalized_epoch": finalized_epoch,
                    "l_epoch": self.l_epoch,
                    "r_epoch": r_epoch,
                }
            )
            raise MinStepIsNotReached()
        adjusted_r_epoch = min(r_epoch, EpochNumber(finalized_epoch - 1))
        if r_epoch != adjusted_r_epoch:
            logger.info(
                {
                    "msg": f"Right border epoch of checkpoints iterator is recalculated according to the finalized epoch. "
                    f"Before: {r_epoch} After: {adjusted_r_epoch}"
                }
            )
        return adjusted_r_epoch


class CheckpointProcessor:
    cc: ConsensusClient
    converter: Web3Converter

    state: State
    finalized_blockstamp: BlockStamp

    def __init__(self, cc: ConsensusClient, state: State, converter: Web3Converter, finalized_blockstamp: BlockStamp):
        self.cc = cc
        self.converter = converter
        self.state = state
        self.finalized_blockstamp = finalized_blockstamp

    def exec(self, checkpoint: Checkpoint) -> int:
        logger.info(
            {"msg": f"Processing checkpoint for slot {checkpoint.slot} with {len(checkpoint.duty_epochs)} epochs"}
        )
        unprocessed_epochs = [e for e in checkpoint.duty_epochs if e in self.state.unprocessed_epochs]
        if not unprocessed_epochs:
            logger.info({"msg": "Nothing to process in the checkpoint"})
            return 0
        block_roots = self._get_block_roots(checkpoint.slot)
        duty_epochs_roots = {
            duty_epoch: self._select_block_roots(duty_epoch, block_roots, checkpoint.slot)
            for duty_epoch in unprocessed_epochs
        }
        self._process(unprocessed_epochs, duty_epochs_roots)
        return len(unprocessed_epochs)

    def _get_block_roots(self, checkpoint_slot: SlotNumber):
        logger.info({"msg": f"Get block roots for slot {checkpoint_slot}"})
        # checkpoint for us like a time point, that's why we use slot, not root
        br = self.cc.get_state_block_roots(checkpoint_slot)
        # replace duplicated roots to None to mark missed slots
        # the first root always exists
        return [br[0], *[None if br[i] == br[i - 1] else br[i] for i in range(1, len(br))]]

    def _select_block_roots(
        self, duty_epoch: EpochNumber, block_roots: list[BlockRoot | None], checkpoint_slot: SlotNumber
    ) -> list[BlockRoot]:
        roots_to_check = []
        # To check duties in the current epoch you need to
        # have 32 slots of the current epoch and 32 slots of the next epoch
        slots = sequence(
            self.converter.get_epoch_first_slot(duty_epoch),
            self.converter.get_epoch_last_slot(EpochNumber(duty_epoch + 1)),
        )
        for slot_to_check in slots:
            # From spec
            # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_block_root_at_slot
            if checkpoint_slot - SLOTS_PER_HISTORICAL_ROOT < slot_to_check <= checkpoint_slot:
                if br := block_roots[slot_to_check % SLOTS_PER_HISTORICAL_ROOT]:
                    roots_to_check.append(br)
                continue
            raise ValueError("Slot is out of the state block roots range")
        return roots_to_check

    def _process(self, unprocessed_epochs: list[EpochNumber], duty_epochs_roots: dict[EpochNumber, list[BlockRoot]]):
        with ThreadPoolExecutor(max_workers=variables.CSM_ORACLE_MAX_CONCURRENCY) as ext:
            try:
                futures = {
                    ext.submit(self._check_duty, duty_epoch, duty_epochs_roots[duty_epoch])
                    for duty_epoch in unprocessed_epochs
                }
                for future in as_completed(futures):
                    future.result()
            except DecoratorTimeoutError as e:
                logger.error({"msg": "Timeout processing epochs in threads", "error": str(e)})
                # Don't wait the current running tasks to finish, cancel the rest and shutdown the executor
                # To interrupt the current running tasks, we need to raise a special exception
                ext.shutdown(wait=False, cancel_futures=True)
                raise SystemExit(1) from e
            except Exception as e:
                logger.error({"msg": "Error processing epochs in threads, wait the current threads", "error": str(e)})
                # Wait only for the current running threads to prevent
                # a lot of similar error-possible requests to the consensus node.
                # Raise the error after a batch of running threads is finished
                ext.shutdown(wait=True, cancel_futures=True)
                raise ValueError(e) from e

    def _check_duty(
        self,
        duty_epoch: EpochNumber,
        block_roots: list[BlockRoot],
    ):
        logger.info({"msg": f"Process epoch {duty_epoch}"})
        start = time.time()
        committees = self._prepare_committees(EpochNumber(duty_epoch))
        for root in block_roots:
            attestations = self.cc.get_block_attestations(BlockRoot(root))
            process_attestations(attestations, committees)

        with lock:
            for committee in committees.values():
                for validator in committee:
                    self.state.inc(
                        ValidatorIndex(int(validator['index'])),
                        included=validator['included'],
                    )
            if duty_epoch not in self.state.unprocessed_epochs:
                raise ValueError(f"Epoch {duty_epoch} is not in epochs that should be processed")
            self.state.add_processed_epoch(duty_epoch)
            self.state.commit()
            self.state.status()

        logger.info({"msg": f"Epoch {duty_epoch} processed in {time.time() - start:.2f} seconds"})

    def _prepare_committees(self, epoch: int) -> dict:
        start = time.time()
        committees = {}
        for committee in self.cc.get_attestation_committees(self.finalized_blockstamp, EpochNumber(epoch)):
            validators = []
            # Order of insertion is used to track the positions in the committees.
            for validator in committee.validators:
                data = {"index": validator, "included": False}
                validators.append(data)
            committees[f"{committee.slot}_{committee.index}"] = validators
        logger.info({"msg": f"Committees for epoch {epoch} processed in {time.time() - start:.2f} seconds"})
        return committees


def process_attestations(attestations: Iterable[BlockAttestation], committees: dict) -> None:
    for attestation in attestations:
        committee_id = f"{attestation.data.slot}_{attestation.data.index}"
        committee = committees.get(committee_id)
        att_bits = _to_bits(attestation.aggregation_bits)
        if not committee:
            continue
        for index_in_committee, validator in enumerate(committee):
            if validator['included']:
                # validator has already fulfilled its duties
                continue
            if _is_attested(att_bits, index_in_committee):
                validator['included'] = True
                committees[committee_id][index_in_committee] = validator


def _is_attested(bits: list[bool], index: int) -> bool:
    return bits[index]


def _to_bits(aggregation_bits: str):
    # copied from https://github.com/ethereum/py-ssz/blob/main/ssz/sedes/bitvector.py#L66
    att_bytes = bytes.fromhex(aggregation_bits[2:])
    return [bool((att_bytes[bit_index // 8] >> bit_index % 8) % 2) for bit_index in range(len(att_bytes) * 8)]
