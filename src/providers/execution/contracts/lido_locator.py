import logging
from src.utils.cache import global_lru_cache as lru_cache

from eth_typing import ChecksumAddress
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class LidoLocatorContract(ContractInterface):
    abi_path = './assets/LidoLocator.json'

    @lru_cache(maxsize=1)
    def lido(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.lido().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `lido()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def accounting(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.accounting().call(block_identifier=block_identifier)

        logger.debug(
            {
                'msg': 'Call `accounting()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    @lru_cache(maxsize=1)
    def accounting_oracle(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.accountingOracle().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `accountingOracle()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def staking_router(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.stakingRouter().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `stakingRouter()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def validator_exit_bus_oracle(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.validatorsExitBusOracle().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `validatorsExitBusOracle()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def withdrawal_queue(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.withdrawalQueue().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `withdrawalQueue()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def oracle_report_sanity_checker(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.oracleReportSanityChecker().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `oracleReportSanityChecker()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def oracle_daemon_config(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.oracleDaemonConfig().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `oracleDaemonConfig()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def burner(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.burner().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `burner()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def withdrawal_vault(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.withdrawalVault().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `withdrawalVault()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def el_rewards_vault(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.elRewardsVault().call(block_identifier=block_identifier)

        logger.debug({
            'msg': 'Call `elRewardsVault()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def vault_hub(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.vaultHub().call(block_identifier=block_identifier)

        logger.debug(
            {
                'msg': 'Call `vaultHub()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    @lru_cache(maxsize=1)
    def lazy_oracle(self, block_identifier: BlockIdentifier = 'latest') -> ChecksumAddress:
        response = self.functions.lazyOracle().call(block_identifier=block_identifier)

        logger.debug(
            {
                'msg': 'Call `lazyOracle()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response
