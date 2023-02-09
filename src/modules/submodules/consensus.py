import logging
from abc import ABC
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

from eth_typing import Address

from src.web3_extentions.typings import Web3
from web3.contract import Contract

from src import variables
from src.typings import BlockStamp, SlotNumber


logger = logging.getLogger(__name__)


class IsNotMemberException(Exception):
    pass


@dataclass
class MemberInfo:
    is_member: bool
    last_report_ref_slot: SlotNumber
    current_ref_slot: SlotNumber
    member_ref_slot: SlotNumber
    member_report_for_current_ref_slot: bytes
    deadline_slot: SlotNumber


class ConsensusModule(ABC):
    """
    Calculates ref_slot to report for Oracle.
    Returns one of
    If report could be done
        slot_number, state_hash, block_number, block_hash

    If report could not be done
        None

    Goal:
    - Skip missed slots
    - Skip non-finalized slot
    - Check ref_slot for each member specifically
    """
    report_contract: Contract = None

    def __init__(self, w3: Web3):
        self.w3 = w3

        if self.report_contract is None:
            raise NotImplementedError('report_contract attribute should be set.')

    @lru_cache(maxsize=1)
    def _get_consensus_contract(self, blockstamp: BlockStamp) -> Contract:
        return self.w3.eth.contract(
            address=self._get_consensus_contract_address(blockstamp),
            abi=self.w3.lido_contracts.load_abi('LidoOracle'),
        )

    @lru_cache(maxsize=1)
    def _get_consensus_contract_address(self, blockstamp: BlockStamp) -> Address:
        return self.report_contract.functions.getConsensusContract().call(block_identifier=blockstamp.block_hash)

    @lru_cache(maxsize=1)
    def _get_member_info(self, blockstamp: BlockStamp) -> MemberInfo:
        consensus_contract = self._get_consensus_contract(blockstamp)

        # Defaults for dry mode
        current_ref_slot, deadline_slot = self._get_current_frame(blockstamp)
        is_member, last_report_ref_slot, member_report_for_current_ref_slot = True, 0, b''
        member_ref_slot = current_ref_slot

        if variables.ACCOUNT:
            (
                is_member,
                last_report_ref_slot,
                member_ref_slot,
                member_report_for_current_ref_slot,
            ) = consensus_contract.functions.getMemberInfo(
                variables.ACCOUNT.address,
            ).call(block_identifier=blockstamp.block_hash)

            if not is_member:
                raise IsNotMemberException(
                    'Provided Account is not part of Oracle\'s members. '
                    'For dry mode remove MEMBER_PRIV_KEY from variables.'
                )

        return MemberInfo(
            is_member=is_member,
            last_report_ref_slot=last_report_ref_slot,
            current_ref_slot=current_ref_slot,
            member_ref_slot=member_ref_slot,
            member_report_for_current_ref_slot=member_report_for_current_ref_slot,
            deadline_slot=deadline_slot,
        )

    @lru_cache(maxsize=1)
    def _get_current_frame(self, blockstamp: BlockStamp) -> Tuple[SlotNumber, SlotNumber]:
        consensus_contract = self._get_consensus_contract(blockstamp)
        return consensus_contract.functions.getCurrentFrame().call(
            block_identifier=blockstamp.block_hash,
        )

    def get_blockstamp_for_report(self, blockstamp: BlockStamp) -> Optional[BlockStamp]:
        member_info = self._get_member_info(blockstamp)

        if blockstamp.slot_number < member_info.member_ref_slot:
            logger.info({'msg': 'Reference slot is not yet finalized.'})
            return

        # Maybe check head slot number?
        if blockstamp.slot_number > member_info.deadline_slot:
            logger.info({'msg': 'Deadline missed.'})
            return

        return self._get_first_non_missed_slot(blockstamp, member_info.current_ref_slot)

    def _get_first_non_missed_slot(self, blockstamp: BlockStamp, slot: SlotNumber) -> BlockStamp:
        _, epoch_per_frame = self._get_frame_config(blockstamp)

        for i in range(slot, slot - epoch_per_frame * 32, -1):
            try:
                root = self.w3.cc.get_block_root(slot).root
            except KeyError:
                logger.warning({'msg': f'Missed slot: {slot}. Check next slot.'})
                continue

            slot_details = self.w3.cc.get_block_details(root)

            execution_data = slot_details.message.body['execution_payload']

            return BlockStamp(
                block_root=root,
                slot_number=slot,
                state_root=slot_details.message.state_root,
                block_number=execution_data['block_number'],
                block_hash=execution_data['block_hash']
            )

    @lru_cache(maxsize=1)
    def _get_frame_config(self, blockstamp: BlockStamp) -> Tuple[int, int]:
        consensus = self._get_consensus_contract(blockstamp)
        initial_epoch, epochs_per_frame = consensus.functions.getFrameConfig().call(block_identifier=blockstamp.block_hash)
        return initial_epoch, epochs_per_frame
