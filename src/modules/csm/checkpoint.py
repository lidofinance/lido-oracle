import logging
from collections import UserDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import batched
from threading import Lock
from typing import Iterable, Sequence

from hexbytes import HexBytes

from src import variables
from src.constants import SLOTS_PER_HISTORICAL_ROOT, EPOCHS_PER_SYNC_COMMITTEE_PERIOD
from src.metrics.prometheus.csm import CSM_UNPROCESSED_EPOCHS_COUNT, CSM_MIN_UNPROCESSED_EPOCH
from src.modules.csm.state import State
from src.modules.submodules.types import ZERO_HASH
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import SyncCommittee, SyncAggregate
from src.utils.blockstamp import build_blockstamp
from src.providers.consensus.types import BlockAttestation
from src.types import BlockRoot, BlockStamp, CommitteeIndex, EpochNumber, SlotNumber, ValidatorIndex
from src.utils.range import sequence
from src.utils.slot import get_prev_non_missed_slot
from src.utils.timeit import timeit
from src.utils.types import hex_str_to_bytes
from src.utils.web3converter import Web3Converter

ZERO_BLOCK_ROOT = HexBytes(ZERO_HASH).to_0x_hex()

logger = logging.getLogger(__name__)
lock = Lock()


class MinStepIsNotReached(Exception): ...
class SlotOutOfRootsRange(Exception): ...


@dataclass
class FrameCheckpoint:
    slot: SlotNumber  # Slot for the state to get the trusted block roots from.
    duty_epochs: Sequence[EpochNumber]  # NOTE: max 255 elements.


@dataclass
class ValidatorDuty:
    validator_index: ValidatorIndex
    included: bool


class FrameCheckpointsIterator:
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
    # Delay from last duty epoch to get checkpoint slot.
    # Regard to EIP-7045 if we want to process epoch N, we need to get attestation data from epoch N and N + 1.
    # To get attestation data block roots for epoch N and N + 1 we need to
    # get roots from state checkpoint slot for epoch N + 2. That's why we need the delay from epoch N.
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
            yield FrameCheckpoint(checkpoint_slot, checkpoint_epochs)

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


type SlotBlockRoot = tuple[SlotNumber, BlockRoot | None]
type SyncCommittees = dict[SlotNumber, list[ValidatorDuty]]
type AttestationCommittees = dict[tuple[SlotNumber, CommitteeIndex], list[ValidatorDuty]]


class SyncCommitteesCache(UserDict):

    max_size = max(2, variables.CSM_ORACLE_MAX_CONCURRENCY)

    def __setitem__(self, sync_committee_period: int, value: SyncCommittee):
        if len(self) >= self.max_size:
            self.pop(min(self))
        super().__setitem__(sync_committee_period, value)


SYNC_COMMITTEES_CACHE = SyncCommitteesCache()


class FrameCheckpointProcessor:
    cc: ConsensusClient
    converter: Web3Converter

    state: State
    finalized_blockstamp: BlockStamp

    def __init__(
        self,
        cc: ConsensusClient,
        state: State,
        converter: Web3Converter,
        finalized_blockstamp: BlockStamp,
    ):
        self.cc = cc
        self.converter = converter
        self.state = state
        self.finalized_blockstamp = finalized_blockstamp

    def exec(self, checkpoint: FrameCheckpoint) -> int:
        logger.info(
            {"msg": f"Processing checkpoint for slot {checkpoint.slot} with {len(checkpoint.duty_epochs)} epochs"}
        )
        unprocessed_epochs = [e for e in checkpoint.duty_epochs if e in self.state.unprocessed_epochs]
        if not unprocessed_epochs:
            logger.info({"msg": "Nothing to process in the checkpoint"})
            return 0
        block_roots = self._get_block_roots(checkpoint.slot)
        duty_epochs_roots = {
            duty_epoch: self._select_block_roots(block_roots, duty_epoch, checkpoint.slot)
            for duty_epoch in unprocessed_epochs
        }
        self._process(block_roots, checkpoint.slot, unprocessed_epochs, duty_epochs_roots)
        self.state.commit()
        return len(unprocessed_epochs)

    def _get_block_roots(self, checkpoint_slot: SlotNumber):
        logger.info({"msg": f"Get block roots for slot {checkpoint_slot}"})
        # Checkpoint for us like a time point, that's why we use slot, not root.
        br = self.cc.get_state_block_roots(checkpoint_slot)
        # `s % 8192 = i` is the index where slot `s` will be located.
        # If `s` is `checkpoint_slot -> state.slot`, then it cannot yet be in `block_roots`.
        # So it is the index that will be overwritten in the next slot, i.e. the index of the oldest root.
        pivot_index = checkpoint_slot % SLOTS_PER_HISTORICAL_ROOT
        # The oldest root can be missing, so we need to check it and mark it as well as other missing slots
        pivot_block_root = br[pivot_index]
        slot_by_pivot_block_root = self.cc.get_block_header(pivot_block_root).data.header.message.slot
        calculated_pivot_slot = max(checkpoint_slot - SLOTS_PER_HISTORICAL_ROOT, 0)
        is_pivot_missing = slot_by_pivot_block_root != calculated_pivot_slot

        # Replace duplicated roots with `None` to mark missing slots
        br = [
            br[i] if br[i] != ZERO_BLOCK_ROOT and (i == pivot_index or br[i] != br[i - 1])
            else None
            for i in range(len(br))
        ]
        if is_pivot_missing:
            br[pivot_index] = None

        return br

    def _select_block_roots(
        self, block_roots: list[BlockRoot | None], duty_epoch: EpochNumber, checkpoint_slot: SlotNumber
    ) -> tuple[list[SlotBlockRoot], list[SlotBlockRoot]]:
        roots_to_check = []
        # To check duties in the current epoch you need to
        # have 32 slots of the current epoch and 32 slots of the next epoch
        slots = sequence(
            self.converter.get_epoch_first_slot(duty_epoch),
            self.converter.get_epoch_last_slot(EpochNumber(duty_epoch + 1)),
        )
        for slot_to_check in slots:
            block_root = self._select_block_root_by_slot(block_roots, checkpoint_slot, slot_to_check)
            roots_to_check.append((slot_to_check, block_root))

        slots_per_epoch = self.converter.chain_config.slots_per_epoch
        duty_epoch_roots, next_epoch_roots = roots_to_check[:slots_per_epoch], roots_to_check[slots_per_epoch:]

        return duty_epoch_roots, next_epoch_roots

    @staticmethod
    def _select_block_root_by_slot(block_roots: list[BlockRoot | None], checkpoint_slot: SlotNumber, root_slot: SlotNumber) -> BlockRoot | None:
        # From spec
        # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_block_root_at_slot
        if not root_slot < checkpoint_slot <= root_slot + SLOTS_PER_HISTORICAL_ROOT:
            raise SlotOutOfRootsRange("Slot is out of the state block roots range")
        return block_roots[root_slot % SLOTS_PER_HISTORICAL_ROOT]

    def _process(
        self,
        checkpoint_block_roots: list[BlockRoot | None],
        checkpoint_slot: SlotNumber,
        unprocessed_epochs: list[EpochNumber],
        epochs_roots_to_check: dict[EpochNumber, tuple[list[SlotBlockRoot], list[SlotBlockRoot]]]
    ):
        executor = ThreadPoolExecutor(max_workers=variables.CSM_ORACLE_MAX_CONCURRENCY)
        try:
            futures = {
                executor.submit(
                    self._check_duties,
                    checkpoint_block_roots,
                    checkpoint_slot,
                    duty_epoch,
                    *epochs_roots_to_check[duty_epoch]
                )
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
    def _check_duties(
        self,
        checkpoint_block_roots: list[BlockRoot | None],
        checkpoint_slot: SlotNumber,
        duty_epoch: EpochNumber,
        duty_epoch_roots: list[SlotBlockRoot],
        next_epoch_roots: list[SlotBlockRoot],
    ):
        logger.info({"msg": f"Processing epoch {duty_epoch}"})

        att_committees = self._prepare_attestation_duties(duty_epoch)
        propose_duties = self._prepare_propose_duties(duty_epoch, checkpoint_block_roots, checkpoint_slot)
        sync_committees = self._prepare_sync_committee_duties(duty_epoch, duty_epoch_roots)

        for slot, root in [*duty_epoch_roots, *next_epoch_roots]:
            missed_slot = root is None
            if missed_slot:
                continue
            attestations, sync_aggregate = self.cc.get_block_attestations_and_sync(root)
            if (slot, root) in duty_epoch_roots:
                propose_duties[slot].included = True
                process_sync(slot, sync_aggregate, sync_committees)
            process_attestations(attestations, att_committees)

        with lock:
            if duty_epoch not in self.state.unprocessed_epochs:
                raise ValueError(f"Epoch {duty_epoch} is not in epochs that should be processed")
            for att_committee in att_committees.values():
                for att_duty in att_committee:
                    self.state.save_att_duty(
                        duty_epoch,
                        att_duty.validator_index,
                        included=att_duty.included,
                    )
            for sync_committee in sync_committees.values():
                for sync_duty in sync_committee:
                    self.state.save_sync_duty(
                        duty_epoch,
                        sync_duty.validator_index,
                        included=sync_duty.included,
                    )
            for proposer_duty in propose_duties.values():
                self.state.save_prop_duty(
                    duty_epoch,
                    proposer_duty.validator_index,
                    included=proposer_duty.included
                )
            self.state.add_processed_epoch(duty_epoch)
            self.state.log_progress()
            unprocessed_epochs = self.state.unprocessed_epochs
            CSM_UNPROCESSED_EPOCHS_COUNT.set(len(unprocessed_epochs))
            CSM_MIN_UNPROCESSED_EPOCH.set(min(unprocessed_epochs or {EpochNumber(-1)}))

    @timeit(
        lambda args, duration: logger.info(
            {"msg": f"Attestation Committees for epoch {args.epoch} prepared in {duration:.2f} seconds"}
        )
    )
    def _prepare_attestation_duties(self, epoch: EpochNumber) -> AttestationCommittees:
        committees = {}
        for committee in self.cc.get_attestation_committees(self.finalized_blockstamp, epoch):
            validators = []
            # Order of insertion is used to track the positions in the committees.
            for validator_index in committee.validators:
                validators.append(ValidatorDuty(validator_index, included=False))
            committees[(committee.slot, committee.index)] = validators
        return committees

    @timeit(
        lambda args, duration: logger.info(
            {"msg": f"Sync Committee for epoch {args.epoch} prepared in {duration:.2f} seconds"}
        )
    )
    def _prepare_sync_committee_duties(
        self, epoch: EpochNumber, epoch_block_roots: list[SlotBlockRoot]
    ) -> dict[SlotNumber, list[ValidatorDuty]]:

        with lock:
            sync_committee = self._get_sync_committee(epoch)

        duties = {}
        for slot, root in epoch_block_roots:
            missed_slot = root is None
            if missed_slot:
                continue
            duties[slot] = [
                ValidatorDuty(validator_index=validator_index, included=False)
                for validator_index in sync_committee.validators
            ]

        return duties

    def _get_sync_committee(self, epoch: EpochNumber) -> SyncCommittee:
        sync_committee_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        if cached_sync_committee := SYNC_COMMITTEES_CACHE.get(sync_committee_period):
            return cached_sync_committee
        from_epoch = EpochNumber(epoch - epoch % EPOCHS_PER_SYNC_COMMITTEE_PERIOD)
        to_epoch = EpochNumber(from_epoch + EPOCHS_PER_SYNC_COMMITTEE_PERIOD - 1)
        logger.info({"msg": f"Preparing cached Sync Committee for [{from_epoch};{to_epoch}] chain epochs"})
        state_blockstamp = build_blockstamp(
            get_prev_non_missed_slot(
                self.cc,
                self.converter.get_epoch_first_slot(epoch),
                self.finalized_blockstamp.slot_number
            )
        )
        sync_committee = self.cc.get_sync_committee(state_blockstamp, epoch)
        SYNC_COMMITTEES_CACHE[sync_committee_period] = sync_committee
        return sync_committee

    @timeit(
        lambda args, duration: logger.info(
            {"msg": f"Propose Duties for epoch {args.epoch} prepared in {duration:.2f} seconds"}
        )
    )
    def _prepare_propose_duties(
        self,
        epoch: EpochNumber,
        checkpoint_block_roots: list[BlockRoot | None],
        checkpoint_slot: SlotNumber
    ) -> dict[SlotNumber, ValidatorDuty]:
        duties = {}
        dependent_root = self._get_dependent_root_for_proposer_duties(epoch, checkpoint_block_roots, checkpoint_slot)
        proposer_duties = self.cc.get_proposer_duties(epoch, dependent_root)
        for duty in proposer_duties:
            duties[duty.slot] = ValidatorDuty(validator_index=duty.validator_index, included=False)
        return duties

    def _get_dependent_root_for_proposer_duties(
        self,
        epoch: EpochNumber,
        checkpoint_block_roots: list[BlockRoot | None],
        checkpoint_slot: SlotNumber
    ) -> BlockRoot:
        dependent_root = None
        dependent_slot = self.converter.get_epoch_last_slot(EpochNumber(epoch - 1))
        try:
            while not dependent_root:
                dependent_root = self._select_block_root_by_slot(
                    checkpoint_block_roots, checkpoint_slot, dependent_slot
                )
                if dependent_root:
                    logger.debug(
                        {
                            "msg": f"Got dependent root from state block roots for epoch {epoch}. "
                                   f"{dependent_slot=} {dependent_root=}"
                        }
                    )
                    break
                dependent_slot = SlotNumber(int(dependent_slot - 1))
        except SlotOutOfRootsRange:
            dependent_non_missed_slot = get_prev_non_missed_slot(
                self.cc,
                dependent_slot,
                self.finalized_blockstamp.slot_number
            ).message.slot
            dependent_root = self.cc.get_block_root(dependent_non_missed_slot).root
            logger.debug(
                {
                    "msg": f"Got dependent root from CL for epoch {epoch}. "
                           f"{dependent_non_missed_slot=} {dependent_root=}"
                }
            )
        return dependent_root


def process_sync(slot: SlotNumber, sync_aggregate: SyncAggregate, committees: SyncCommittees) -> None:
    committee = committees[slot]
    # Spec: https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/beacon-chain.md#syncaggregate
    sync_bits = hex_bitvector_to_list(sync_aggregate.sync_committee_bits)
    for index_in_committee in get_set_indices(sync_bits):
        committee[index_in_committee].included = True


def process_attestations(
    attestations: Iterable[BlockAttestation],
    committees: AttestationCommittees,
) -> None:
    for attestation in attestations:
        committee_offset = 0
        att_bits = hex_bitlist_to_list(attestation.aggregation_bits)
        for committee_idx in get_committee_indices(attestation):
            committee = committees.get((attestation.data.slot, committee_idx), [])
            att_committee_bits = att_bits[committee_offset:][: len(committee)]
            for index_in_committee in get_set_indices(att_committee_bits):
                committee[index_in_committee].included = True
            committee_offset += len(committee)


def get_committee_indices(attestation: BlockAttestation) -> list[CommitteeIndex]:
    return [CommitteeIndex(i) for i in get_set_indices(hex_bitvector_to_list(attestation.committee_bits))]


def get_set_indices(bits: Sequence[bool]) -> list[int]:
    """Returns indices of truthy values in the supplied sequence"""
    return [i for i, bit in enumerate(bits) if bit]


def hex_bitvector_to_list(bitvector: str) -> list[bool]:
    bytes_ = hex_str_to_bytes(bitvector)
    return _bytes_to_bool_list(bytes_)


def hex_bitlist_to_list(bitlist: str) -> list[bool]:
    bytes_ = hex_str_to_bytes(bitlist)
    if not bytes_ or bytes_[-1] == 0:
        raise ValueError(f"Got invalid {bitlist=}")
    bitlist_len = int.from_bytes(bytes_, "little").bit_length() - 1
    return _bytes_to_bool_list(bytes_, count=bitlist_len)


def _bytes_to_bool_list(bytes_: bytes, count: int | None = None) -> list[bool]:
    count = count if count is not None else len(bytes_) * 8
    # copied from https://github.com/ethereum/py-ssz/blob/main/ssz/sedes/bitvector.py#L66
    return [bool((bytes_[bit_index // 8] >> bit_index % 8) % 2) for bit_index in range(count)]
