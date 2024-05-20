import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import cast, Iterable

from timeout_decorator import TimeoutError as DecoratorTimeoutError

from src.modules.csm.state import State
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.typings import BlockAttestation
from src.typings import BlockRoot, BlockStamp, EpochNumber, SlotNumber, ValidatorIndex
from src.utils.range import sequence
from src.utils.web3converter import Web3Converter

logger = logging.getLogger(__name__)
lock = Lock()


class CheckpointsFactory:
    cc: ConsensusClient
    converter: Web3Converter
    state: State

    # min checkpoint step is 10 because it's a reasonable number of epochs to process at once (~1 hour)
    MIN_CHECKPOINT_STEP = 10
    # max checkpoint step is 255 epochs because block_roots size from state is 8192 slots (256 epochs)
    # to check duty of every epoch, we need to check 64 slots (32 slots of duty epoch + 32 slots of next epoch)
    # in the end we got 255 committees and 8192 block_roots to check them for every checkpoint
    MAX_CHECKPOINT_STEP = 255

    def __init__(self, cc: ConsensusClient, converter: Web3Converter, state: State):
        self.cc = cc
        self.converter = converter
        self.state = state

    def prepare_checkpoints(self, l_epoch: EpochNumber, r_epoch: EpochNumber, finalized_epoch: EpochNumber):
        def _prepare_checkpoint(_slot: SlotNumber, _duty_epochs: list[EpochNumber]):
            return Checkpoint(self.cc, self.converter, self.state, _slot, _duty_epochs)

        if not self.state.unprocessed_epochs:
            logger.info({"msg": "All epochs processed. No checkpoint required."})
            return []

        l_epoch = min(self.state.unprocessed_epochs) or l_epoch
        assert l_epoch <= r_epoch

        processing_delay = finalized_epoch - l_epoch
        if processing_delay < self.MIN_CHECKPOINT_STEP and finalized_epoch < r_epoch:
            logger.info(
                {
                    "msg": f"Minimum checkpoint step is not reached, current delay is {processing_delay} epochs",
                    "finalized_epoch": finalized_epoch,
                    "l_epoch": l_epoch,
                    "r_epoch": r_epoch,
                }
            )
            return []

        r_epoch = min(r_epoch, EpochNumber(finalized_epoch - 1))
        duty_epochs = cast(list[EpochNumber], list(sequence(l_epoch, r_epoch)))
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
    cc: ConsensusClient
    converter: Web3Converter

    state: State

    slot: SlotNumber  # last slot of the epoch
    duty_epochs: list[EpochNumber]  # max 255 elements
    block_roots: list[BlockRoot | None]  # max 8192 elements

    def __init__(
        self,
        cc: ConsensusClient,
        converter: Web3Converter,
        state: State,
        slot: SlotNumber,
        duty_epochs: list[EpochNumber],
    ):
        self.cc = cc
        self.converter = converter
        self.slot = slot
        self.duty_epochs = duty_epochs
        self.block_roots = []
        self.state = state

    def process(self, last_finalized_blockstamp: BlockStamp):
        def _unprocessed():
            for _epoch in self.duty_epochs:
                if _epoch in self.state.unprocessed_epochs:
                    if not self.block_roots:
                        self._get_block_roots()
                    yield _epoch

        with ThreadPoolExecutor() as ext:
            try:
                futures = {
                    ext.submit(self._process_epoch, last_finalized_blockstamp, duty_epoch)
                    for duty_epoch in _unprocessed()
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

    def _select_roots_to_check(self, duty_epoch: EpochNumber) -> list[BlockRoot | None]:
        # inspired by the spec
        # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#get_block_root_at_slot
        roots_to_check = []
        slots = sequence(
            self.converter.get_epoch_first_slot(duty_epoch),
            self.converter.get_epoch_last_slot(EpochNumber(duty_epoch + 1)),
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
    ):
        logger.info({"msg": f"Process epoch {duty_epoch}"})
        start = time.time()
        committees = self._prepare_committees(last_finalized_blockstamp, EpochNumber(duty_epoch))
        for root in self._select_roots_to_check(duty_epoch):
            if root is None:
                continue
            attestations = self.cc.get_block_attestations(BlockRoot(root))
            self._process_attestations(attestations, committees)

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

    def _process_attestations(self, attestations: Iterable[BlockAttestation], committees: dict) -> None:
        def to_bits(aggregation_bits: str):
            # copied from https://github.com/ethereum/py-ssz/blob/main/ssz/sedes/bitvector.py#L66
            att_bytes = bytes.fromhex(aggregation_bits[2:])
            return [bool((att_bytes[bit_index // 8] >> bit_index % 8) % 2) for bit_index in range(len(att_bytes) * 8)]

        for attestation in attestations:
            committee_id = f"{attestation.data.slot}{attestation.data.index}"
            committee = committees.get(committee_id)
            att_bits = to_bits(attestation.aggregation_bits)
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
