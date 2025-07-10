import logging

from web3.types import Wei, BlockIdentifier

from src.modules.accounting.types import BeaconStat
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


class LidoContract(ContractInterface):
    abi_path = './assets/Lido.json'

    @lru_cache(maxsize=1)
    def get_buffered_ether(self, block_identifier: BlockIdentifier = 'latest') -> Wei:
        """
        Get the amount of Ether temporary buffered on this contract balance
        Buffered balance is kept on the contract from the moment the funds are received from user
        until the moment they are actually sent to the official Deposit contract.
        return amount of buffered funds in wei
        """
        response = self.functions.getBufferedEther().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `getBufferedEther()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return Wei(response)

    @lru_cache(maxsize=1)
    def total_supply(self, block_identifier: BlockIdentifier = 'latest') -> Wei:
        """
        return the amount of tokens in existence.

        Always equals to `_getTotalPooledEther()` since token amount
        is pegged to the total amount of Ether controlled by the protocol.
        """
        response = self.functions.totalSupply().call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `totalSupply()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return Wei(response)

    @lru_cache(maxsize=1)
    def get_beacon_stat(self, block_identifier: BlockIdentifier = 'latest') -> BeaconStat:
        """
        Returns the key values related to Consensus Layer side of the contract. It historically contains beacon

        depositedValidators - number of deposited validators from Lido contract side
        beaconValidators - number of Lido validators visible on Consensus Layer, reported by oracle
        beaconBalance - total amount of ether on the Consensus Layer side (sum of all the balances of Lido validators)
        """
        response = self.functions.getBeaconStat().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, BeaconStat)

        logger.info({
            'msg': 'Call `getBeaconStat()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response
