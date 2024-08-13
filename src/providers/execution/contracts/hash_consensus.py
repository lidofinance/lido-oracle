import logging
from src.types import SlotNumber
from src.utils.cache import global_lru_cache as lru_cache

from eth_typing import ChecksumAddress
from web3.contract.contract import ContractFunction
from web3.types import BlockIdentifier

from src.modules.submodules.types import ChainConfig, CurrentFrame, FrameConfig
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass

logger = logging.getLogger(__name__)


class HashConsensusContract(ContractInterface):
    abi_path = './assets/HashConsensus.json'

    @lru_cache(maxsize=1)
    def get_members(self, block_identifier: BlockIdentifier = 'latest') -> tuple[list[ChecksumAddress], list[int]]:
        """
        Returns all current members, together with the last reference slot each member
        submitted a report for.
        """
        response = self.functions.getMembers().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getMembers()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response

    @lru_cache(maxsize=1)
    def get_chain_config(self, block_identifier: BlockIdentifier = 'latest') -> ChainConfig:
        """
        Returns the immutable chain parameters required to calculate epoch and slot
        given a timestamp.
        """
        response = self.functions.getChainConfig().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, ChainConfig)

        logger.debug({
            'msg': 'Call `getChainConfig()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response

    @lru_cache(maxsize=1)
    def get_current_frame(self, block_identifier: BlockIdentifier = 'latest') -> CurrentFrame:
        """
        Returns the current reporting frame.

        ref_slot The frame's reference slot: if the data the consensus is being reached upon
                 includes or depends on any onchain state, this state should be queried at the
                 reference slot. If the slot contains a block, the state should include all changes
                 from that block.

        report_processing_deadline_slot: The last slot at which the report can be processed
                                         by the report processor contract.
        """
        response = self.functions.getCurrentFrame().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, CurrentFrame)

        logger.info({
            'msg': 'Call `getCurrentFrame()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response

    @lru_cache(maxsize=1)
    def get_initial_ref_slot(self, block_identifier: BlockIdentifier = 'latest') -> SlotNumber:
        """
        Returns the earliest possible reference slot,
        i.e. the reference slot of the reporting frame with zero index.
        """
        response = self.functions.getInitialRefSlot().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getInitialRefSlot()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response

    @lru_cache(maxsize=1)
    def get_frame_config(self, block_identifier: BlockIdentifier = 'latest') -> FrameConfig:
        """
        Returns the time-related configuration.

        initialEpoch Epoch of the frame with zero index.
        epochsPerFrame Length of a frame in epochs.
        fastLaneLengthSlots Length of the fast lane interval in slots; see `getIsFastLaneMember`.
        """
        response = self.functions.getFrameConfig().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, FrameConfig)

        logger.debug({
            'msg': 'Call `getFrameConfig()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response

    @lru_cache(maxsize=1)
    def get_consensus_state_for_member(self, address: ChecksumAddress, block_identifier: BlockIdentifier = 'latest') -> tuple:
        """
        Returns the extended information related to an oracle committee member with the
        given address and the current consensus state. Provides all the information needed for
        an oracle daemon to decide if it needs to submit a report.
        """
        response = self.functions.getConsensusStateForMember(address).call(block_identifier=block_identifier)

        logger.info({
            'msg': f'Call `getConsensusStateForMember({address})`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response

    def submit_report(self, ref_slot: int, report_hash: bytes, consensus_version: int) -> ContractFunction:
        """
        Used by oracle members to submit hash of the data calculated for the given reference slot.

        ref_slot: The reference slot the data was calculated for. Reverts if doesn't match
                  the current reference slot.

        report_hash: of the data calculated for the given reference slot.

        consensus_version:  Version of the oracle consensus rules. Reverts if doesn't
                            match the version returned by the currently set consensus report processor,
                            or zero if no report processor is set.
        """
        tx = self.functions.submitReport(ref_slot, report_hash, consensus_version)

        logger.info({
            'msg': 'Build `submitReport({}, {}, {})`.'.format(  # pylint: disable=consider-using-f-string
                ref_slot,
                report_hash.hex(),
                consensus_version,
            ),
        })

        return tx
