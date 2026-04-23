import logging

from web3.types import BlockIdentifier, Wei

from modules.oracles.accounting.types import BeaconStat
from providers.execution.base_interface import ContractInterface
from utils.abi import named_tuple_to_dataclass
from utils.cache import global_lru_cache as lru_cache


logger = logging.getLogger(__name__)


class LidoContract(ContractInterface):
    abi_path = './assets/Lido.json'

    @lru_cache(maxsize=1)
    def get_withdrawals_reserve(self, block_identifier: BlockIdentifier = 'latest') -> Wei:
        """
        Return the amount of ETH reserved to satisfy withdrawals, in wei.
        """
        response = self.functions.getWithdrawalsReserve().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `getWithdrawalsReserve()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return Wei(response)

    @lru_cache(maxsize=1)
    def total_supply(self, block_identifier: BlockIdentifier = 'latest') -> Wei:
        """
        return the amount of tokens in existence.

        Always equals to `_getTotalPooledEther()` since token amount
        is pegged to the total amount of Ether controlled by the protocol.
        """
        response = self.functions.totalSupply().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `totalSupply()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
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

        logger.info(
            {
                'msg': 'Call `getBeaconStat()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    def get_deposits_reserve_target(self, block_identifier: BlockIdentifier) -> Wei:
        """
        Returns the amount of ETH reserved for deposits every AO frame.
        """
        response = self.functions.getDepositsReserveTarget().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `getDepositsReserveTarget()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return Wei(response)
