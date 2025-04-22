import logging
from src.utils.cache import global_lru_cache as lru_cache

from eth_typing import ChecksumAddress, Hash32
from web3.contract.contract import ContractFunction
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.types import SlotNumber


logger = logging.getLogger(__name__)


class BaseOracleContract(ContractInterface):

    @lru_cache(maxsize=1)
    def get_consensus_contract(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        """
        Returns the address of the HashConsensus contract.
        """
        response = self.functions.getConsensusContract().call(block_identifier=block_identifier)
        logger.debug({
            'msg': 'Call `getConsensusContract()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def submit_data_role(self, block_identifier: BlockIdentifier = 'latest') -> Hash32:
        """
        An ACL role granting the permission to submit the data for a committee report.
        """
        response = self.functions.SUBMIT_DATA_ROLE().call(block_identifier=block_identifier)
        logger.info({
            'msg': 'Call `SUBMIT_DATA_ROLE()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def has_role(self, role: Hash32, address: ChecksumAddress, block_identifier: BlockIdentifier = 'latest') -> bool:
        """
        Returns `true` if `account` has been granted `role`.
        """
        response = self.functions.hasRole(role, address).call(block_identifier=block_identifier)
        logger.info({
            'msg': f'Call `hasRole({role.hex()}, {address})`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def get_contract_version(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Returns the current contract version.
        """
        response = self.functions.getContractVersion().call(block_identifier=block_identifier)
        logger.debug({
            'msg': 'Call `getContractVersion().',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def get_consensus_version(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Returns the current consensus version expected by the oracle contract.
        Consensus version must change every time consensus rules change, meaning that
        an oracle looking at the same reference slot would calculate a different hash.
        """
        response = self.functions.getConsensusVersion().call(block_identifier=block_identifier)
        logger.debug({
            'msg': 'Call `getConsensusVersion().',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    def submit_report_data(self, report: tuple, contract_version: int) -> ContractFunction:
        """
        Submits report data for processing.
        data. See the `ReportData` structure's docs for details.
        contractVersion Expected version of the oracle contract.

        Reverts if:
        - The caller is not a member of the oracle committee and doesn't possess the SUBMIT_DATA_ROLE.
        - The provided contract version is different from the current one.
        - The provided consensus version is different from the expected one.
        - The provided reference slot differs from the current consensus frame's one.
        - The processing deadline for the current consensus frame is missed.
        - The keccak256 hash of the ABI-encoded data is different from the last hash provided by the hash consensus contract.
        - The provided data doesn't meet safety checks.
        """
        tx = self.functions.submitReportData(report, contract_version)
        logger.info({
            'msg': f'Build `submitReport({report}, {contract_version}) tx.'
        })
        return tx

    @lru_cache(maxsize=1)
    def get_last_processing_ref_slot(self, block_identifier: BlockIdentifier = 'latest') -> SlotNumber:
        """
        Returns the last reference slot for which processing of the report was started.
        HashConsensus won't submit reports for any slot less than or equal to this slot.
        """
        response = self.functions.getLastProcessingRefSlot().call(block_identifier=block_identifier)
        logger.info({
            'msg': 'Call `getLastProcessingRefSlot().',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return SlotNumber(response)
