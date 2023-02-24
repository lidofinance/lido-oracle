import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from time import sleep
from typing import Optional

from eth_abi import encode
from eth_typing import Address
from hexbytes import HexBytes

from src.modules.submodules.exceptions import IsNotMemberException, QuorumHashDoNotMatch
from src.modules.submodules.typings import ChainConfig, MemberInfo, ZERO_HASH, CurrentFrame, FrameConfig
from src.utils.abi import named_tuple_to_dataclass
from src.utils.slot import get_first_non_missed_slot
from src.web3py.typings import Web3
from web3.contract import Contract

from src import variables
from src.typings import BlockStamp, SlotNumber, BlockNumber, EpochNumber


logger = logging.getLogger(__name__)


DEFAULT_SLEEP = 12


class ConsensusModule(ABC):
    report_contract: Contract

    CONTRACT_VERSION: int
    CONSENSUS_VERSION: int

    def __init__(self, w3: Web3):
        self.w3 = w3

        if self.report_contract is None:
            raise NotImplementedError('report_contract attribute should be set.')

        if self.CONSENSUS_VERSION is None or self.CONSENSUS_VERSION is None:
            raise NotImplementedError('CONSENSUS_VERSION and CONSENSUS_VERSION should be set.')

    # ----- Web3 data requests -----
    @lru_cache(maxsize=1)
    def _get_consensus_contract(self, blockstamp: BlockStamp) -> Contract:
        return self.w3.eth.contract(
            address=self._get_consensus_contract_address(blockstamp),
            abi=self.w3.lido_contracts.load_abi('HashConsensus'),
            decode_tuples=True,
        )

    @lru_cache(maxsize=1)
    def _get_consensus_contract_address(self, blockstamp: BlockStamp) -> Address:
        return self.report_contract.functions.getConsensusContract().call(block_identifier=blockstamp.block_hash)

    @lru_cache(maxsize=1)
    def _get_chain_config(self, blockstamp: BlockStamp) -> ChainConfig:
        consensus_contract = self._get_consensus_contract(blockstamp)
        return named_tuple_to_dataclass(
            consensus_contract.functions.getChainConfig().call(block_identifier=blockstamp.block_hash),
            ChainConfig,
        )

    @lru_cache(maxsize=1)
    def _get_member_info(self, blockstamp: BlockStamp) -> MemberInfo:
        consensus_contract = self._get_consensus_contract(blockstamp)

        # Defaults for dry mode
        current_frame = self._get_current_frame(blockstamp)
        frame_config = self._get_frame_config(blockstamp)
        is_member = is_submit_member = is_fast_lane = True
        current_frame_consensus_report = current_frame_member_report = ZERO_HASH

        if variables.ACCOUNT:
            (
                # Current frame's reference slot.
                current_frame_ref_slot,
                # Consensus report for the current frame, if any. Zero bytes otherwise.
                current_frame_consensus_report,
                # Whether the provided address is a member of the oracle committee.
                is_member,
                # Whether the oracle committee member is in the fast line members subset of the current reporting frame.
                is_fast_lane,
                # Whether the oracle committee member is allowed to submit a report at the moment of the call.
                _,  # can_report
                # The last reference slot for which the member submitted a report.
                _,  # last_member_report_ref_slot
                # The hash reported by the member for the current frame, if any.
                current_frame_member_report,
            ) = consensus_contract.functions.getConsensusStateForMember(
                variables.ACCOUNT.address,
            ).call(block_identifier=blockstamp.block_hash)

            submit_role = self.report_contract.functions.SUBMIT_DATA_ROLE().call(
                block_identifier=blockstamp.block_hash,
            )
            is_submit_member = self.report_contract.functions.hasRole(
                submit_role,
                variables.ACCOUNT.address,
            ).call(
                block_identifier=blockstamp.block_hash,
            )

            if not is_member and not is_submit_member:
                raise IsNotMemberException(
                    'Provided Account is not part of Oracle\'s members and has no submit role. '
                    'For dry mode remove MEMBER_PRIV_KEY from variables.'
                )

        mi = MemberInfo(
            is_report_member=is_member,
            is_submit_member=is_submit_member,
            is_fast_lane=is_fast_lane,
            fast_lane_length_slot=frame_config.fast_lane_length_slots,
            current_frame_consensus_report=current_frame_consensus_report,
            current_frame_ref_slot=current_frame.ref_slot,
            current_frame_member_report=current_frame_member_report,
            deadline_slot=current_frame.report_processing_deadline_slot,
        )
        logger.info({'msg': 'Fetch member info.', 'value': mi})

        return mi

    @lru_cache(maxsize=1)
    def _get_current_frame(self, blockstamp: BlockStamp) -> CurrentFrame:
        consensus_contract = self._get_consensus_contract(blockstamp)
        cf = CurrentFrame(*consensus_contract.functions.getCurrentFrame().call(block_identifier=blockstamp.block_hash))
        logger.info({'msg': 'Fetch current frame.', 'value': cf})
        return cf

    @lru_cache(maxsize=1)
    def _get_frame_config(self, blockstamp: BlockStamp) -> FrameConfig:
        consensus_contract = self._get_consensus_contract(blockstamp)
        fc = FrameConfig(*consensus_contract.functions.getFrameConfig().call(block_identifier=blockstamp.block_hash))
        logger.info({'msg': 'Fetch frame config.', 'value': fc})
        return fc

    # ----- Calculation reference slot for report -----
    def get_blockstamp_for_report(self, last_finalized_blockstamp: BlockStamp) -> Optional[BlockStamp]:
        """
        Get blockstamp that should be used to build and send report for current frame.
        Returns:
            Non-missed finalized blockstamp
        """
        member_info = self._get_member_info(last_finalized_blockstamp)

        latest_blockstamp = self._get_latest_blockstamp()

        # Check if contract is currently reportable
        if not self.is_contract_reportable(latest_blockstamp):
            logger.info({'msg': 'Contract is not reportable.'})
            return

        # Check if current slot is higher than member slot
        if latest_blockstamp.slot_number < member_info.current_frame_ref_slot:
            logger.info({'msg': 'Reference slot is not yet finalized.'})
            return

        # Check if current slot is higher than member slot + slots_delay
        if not member_info.is_fast_lane:
            if latest_blockstamp.slot_number < member_info.current_frame_ref_slot + member_info.fast_lane_length_slot:
                logger.info({'msg': f'Member is not in fast lane, so report will be postponed for [{member_info.fast_lane_length_slot}] slots.'})
                return

        # Check latest block didn't miss deadline.
        if latest_blockstamp.slot_number >= member_info.deadline_slot:
            logger.info({'msg': 'Deadline missed.'})
            return

        chain_config = self._get_chain_config(last_finalized_blockstamp)
        bs = get_first_non_missed_slot(
            self.w3.cc,
            ref_slot=member_info.current_frame_ref_slot,
            ref_epoch=EpochNumber(member_info.current_frame_ref_slot // chain_config.slots_per_epoch),
        )
        logger.info({'msg': 'Calculate blockstamp for report.', 'value': bs})
        return bs

    # ----- Working with report -----
    def process_report(self, blockstamp: BlockStamp) -> None:
        """Builds and sends report for current frame with provided blockstamp."""
        report_data = self.build_report(blockstamp)
        logger.info({'msg': 'Build report.', 'value': report_data})

        report_hash = self._get_report_hash(report_data)
        logger.info({'msg': 'Calculate report hash.', 'value': report_hash})
        self._process_report_hash(blockstamp, report_hash)
        # Even if report hash transaction was failed we have to check if we can report data for current frame
        self._process_report_data(blockstamp, report_data, report_hash)

    def _process_report_hash(self, blockstamp: BlockStamp, report_hash: HexBytes) -> None:
        _, member_info = self._get_latest_data()

        if not member_info.is_report_member:
            logger.info({'msg': 'Account can`t submit report hash.'})
            return

        if HexBytes(member_info.current_frame_member_report) != report_hash:
            logger.info({'msg': f'Send report hash. Consensus version: [{self.CONSENSUS_VERSION}]'})
            self._send_report_hash(blockstamp, report_hash, self.CONSENSUS_VERSION)
        else:
            logger.info({'msg': 'Provided hash already submitted.'})

    def _process_report_data(self, blockstamp: BlockStamp, report_data: tuple, report_hash: HexBytes):
        latest_blockstamp, member_info = self._get_latest_data()

        # If the quorum is ready to report data, the member should have opportunity to send report
        if (
            # If there is no quorum
            member_info.current_frame_consensus_report == ZERO_HASH
            # And member did not send the report
            and HexBytes(member_info.current_frame_member_report) != report_hash
        ):
            logger.info({'msg': 'Quorum is not ready and member did not send the report hash.'})
            return

        # In worst case exception will be raised in MAX_CYCLE_LIFETIME_IN_SECONDS seconds
        for retry_num in range(2 * member_info.fast_lane_length_slot):
            latest_blockstamp, member_info = self._get_latest_data()
            if HexBytes(member_info.current_frame_consensus_report) != ZERO_HASH:
                break
            logger.info({'msg': f'Wait until consensus will be reached. Sleep for {DEFAULT_SLEEP}'})
            sleep(DEFAULT_SLEEP)

        if HexBytes(member_info.current_frame_consensus_report) != report_hash:
            msg = 'Oracle`s hash differs from consensus report hash.'
            logger.warning({
                'msg': msg,
                'consensus_report_hash': str(HexBytes(member_info.current_frame_consensus_report)),
                'report_hash': str(report_hash),
            })
            raise QuorumHashDoNotMatch(msg)

        if self.is_main_data_submitted(latest_blockstamp):
            logger.info({'msg': 'Main data already submitted.'})
            return

        # Fast lane offchain implementation for report data
        slots_to_sleep = self._get_slot_delay_before_data_submit(blockstamp)
        if slots_to_sleep != 0:
            _, seconds_per_slot, _ = self._get_chain_config(blockstamp)

            logger.info({'msg': f'Sleep for {slots_to_sleep} slots before sending data.'})
            for slot in range(slots_to_sleep):
                sleep(seconds_per_slot)

                latest_blockstamp, member_info = self._get_latest_data()
                if self.is_main_data_submitted(latest_blockstamp):
                    logger.info({'msg': 'Main data was submitted.'})
                    return

        logger.info({'msg': f'Send report data. Contract version: [{self.CONTRACT_VERSION}]'})
        # If data already submitted transaction will be locally reverted, no need to check status manually
        self._submit_report(report_data, self.CONTRACT_VERSION)

    def _get_latest_data(self) -> tuple[BlockStamp, MemberInfo]:
        latest_blockstamp = self._get_latest_blockstamp()
        logger.info({'msg': 'Get latest blockstamp.', 'value': latest_blockstamp})

        member_info = self._get_member_info(latest_blockstamp)
        logger.info({'msg': 'Get current member info.', 'value': member_info})
        return latest_blockstamp, member_info

    def _get_report_hash(self, report_data: tuple):
        # The Accounting Oracle and Ejector Bus has same named method to report data
        report_function_name = 'submitReportData'

        report_function_abi = next(filter(lambda x: 'name' in x and x['name'] == report_function_name, self.report_contract.abi))

        # First input is ReportData structure
        report_data_abi = report_function_abi['inputs'][0]['components']

        # Transform abi to string
        report_str_abi = ','.join(map(lambda x: x['type'], report_data_abi))

        # Transform str abi to tuple, because ReportData is struct
        encoded = encode([f'({report_str_abi})'], [report_data])

        report_hash = self.w3.keccak(encoded)
        logger.info({'msg': 'Calculate report hash.', 'value': report_hash})
        return report_hash

    def _send_report_hash(self, blockstamp: BlockStamp, report_hash: bytes, consensus_version: int):
        consensus_contract = self._get_consensus_contract(blockstamp)

        tx = consensus_contract.functions.submitReport(blockstamp.slot_number, report_hash, consensus_version)

        if self.w3.transaction.check_transaction(tx, variables.ACCOUNT.address):
            self.w3.transaction.sign_and_send_transaction(tx, variables.GAS_LIMIT, variables.ACCOUNT)

    def _submit_report(self, report: tuple, contract_version: int):
        tx = self.report_contract.functions.submitReportData(report, contract_version)

        if self.w3.transaction.check_transaction(tx, variables.ACCOUNT.address):
            self.w3.transaction.sign_and_send_transaction(tx, variables.GAS_LIMIT, variables.ACCOUNT)

    def _get_latest_blockstamp(self) -> BlockStamp:
        root = self.w3.cc.get_block_root('head').root
        slot_details = self.w3.cc.get_block_details(root)
        slot_number = SlotNumber(int(slot_details.message.slot))

        bs = BlockStamp(
            block_root=root,
            slot_number=slot_number,
            state_root=slot_details.message.state_root,
            block_number=BlockNumber(int(slot_details.message.body['execution_payload']['block_number'])),
            block_hash=slot_details.message.body['execution_payload']['block_hash'],
            block_timestamp=int(slot_details.message.body['execution_payload']['timestamp']),
            ref_slot=slot_number,
            ref_epoch=None,
        )

        logger.debug({'msg': 'Fetch latest blockstamp.', 'value': bs})
        return bs

    def _get_slot_delay_before_data_submit(self, blockstamp: BlockStamp) -> int:
        """Returns in slots time to sleep before data report."""
        consensus_contract = self._get_consensus_contract(blockstamp)

        members, _ = consensus_contract.functions.getMembers().call(block_identifier=blockstamp.block_hash)

        mem_position = members.index(variables.ACCOUNT.address)

        frame_config = self._get_frame_config(blockstamp)
        chain_config = self._get_chain_config(blockstamp)

        current_frame_number = int(blockstamp.slot_number / chain_config.slots_per_epoch / frame_config.epochs_per_frame)
        current_position = current_frame_number % len(members)

        sleep_count = mem_position - current_position
        if sleep_count < 0:
            sleep_count += len(members)

        logger.info({'msg': 'Calculate slots to sleep.', 'value': sleep_count})
        return sleep_count

    @abstractmethod
    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: BlockStamp) -> tuple:
        """Returns ReportData struct with calculated data."""
        pass

    @abstractmethod
    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        """Returns if main data already submitted"""
        pass

    @abstractmethod
    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        """Returns true if contract is ready for report"""
        pass
