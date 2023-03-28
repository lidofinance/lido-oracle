import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from time import sleep
from typing import Optional

from eth_abi import encode
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3.contract import AsyncContract, Contract

from src import variables
from src.metrics.prometheus.basic import ORACLE_SLOT_NUMBER, ORACLE_BLOCK_NUMBER, GENESIS_TIME
from src.typings import BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber
from src.metrics.prometheus.business import (
    ORACLE_MEMBER_LAST_REPORT_REF_SLOT,
    FRAME_CURRENT_REF_SLOT,
    FRAME_DEADLINE_SLOT,
    ORACLE_MEMBER_INFO
)
from src.modules.submodules.exceptions import IsNotMemberException, IncompatibleContractVersion
from src.modules.submodules.typings import ChainConfig, MemberInfo, ZERO_HASH, CurrentFrame, FrameConfig
from src.utils.abi import named_tuple_to_dataclass
from src.utils.blockstamp import build_blockstamp
from src.utils.web3converter import Web3Converter
from src.utils.slot import get_reference_blockstamp
from src.web3py.typings import Web3

logger = logging.getLogger(__name__)


class ConsensusModule(ABC):
    report_contract: Contract

    CONTRACT_VERSION: int
    CONSENSUS_VERSION: int

    def __init__(self, w3: Web3):
        self.w3 = w3

        if self.report_contract is None:
            raise NotImplementedError('report_contract attribute should be set.')

        if self.CONTRACT_VERSION is None or self.CONSENSUS_VERSION is None:
            raise NotImplementedError('CONTRACT_VERSION and CONSENSUS_VERSION should be set.')

    def check_contract_configs(self):
        root = self.w3.cc.get_block_root('head').root
        block_details = self.w3.cc.get_block_details(root)
        bs = build_blockstamp(block_details)

        config = self.get_chain_config(bs)
        cc_config = self.w3.cc.get_config_spec()
        genesis_time = int(self.w3.cc.get_genesis().genesis_time)
        GENESIS_TIME.set(genesis_time)
        if any((config.genesis_time != genesis_time,
                config.seconds_per_slot != int(cc_config.SECONDS_PER_SLOT),
                config.slots_per_epoch != int(cc_config.SLOTS_PER_EPOCH))):
            raise ValueError('Contract chain config is not compatible with Beacon chain.\n'
                             f'Contract config: {config}\n'
                             f'Beacon chain config: {genesis_time=}, {cc_config.SECONDS_PER_SLOT=}, {cc_config.SLOTS_PER_EPOCH=}')

    # ----- Web3 data requests -----
    @lru_cache(maxsize=1)
    def _get_consensus_contract(self, blockstamp: BlockStamp) -> Contract | AsyncContract:
        return self.w3.eth.contract(
            address=self._get_consensus_contract_address(blockstamp),
            abi=self.w3.lido_contracts.load_abi('HashConsensus'),
            decode_tuples=True,
        )

    def _get_consensus_contract_address(self, blockstamp: BlockStamp) -> ChecksumAddress:
        return self.report_contract.functions.getConsensusContract().call(block_identifier=blockstamp.block_hash)

    def _get_consensus_contract_members(self, blockstamp: BlockStamp):
        consensus_contract = self._get_consensus_contract(blockstamp)
        members, last_reported_ref_slots = consensus_contract.functions.getMembers().call(block_identifier=blockstamp.block_hash)
        return members, last_reported_ref_slots

    @lru_cache(maxsize=1)
    def get_chain_config(self, blockstamp: BlockStamp) -> ChainConfig:
        consensus_contract = self._get_consensus_contract(blockstamp)
        cc = named_tuple_to_dataclass(
            consensus_contract.functions.getChainConfig().call(block_identifier=blockstamp.block_hash),
            ChainConfig,
        )
        logger.info({'msg': 'Fetch chain config.', 'value': cc})
        return cc

    @lru_cache(maxsize=1)
    def get_current_frame(self, blockstamp: BlockStamp) -> CurrentFrame:
        consensus_contract = self._get_consensus_contract(blockstamp)
        cf = named_tuple_to_dataclass(
            consensus_contract.functions.getCurrentFrame().call(block_identifier=blockstamp.block_hash),
            CurrentFrame,
        )
        logger.info({'msg': 'Fetch current frame.', 'value': cf})
        return cf

    @lru_cache(maxsize=1)
    def get_frame_config(self, blockstamp: BlockStamp) -> FrameConfig:
        consensus_contract = self._get_consensus_contract(blockstamp)
        fc = named_tuple_to_dataclass(
            consensus_contract.functions.getFrameConfig().call(block_identifier=blockstamp.block_hash),
            FrameConfig,
        )
        logger.info({'msg': 'Fetch frame config.', 'value': fc})
        return fc

    @lru_cache(maxsize=1)
    def get_member_info(self, blockstamp: BlockStamp) -> MemberInfo:
        consensus_contract = self._get_consensus_contract(blockstamp)

        # Defaults for dry mode
        current_frame = self.get_current_frame(blockstamp)
        frame_config = self.get_frame_config(blockstamp)
        is_member = is_submit_member = is_fast_lane = True
        last_member_report_ref_slot = SlotNumber(0)
        current_frame_consensus_report = current_frame_member_report = ZERO_HASH

        if variables.ACCOUNT:
            (
                # Current frame's reference slot.
                _,  # current_frame_ref_slot
                # Consensus report for the current frame, if any. Zero bytes otherwise.
                current_frame_consensus_report,
                # Whether the provided address is a member of the oracle committee.
                is_member,
                # Whether the oracle committee member is in the fast line members subset of the current reporting frame.
                is_fast_lane,
                # Whether the oracle committee member is allowed to submit a report at the moment of the call.
                _,  # can_report
                # The last reference slot for which the member submitted a report.
                last_member_report_ref_slot,
                # The hash reported by the member for the current frame, if any.
                current_frame_member_report,
            ) = consensus_contract.functions.getConsensusStateForMember(
                variables.ACCOUNT.address,
            ).call(block_identifier=blockstamp.block_hash)

            is_submit_member = self._is_submit_member(blockstamp)

            if not is_member and not is_submit_member:
                raise IsNotMemberException(
                    'Provided Account is not part of Oracle\'s members and has no submit role. '
                    'For dry mode remove MEMBER_PRIV_KEY from variables.'
                )

        mi = MemberInfo(
            is_report_member=is_member,
            is_submit_member=is_submit_member,
            is_fast_lane=is_fast_lane,
            last_report_ref_slot=last_member_report_ref_slot,
            fast_lane_length_slot=frame_config.fast_lane_length_slots,
            current_frame_consensus_report=current_frame_consensus_report,
            current_frame_ref_slot=current_frame.ref_slot,
            current_frame_member_report=current_frame_member_report,
            deadline_slot=current_frame.report_processing_deadline_slot,
        )
        logger.info({'msg': 'Fetch member info.', 'value': mi})

        return mi

    def _is_submit_member(self, blockstamp: BlockStamp) -> bool:
        if not variables.ACCOUNT:
            return True

        submit_role = self.report_contract.functions.SUBMIT_DATA_ROLE().call(
            block_identifier=blockstamp.block_hash,
        )
        is_submit_member = self.report_contract.functions.hasRole(
            submit_role,
            variables.ACCOUNT.address,
        ).call(
            block_identifier=blockstamp.block_hash,
        )

        return is_submit_member

    # ----- Calculation reference slot for report -----
    def get_blockstamp_for_report(self, last_finalized_blockstamp: BlockStamp) -> Optional[ReferenceBlockStamp]:
        """
        Get blockstamp that should be used to build and send report for current frame.
        Returns:
            Non-missed reference slot blockstamp in case contract is reportable.
        """
        latest_blockstamp = self._get_latest_blockstamp()

        self._check_contract_versions(latest_blockstamp)

        # Check if contract is currently reportable
        if not self.is_contract_reportable(latest_blockstamp):
            logger.info({'msg': 'Contract is not reportable.'})
            return None

        member_info = self.get_member_info(latest_blockstamp)

        # Check if current slot is higher than member slot
        if last_finalized_blockstamp.slot_number < member_info.current_frame_ref_slot:
            logger.info({'msg': 'Reference slot is not yet finalized.'})
            return None

        # Check latest block didn't miss the deadline.
        if latest_blockstamp.slot_number >= member_info.deadline_slot:
            logger.info({'msg': 'Deadline missed.'})
            return None

        chain_config = self.get_chain_config(last_finalized_blockstamp)
        frame_config = self.get_frame_config(last_finalized_blockstamp)

        converter = Web3Converter(chain_config, frame_config)

        bs = get_reference_blockstamp(
            cc=self.w3.cc,
            ref_slot=member_info.current_frame_ref_slot,
            ref_epoch=converter.get_epoch_by_slot(member_info.current_frame_ref_slot),
            last_finalized_slot_number=last_finalized_blockstamp.slot_number,
        )
        logger.info({'msg': 'Calculate blockstamp for report.', 'value': bs})
        return bs

    def _check_contract_versions(self, blockstamp: BlockStamp):
        contract_version = self.report_contract.functions.getContractVersion().call(block_identifier=blockstamp.block_hash)
        consensus_version = self.report_contract.functions.getConsensusVersion().call(block_identifier=blockstamp.block_hash)

        if contract_version != self.CONTRACT_VERSION or consensus_version != self.CONSENSUS_VERSION:
            raise IncompatibleContractVersion(
                f'Incompatible Oracle version. '
                f'Expected contract version {contract_version} got {self.CONTRACT_VERSION}. '
                f'Expected consensus version {consensus_version} got {self.CONSENSUS_VERSION}.'
            )

    # ----- Working with report -----
    def process_report(self, blockstamp: ReferenceBlockStamp) -> None:
        """Builds and sends report for current frame with provided blockstamp."""
        report_data = self.build_report(blockstamp)
        logger.info({'msg': 'Build report.', 'value': report_data})

        report_hash = self._encode_data_hash(report_data)
        logger.info({'msg': 'Calculate report hash.', 'value': report_hash})
        # We need to check whether report has unexpected data before sending.
        # otherwise we have to check it manually.
        if not self.is_reporting_allowed(blockstamp):
            logger.warning({'msg': 'Reporting checks are not passed. Report will not be sent.'})
            return
        self._process_report_hash(blockstamp, report_hash)
        # Even if report hash transaction was failed we have to check if we can report data for current frame
        self._process_report_data(blockstamp, report_data, report_hash)

    def _process_report_hash(self, blockstamp: ReferenceBlockStamp, report_hash: HexBytes) -> None:
        latest_blockstamp, member_info = self._get_latest_data()

        # Check if current slot is newer than (member slot + slots_delay)
        if not member_info.is_fast_lane:
            if latest_blockstamp.slot_number < member_info.current_frame_ref_slot + member_info.fast_lane_length_slot:
                logger.info({'msg': f'Member is not in fast lane, so report will be postponed for [{member_info.fast_lane_length_slot}] slots.'})
                return None

        if not member_info.is_report_member:
            logger.info({'msg': 'Account can`t submit report hash.'})
            return None

        if HexBytes(member_info.current_frame_member_report) != report_hash:
            logger.info({'msg': f'Send report hash. Consensus version: [{self.CONSENSUS_VERSION}]'})
            self._send_report_hash(blockstamp, report_hash, self.CONSENSUS_VERSION)
        else:
            logger.info({'msg': 'Provided hash already submitted.'})

        return None

    def _process_report_data(self, blockstamp: ReferenceBlockStamp, report_data: tuple, report_hash: HexBytes):
        latest_blockstamp, member_info = self._get_latest_data()

        if member_info.current_frame_consensus_report == ZERO_HASH:
            logger.info({'msg': 'Quorum is not ready.'})
            return

        if HexBytes(member_info.current_frame_consensus_report) != report_hash:
            msg = 'Oracle`s hash differs from consensus report hash.'
            logger.error({
                'msg': msg,
                'consensus_report_hash': str(HexBytes(member_info.current_frame_consensus_report)),
                'report_hash': str(report_hash),
            })
            return

        if self.is_main_data_submitted(latest_blockstamp):
            logger.info({'msg': 'Main data already submitted.'})
            return

        # Fast lane offchain implementation for report data
        # If the member was added in the current frame,
        # the result of _get_slot_delay_before_data_submit may be inconsistent for different latest blocks, but it's ok.
        # We can't use ref blockstamp here because new oracle member will fail is_member check,
        # because he wasn't in quorum on ref_slot
        slots_to_sleep = self._get_slot_delay_before_data_submit(latest_blockstamp)
        if slots_to_sleep:
            chain_configs = self.get_chain_config(blockstamp)

            logger.info({'msg': f'Sleep for {slots_to_sleep} slots before sending data.'})
            for _ in range(slots_to_sleep):
                sleep(chain_configs.seconds_per_slot)

                latest_blockstamp, member_info = self._get_latest_data()
                if self.is_main_data_submitted(latest_blockstamp):
                    logger.info({'msg': 'Main data was submitted.'})
                    return

        if self.is_main_data_submitted(latest_blockstamp):
            logger.info({'msg': 'Main data was submitted.'})
            return

        logger.info({'msg': f'Send report data. Contract version: [{self.CONTRACT_VERSION}]'})
        # If data already submitted transaction will be locally reverted, no need to check status manually
        self._submit_report(report_data, self.CONTRACT_VERSION)

    def _get_latest_data(self) -> tuple[BlockStamp, MemberInfo]:
        latest_blockstamp = self._get_latest_blockstamp()
        logger.debug({'msg': 'Get latest blockstamp.', 'value': latest_blockstamp})

        member_info = self.get_member_info(latest_blockstamp)
        logger.debug({'msg': 'Get current member info.', 'value': member_info})

        # Set member info metrics
        ORACLE_MEMBER_INFO.info(
            {
                'is_report_member': str(member_info.is_report_member),
                'is_submit_member': str(member_info.is_submit_member),
                'is_fast_lane': str(member_info.is_fast_lane),
            }
        )
        ORACLE_MEMBER_LAST_REPORT_REF_SLOT.set(member_info.last_report_ref_slot or 0)

        # Set frame metrics
        FRAME_CURRENT_REF_SLOT.set(member_info.current_frame_ref_slot)
        FRAME_DEADLINE_SLOT.set(member_info.deadline_slot)

        return latest_blockstamp, member_info

    def _encode_data_hash(self, report_data: tuple):
        # The Accounting Oracle and Ejector Bus has same named method to report data
        report_function_name = 'submitReportData'

        report_function_abi = next(x for x in self.report_contract.abi if x.get('name') == report_function_name)

        # First input is ReportData structure
        report_data_abi = report_function_abi['inputs'][0]['components']  # type: ignore

        # Transform abi to string
        report_str_abi = ','.join(map(lambda x: x['type'], report_data_abi))  # type: ignore

        # Transform str abi to tuple, because ReportData is struct
        encoded = encode([f'({report_str_abi})'], [report_data])

        report_hash = self.w3.keccak(encoded)
        return report_hash

    def _send_report_hash(self, blockstamp: ReferenceBlockStamp, report_hash: bytes, consensus_version: int):
        consensus_contract = self._get_consensus_contract(blockstamp)

        tx = consensus_contract.functions.submitReport(blockstamp.ref_slot, report_hash, consensus_version)

        self.w3.transaction.check_and_send_transaction(tx, variables.ACCOUNT)

    def _submit_report(self, report: tuple, contract_version: int):
        tx = self.report_contract.functions.submitReportData(report, contract_version)

        self.w3.transaction.check_and_send_transaction(tx, variables.ACCOUNT)

    def _get_latest_blockstamp(self) -> BlockStamp:
        root = self.w3.cc.get_block_root('head').root
        block_details = self.w3.cc.get_block_details(root)
        bs = build_blockstamp(block_details)
        logger.debug({'msg': 'Fetch latest blockstamp.', 'value': bs})
        ORACLE_SLOT_NUMBER.labels('head').set(bs.slot_number)
        ORACLE_BLOCK_NUMBER.labels('head').set(bs.block_number)
        return bs

    @lru_cache(maxsize=1)
    def _get_slot_delay_before_data_submit(self, blockstamp: BlockStamp) -> int:
        """Returns in slots time to sleep before data report."""
        member = self.get_member_info(blockstamp)
        if member.is_submit_member or variables.ACCOUNT is None:
            return 0

        members, _ = self._get_consensus_contract_members(blockstamp)

        mem_position = members.index(variables.ACCOUNT.address)

        frame_config = self.get_frame_config(blockstamp)
        chain_config = self.get_chain_config(blockstamp)

        converter = Web3Converter(chain_config, frame_config)

        current_frame_number = converter.get_frame_by_slot(blockstamp.slot_number)
        current_position = current_frame_number % len(members)

        sleep_count = mem_position - current_position
        if sleep_count < 0:
            sleep_count += len(members)

        # 1 - is default delay for non submit members.
        total_delay = (1 + sleep_count) * variables.SUBMIT_DATA_DELAY_IN_SLOTS

        logger.info({'msg': 'Calculate slots delay.', 'value': total_delay})
        return total_delay

    @abstractmethod
    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        """Returns ReportData struct with calculated data."""

    @abstractmethod
    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        """Returns if main data already submitted"""

    @abstractmethod
    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        """Returns true if contract is ready for report"""

    @abstractmethod
    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        """Check if collected build output is unexpected and need to be checked manually."""
