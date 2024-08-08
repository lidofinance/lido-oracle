import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import batched
from threading import Lock
from typing import Iterable, Sequence

from src import variables
from src.constants import SLOTS_PER_HISTORICAL_ROOT
from src.metrics.prometheus.csm import CSM_UNPROCESSED_EPOCHS_COUNT, CSM_MIN_UNPROCESSED_EPOCH
from src.modules.csm.state import State
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BlockAttestation
from src.types import BlockRoot, BlockStamp, EpochNumber, SlotNumber, ValidatorIndex
from src.utils.range import sequence
from src.utils.timeit import timeit
from src.utils.web3converter import Web3Converter

logger = logging.getLogger(__name__)
lock = Lock()


class MinStepIsNotReached(Exception):
    ...


@dataclass
class Checkpoint:
    slot: SlotNumber  # last slot of the epoch
    duty_epochs: Sequence[EpochNumber]  # max 255 elements


@dataclass
class ValidatorDuty:
    index: ValidatorIndex
    included: bool


class CheckpointsIterator:
    converter: Web3Converter

    l_epoch: EpochNumber
    r_epoch: EpochNumber

    # Max available epoch to process according to the finalized epoch
    max_available_epoch_to_check: EpochNumber

    # Min checkpoint step is 10 because it's a reasonable number of epochs to process at once (~1 hour)
    MIN_CHECKPOINT_STEP = 10
    # Max checkpoint step is 255 epochs because block_roots size from state is 8192 slots (256 epochs)
    # to check duty of every epoch, we need to check 64 slots (32 slots of duty epoch + 32 slots of next epoch).
    # In the end we got 255 committees and 8192 block_roots to check them for every checkpoint.
    MAX_CHECKPOINT_STEP = 255
    # Delay from last duty epoch to get checkpoint slot
    CHECKPOINT_SLOT_DELAY_EPOCHS = 2

    def __init__(
        self, converter: Web3Converter, l_epoch: EpochNumber, r_epoch: EpochNumber, finalized_epoch: EpochNumber
    ):
        if l_epoch > r_epoch:
            raise ValueError("Left border epoch should be less or equal right border epoch")
        self.converter = converter
        self.l_epoch = l_epoch
        self.r_epoch = r_epoch

        self.max_available_epoch_to_check = min(
            self.r_epoch, EpochNumber(finalized_epoch - self.CHECKPOINT_SLOT_DELAY_EPOCHS)
        )

        if self.r_epoch > self.max_available_epoch_to_check and not self._is_min_step_reached():
            raise MinStepIsNotReached()

    def __iter__(self):
        for checkpoint_epochs in batched(
            sequence(self.l_epoch, self.max_available_epoch_to_check),
            self.MAX_CHECKPOINT_STEP,
        ):
            checkpoint_slot = self.converter.get_epoch_first_slot(
                EpochNumber(max(checkpoint_epochs) + self.CHECKPOINT_SLOT_DELAY_EPOCHS)
            )
            logger.info(
                {"msg": f"Checkpoint slot {checkpoint_slot} with {len(checkpoint_epochs)} duty epochs is prepared"}
            )
            yield Checkpoint(checkpoint_slot, checkpoint_epochs)

    def _is_min_step_reached(self):
        # NOTE: processing delay can be negative
        # if the finalized epoch is less than next epoch to check (l_epoch)
        processing_delay = self.max_available_epoch_to_check - self.l_epoch
        if processing_delay >= self.MIN_CHECKPOINT_STEP:
            return True
        logger.info(
            {
                "msg": f"Minimum checkpoint step is not reached, current delay is {processing_delay} epochs",
                "max_available_epoch_to_check": self.max_available_epoch_to_check,
                "l_epoch": self.l_epoch,
                "r_epoch": self.r_epoch,
            }
        )
        return False


type Committees = dict[tuple[str, str], list[ValidatorDuty]]


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
        # Checkpoint for us like a time point, that's why we use slot, not root.
        # `s % 8192 = i` is the index where slot `s` will be located.
        # If `s` is `checkpoint_slot -> state.slot`, then it cannot yet be in `block_roots`.
        # So it is the index that will be overwritten in the next slot, i.e. the index of the oldest root.
        pivot_index = checkpoint_slot % SLOTS_PER_HISTORICAL_ROOT
        br = self.cc.get_state_block_roots(checkpoint_slot)
        # Replace duplicated roots to None to mark missed slots
        return [br[i] if i == pivot_index or br[i] != br[i - 1] else None for i in range(len(br))]

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
            if not slot_to_check < checkpoint_slot <= slot_to_check + SLOTS_PER_HISTORICAL_ROOT:
                raise ValueError("Slot is out of the state block roots range")
            if br := block_roots[slot_to_check % SLOTS_PER_HISTORICAL_ROOT]:
                roots_to_check.append(br)

        return roots_to_check

    def _process(self, unprocessed_epochs: list[EpochNumber], duty_epochs_roots: dict[EpochNumber, list[BlockRoot]]):
        executor = ThreadPoolExecutor(max_workers=variables.CSM_ORACLE_MAX_CONCURRENCY)
        try:
            futures = {
                executor.submit(self._check_duty, duty_epoch, duty_epochs_roots[duty_epoch])
                for duty_epoch in unprocessed_epochs
            }
            for future in as_completed(futures):
                future.result()
        except Exception as e:
            logger.error({"msg": "Error processing epochs in threads", "error": repr(e)})
            raise SystemExit(1) from e
        finally:
            logger.info({"msg": "Shutting down the executor"})
            executor.shutdown(wait=True, cancel_futures=True)
            logger.info({"msg": "The executor was shut down"})

    @timeit(lambda args, duration: logger.info({"msg": f"Epoch {args.duty_epoch} processed in {duration:.2f} seconds"}))
    def _check_duty(
        self,
        duty_epoch: EpochNumber,
        block_roots: list[BlockRoot],
    ):
        logger.info({"msg": f"Processing epoch {duty_epoch}"})
        committees = self._prepare_committees(EpochNumber(duty_epoch))
        for root in block_roots:
            attestations = self.cc.get_block_attestations(BlockRoot(root))
            process_attestations(attestations, committees)

        with lock:
            for committee in committees.values():
                for validator_duty in committee:
                    self.state.inc(
                        validator_duty.index,
                        included=validator_duty.included,
                    )
            if duty_epoch not in self.state.unprocessed_epochs:
                raise ValueError(f"Epoch {duty_epoch} is not in epochs that should be processed")
            self.state.add_processed_epoch(duty_epoch)
            self.state.commit()
            self.state.status()
            unprocessed_epochs = self.state.unprocessed_epochs
            CSM_UNPROCESSED_EPOCHS_COUNT.set(len(unprocessed_epochs))
            CSM_MIN_UNPROCESSED_EPOCH.set(min(unprocessed_epochs or {0}))

    @timeit(
        lambda args, duration: logger.info(
            {"msg": f"Committees for epoch {args.epoch} processed in {duration:.2f} seconds"}
        )
    )
    def _prepare_committees(self, epoch: EpochNumber) -> Committees:
        committees = {}
        for committee in self.cc.get_attestation_committees(self.finalized_blockstamp, EpochNumber(epoch)):
            validators = []
            # Order of insertion is used to track the positions in the committees.
            for validator in committee.validators:
                validators.append(ValidatorDuty(index=ValidatorIndex(int(validator)), included=False))
            committees[(committee.slot, committee.index)] = validators
        return committees


def process_attestations(attestations: Iterable[BlockAttestation], committees: Committees) -> None:
    for attestation in attestations:
        committee_id = (attestation.data.slot, attestation.data.index)
        committee = committees.get(committee_id, [])
        att_bits = _to_bits(attestation.aggregation_bits)
        for index_in_committee, validator_duty in enumerate(committee):
            validator_duty.included = validator_duty.included or _is_attested(att_bits, index_in_committee)


def _is_attested(bits: Sequence[bool], index: int) -> bool:
    return bits[index]


def _to_bits(aggregation_bits: str) -> Sequence[bool]:
    # copied from https://github.com/ethereum/py-ssz/blob/main/ssz/sedes/bitvector.py#L66
    att_bytes = bytes.fromhex(aggregation_bits[2:])
    return [bool((att_bytes[bit_index // 8] >> bit_index % 8) % 2) for bit_index in range(len(att_bytes) * 8)]
