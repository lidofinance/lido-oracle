import logging

from web3.types import BlockIdentifier, Wei

from src.modules.oracles.accounting.types import BalanceStats, BeaconStat
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache


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

    def get_contract_version(self, block_identifier: BlockIdentifier) -> int:
        response = self.functions.getContractVersion().call(block_identifier=block_identifier)
        logger.info(
            {
                'msg': 'Call `getContractVersion()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return int(response)

    def get_balance_stats(self, block_identifier: BlockIdentifier) -> BalanceStats:
        """Lido v4+: balance/deposit accounting state. See
        https://github.com/lidofinance/core/blob/c2872dc75eae824a9959bb4a5f21caef792de1a1/contracts/0.4.24/Lido.sol#L734

        `deposited_since_last_report` (`depositedPostReport`) only resets when a report is
        actually processed on-chain, so diffing two readings taken within the same (still
        unsettled) reporting frame gives the deposits made strictly between those two blocks.

        Do not use `deposited_for_current_report` for that purpose: it is re-derived against
        the *current* HashConsensus frame on every read, so two readings taken within the same
        open frame always come out equal to each other — diffing them always yields 0.
        """
        response = self.functions.getBalanceStats().call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, BalanceStats)

        logger.info(
            {
                'msg': 'Call `getBalanceStats()`.',
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
