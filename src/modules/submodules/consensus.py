import logging
from abc import ABC, abstractmethod
from time import sleep
from typing import cast

from eth_abi import encode
from hexbytes import HexBytes
from web3.exceptions import ContractCustomError

from src import variables
from src.metrics.prometheus.basic import (
    ACCOUNT_BALANCE,
    GENESIS_TIME,
    ORACLE_BLOCK_NUMBER,
    ORACLE_SLOT_NUMBER,
)
from src.metrics.prometheus.business import (
    FRAME_CURRENT_REF_SLOT,
    FRAME_DEADLINE_SLOT,
    ORACLE_MEMBER_INFO,
    ORACLE_MEMBER_LAST_REPORT_REF_SLOT,
)
from src.modules.submodules.exceptions import (
    ContractVersionMismatch,
    IncompatibleOracleVersion,
    IsNotMemberException,
)
from src.modules.submodules.types import (
    ZERO_HASH,
    ChainConfig,
    ConsensusGenesisConfig,
    CurrentFrame,
    FrameConfig,
    MemberInfo,
)
from src.providers.execution.contracts.base_oracle import BaseOracleContract
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.types import BlockStamp, FrameNumber, ReferenceBlockStamp, SlotNumber
from src.utils.blockstamp import build_blockstamp
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.slot import get_reference_blockstamp
from src.utils.web3converter import Web3Converter
from src.web3py.types import Web3

logger = logging.getLogger(__name__)

# Initial epoch is in the future. Revert signature: '0xcd0883ea'
InitialEpochIsYetToArriveRevert = Web3.to_hex(primitive=Web3.keccak(text="InitialEpochIsYetToArrive()")[:4])


class ConsensusModule(ABC):
    """
    Module that works with Hash Consensus Contract.

    Do next things:
    - Calculate report blockstamp if contract is reportable
    - Calculates and sends report hash
    - Decides in what order Oracles should report

    report_contract should contain getConsensusContract method.
    """
    report_contract: BaseOracleContract

    COMPATIBLE_CONTRACT_VERSION: int
    COMPATIBLE_CONSENSUS_VERSION: int

    def __init__(self, w3: Web3):
        self.w3 = w3

        if getattr(self, "report_contract", None) is None:
            raise NotImplementedError('report_contract attribute should be set.')

        for var in ('COMPATIBLE_CONTRACT_VERSION', 'COMPATIBLE_CONSENSUS_VERSION'):
            if getattr(self, var, None) is None:
                raise NotImplementedError(f'{var} attribute should be set.')

    def check_contract_configs(self):
        root = self.w3.cc.get_block_root('head').root
        block_details = self.w3.cc.get_block_details(root)
        bs = build_blockstamp(block_details)

        config = self.get_chain_config(bs)
        cc_config = self.w3.cc.get_config_spec()
        genesis_time = self.get_cc_genesis_config().genesis_time
        GENESIS_TIME.set(genesis_time)
        if any(
            (
                config.genesis_time != genesis_time,
                config.seconds_per_slot != cc_config.SECONDS_PER_SLOT,
                config.slots_per_epoch != cc_config.SLOTS_PER_EPOCH,
            )
        ):
            raise ValueError('Contract chain config is not compatible with Beacon chain.\n'
                             f'Contract config: {config}\n'
                             f'Beacon chain config: {genesis_time=}, {cc_config.SECONDS_PER_SLOT=}, {cc_config.SLOTS_PER_EPOCH=}')

    # ----- Web3 data requests -----
    @lru_cache(maxsize=1)
    def _get_consensus_contract(self, blockstamp: BlockStamp) -> HashConsensusContract:
        return cast(HashConsensusContract, self.w3.eth.contract(
            address=self.report_contract.get_consensus_contract(blockstamp.block_hash),
            ContractFactoryClass=HashConsensusContract,
            decode_tuples=True,
        ))

    def _get_consensus_contract_members(self, blockstamp: BlockStamp):
        consensus_contract = self._get_consensus_contract(blockstamp)
        return consensus_contract.get_members(blockstamp.block_hash)

    @lru_cache(maxsize=1)
    def get_consensus_version(self, blockstamp: BlockStamp):
        return self.report_contract.get_consensus_version(blockstamp.block_hash)

    @lru_cache(maxsize=1)
    def get_chain_config(self, blockstamp: BlockStamp) -> ChainConfig:
        consensus_contract = self._get_consensus_contract(blockstamp)
        return consensus_contract.get_chain_config(blockstamp.block_hash)

    @lru_cache(maxsize=1)
    def get_cc_genesis_config(self) -> ConsensusGenesisConfig:
        genesis = self.w3.cc.get_genesis()
        return ConsensusGenesisConfig(genesis_time=genesis.genesis_time)

    @lru_cache(maxsize=1)
    def get_initial_or_current_frame(self, blockstamp: BlockStamp) -> CurrentFrame:
        consensus_contract = self._get_consensus_contract(blockstamp)

        try:
            return consensus_contract.get_current_frame(blockstamp.block_hash)
        except ContractCustomError as revert:
            if revert.data != InitialEpochIsYetToArriveRevert:
                raise revert

        converter = self._get_web3_converter(blockstamp)

        # If initial epoch is not yet arrived then current frame is the first frame
        # ref_slot is last slot of previous frame
        return CurrentFrame(
            ref_slot=converter.get_frame_last_slot(FrameNumber(0 - 1)),
            report_processing_deadline_slot=converter.get_frame_last_slot(FrameNumber(0)),
        )

    @lru_cache(maxsize=1)
    def get_initial_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        consensus_contract = self._get_consensus_contract(blockstamp)
        return consensus_contract.get_initial_ref_slot(blockstamp.block_hash)

    @lru_cache(maxsize=1)
    def get_frame_config(self, blockstamp: BlockStamp) -> FrameConfig:
        consensus_contract = self._get_consensus_contract(blockstamp)
        return consensus_contract.get_frame_config(blockstamp.block_hash)

    @lru_cache(maxsize=1)
    def get_member_info(self, blockstamp: BlockStamp) -> MemberInfo:
        consensus_contract = self._get_consensus_contract(blockstamp)

        # Defaults for dry mode
        current_frame = self.get_initial_or_current_frame(blockstamp)
        frame_config = self.get_frame_config(blockstamp)
        is_member = is_submit_member = is_fast_lane = True
        last_member_report_ref_slot = SlotNumber(0)
        current_frame_consensus_report = current_frame_member_report = ZERO_HASH

        if variables.ACCOUNT:
            ACCOUNT_BALANCE.labels(str(variables.ACCOUNT.address)).set(
                self.w3.eth.get_balance(variables.ACCOUNT.address)
            )

            try:
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
                ) = consensus_contract.get_consensus_state_for_member(
                    variables.ACCOUNT.address,
                    blockstamp.block_hash,
                )
            except ContractCustomError as revert:
                if revert.data != InitialEpochIsYetToArriveRevert:
                    raise revert

            is_submit_member = self.report_contract.has_role(
                self.report_contract.submit_data_role(blockstamp.block_hash),
                variables.ACCOUNT.address,
                blockstamp.block_hash
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
            last_report_ref_slot=last_member_report_ref_slot,
            fast_lane_length_slot=frame_config.fast_lane_length_slots,
            current_frame_consensus_report=current_frame_consensus_report,
            current_frame_ref_slot=current_frame.ref_slot,
            current_frame_member_report=current_frame_member_report,
            deadline_slot=current_frame.report_processing_deadline_slot,
        )
        logger.debug({'msg': 'Fetch member info.', 'value': mi})

        return mi

    # ----- Calculation reference slot for report -----
    def get_blockstamp_for_report(self, last_finalized_blockstamp: BlockStamp) -> ReferenceBlockStamp | None:
        """
        Get blockstamp that should be used to build and send report for current frame.
        Returns:
            Non-missed reference slot blockstamp in case contract is reportable.
        """
        latest_blockstamp = self._get_latest_blockstamp()

        # Check if contract is currently reportable
        if not self.is_contract_reportable(latest_blockstamp):
            logger.info({'msg': 'Contract is not reportable.'})
            return None

        member_info = self.get_member_info(latest_blockstamp)
        logger.info({'msg': 'Fetch member info.', 'value': member_info})

        # Check if current slot is higher than member slot
        if last_finalized_blockstamp.slot_number < member_info.current_frame_ref_slot:
            logger.info({'msg': 'Reference slot is not yet finalized.'})
            return None

        # Check latest block didn't miss the deadline.
        if latest_blockstamp.slot_number >= member_info.deadline_slot:
            logger.info({'msg': 'Deadline missed.'})
            return None

        converter = self._get_web3_converter(last_finalized_blockstamp)

        bs = get_reference_blockstamp(
            cc=self.w3.cc,
            ref_slot=member_info.current_frame_ref_slot,
            ref_epoch=converter.get_epoch_by_slot(member_info.current_frame_ref_slot),
            last_finalized_slot_number=last_finalized_blockstamp.slot_number,
        )
        logger.info({'msg': 'Calculate blockstamp for report.', 'value': bs})

        return bs

    def _check_compatability(self, blockstamp: BlockStamp) -> bool:
        """
        Check if Oracle can process report on reference blockstamp.

        Returns if Oracle can proceed with calculations or should spin up waiting for a protocol upgrade
        """
        contract_version = self.report_contract.get_contract_version(blockstamp.block_hash)
        consensus_version = self.report_contract.get_consensus_version(blockstamp.block_hash)

        compatibility = contract_version <= self.COMPATIBLE_CONTRACT_VERSION and consensus_version <= self.COMPATIBLE_CONSENSUS_VERSION

        if not compatibility:
            raise IncompatibleOracleVersion(
                f'Incompatible Oracle version. Block tag: {repr(blockstamp.block_hash)}. '
                f'Expected Contract version: {self.COMPATIBLE_CONTRACT_VERSION}. '
                f'Expected Consensus versions: {self.COMPATIBLE_CONSENSUS_VERSION}, '
                f'Got ({contract_version}, {consensus_version})'
            )

        contract_version_latest = self.report_contract.get_contract_version('latest')
        consensus_version_latest = self.report_contract.get_consensus_version('latest')

        if contract_version != contract_version_latest or consensus_version != consensus_version_latest:
            raise ContractVersionMismatch(
                'The Oracle can\'t process the report on the reference blockstamp. '
                f'The Contract or Consensus versions differ between the latest and {blockstamp.block_hash}, '
                'further processing report can lead to unexpected behavior.'
            )
        ready_to_report = contract_version == self.COMPATIBLE_CONTRACT_VERSION and consensus_version == self.COMPATIBLE_CONSENSUS_VERSION
        if not ready_to_report:
            logger.info({
                'msg': 'Oracle waits for contacts to be updated.',
                'expected_contract_version': self.COMPATIBLE_CONTRACT_VERSION,
                'expected_consensus_version': self.COMPATIBLE_CONSENSUS_VERSION,
                'actual_contract_version': contract_version_latest,
                'actual_consensus_version': consensus_version_latest,
            })
        return ready_to_report

    # ----- Working with report -----
    def process_report(self, blockstamp: ReferenceBlockStamp) -> None:
        """Builds and sends report for current frame with provided blockstamp."""
        report_data = self.build_report(blockstamp)
        logger.info({'msg': 'Build report.', 'value': report_data})

        report_hash = self._encode_data_hash(report_data)
        logger.info({'msg': 'Calculate report hash.', 'value': repr(report_hash)})
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

        if not member_info.is_report_member:
            logger.info({'msg': 'Account can`t submit report hash.'})
            return None

        if HexBytes(member_info.current_frame_member_report) == report_hash:
            logger.info({'msg': 'Account already submitted provided hash.'})
            return None

        if not member_info.is_fast_lane:
            # Check if current slot is newer than (member slot + slots_delay)
            if latest_blockstamp.slot_number < member_info.current_frame_ref_slot + member_info.fast_lane_length_slot:
                logger.info({'msg': f'Member is not in fast lane, so report will be postponed '
                                    f'for [{member_info.fast_lane_length_slot}] slots.'})
                return None

            if HexBytes(member_info.current_frame_consensus_report) == report_hash:
                logger.info({'msg': 'Consensus reached with provided hash.'})
                return None
        logger.info({'msg': f'Send report hash. Consensus version: [{self.COMPATIBLE_CONSENSUS_VERSION}]'})
        self._send_report_hash(blockstamp, report_hash, self.COMPATIBLE_CONSENSUS_VERSION)
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
                'consensus_report_hash': HexBytes(member_info.current_frame_consensus_report).hex(),
                'report_hash': report_hash.hex(),
            })
            return

        if self.is_main_data_submitted(latest_blockstamp):
            logger.info({'msg': 'Main data already submitted.'})
            return

        slots_to_sleep = self._get_slot_delay_before_data_submit(latest_blockstamp)
        if slots_to_sleep:
            chain_configs = self.get_chain_config(blockstamp)

            logger.info({'msg': f'Sleep for {slots_to_sleep} slots before sending data.'})
            for _ in range(slots_to_sleep):
                sleep(chain_configs.seconds_per_slot)

                latest_blockstamp, member_info = self._get_latest_data()
                if self.is_main_data_submitted(latest_blockstamp):
                    logger.info({'msg': 'Main data already submitted.'})
                    return

        if self.is_main_data_submitted(latest_blockstamp):
            logger.info({'msg': 'Main data already submitted.'})
            return
        logger.info({'msg': f'Send report data. Contract version: [{self.COMPATIBLE_CONTRACT_VERSION}]'})
        # If data already submitted transaction will be locally reverted, no need to check status manually
        self._submit_report(report_data, self.COMPATIBLE_CONTRACT_VERSION)

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

    def _encode_data_hash(self, report_data: tuple) -> HexBytes:
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

        tx = consensus_contract.submit_report(blockstamp.ref_slot, report_hash, consensus_version)

        self.w3.transaction.check_and_send_transaction(tx, variables.ACCOUNT)

    def _submit_report(self, report: tuple, contract_version: int):
        tx = self.report_contract.submit_report_data(report, contract_version)

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
        """
        Fast lane offchain implementation for report data
        If the member was added in the current frame,
        the result of _get_slot_delay_before_data_submit may be inconsistent for different latest blocks, but it's ok.

        Do not use ref blockstamp here because new oracle member will fail is_member check,
        because it wasn't in quorum on ref_slot.

        Returns in slots time to sleep before data report.
        """
        member = self.get_member_info(blockstamp)
        if member.is_submit_member or variables.ACCOUNT is None:
            return 0

        members, _ = self._get_consensus_contract_members(blockstamp)

        mem_position = members.index(variables.ACCOUNT.address)

        converter = self._get_web3_converter(blockstamp)

        current_frame_number = converter.get_frame_by_slot(blockstamp.slot_number)
        current_position = current_frame_number % len(members)

        sleep_count = mem_position - current_position
        if sleep_count < 0:
            sleep_count += len(members)

        # 1 - is default delay for non submit members.
        total_delay = (1 + sleep_count) * variables.SUBMIT_DATA_DELAY_IN_SLOTS

        logger.info({'msg': 'Calculate slots delay.', 'value': total_delay})
        return total_delay

    def _get_web3_converter(self, blockstamp: BlockStamp) -> Web3Converter:
        chain_config = self.get_chain_config(blockstamp)
        frame_config = self.get_frame_config(blockstamp)
        return Web3Converter(chain_config, frame_config)

    @lru_cache(maxsize=1)
    def get_frame_number_by_slot(self, blockstamp: ReferenceBlockStamp) -> FrameNumber:
        converter = self._get_web3_converter(blockstamp)
        frame_number = converter.get_frame_by_slot(blockstamp.ref_slot)
        logger.info({
            "msg": "Get current frame from blockstamp",
            "frame": frame_number,
            "slot": blockstamp.ref_slot
        })
        return FrameNumber(frame_number)

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
