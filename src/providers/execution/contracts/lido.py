import logging

from eth_typing import ChecksumAddress
from web3.types import Wei, BlockIdentifier

from src.modules.accounting.types import LidoReportRebase
from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class LidoContract(ContractInterface):
    abi_path = './assets/Lido.json'

    def handle_oracle_report(
        self,
        timestamp: int,
        time_elapsed: int,
        validators_count: int,
        cl_balance: Wei,
        withdrawal_vault_balance: Wei,
        el_rewards: Wei,
        shares_to_burn: int,
        accounting_oracle_address: ChecksumAddress,
        block_identifier: BlockIdentifier = 'latest',
    ) -> LidoReportRebase:
        """
        Updates accounting stats, collects EL rewards and distributes collected rewards
        if beacon balance increased, performs withdrawal requests finalization
        periodically called by the AccountingOracle contract

        NB: `_simulatedShareRate` should be calculated off-chain by calling the method with `eth_call` JSON-RPC API
        while passing empty `_withdrawalFinalizationBatches` and `_simulatedShareRate` == 0, plugging the returned values
        to the following formula: `_simulatedShareRate = (postTotalPooledEther * 1e27) / postTotalShares`
        """
        response = self.functions.handleOracleReport(
            timestamp,
            time_elapsed,
            validators_count,
            cl_balance,
            withdrawal_vault_balance,
            el_rewards,
            shares_to_burn,
            [],
            0,
        ).call(
            transaction={'from': accounting_oracle_address},
            block_identifier=block_identifier,
        )

        response = LidoReportRebase(*response)

        logger.info({
            'msg': 'Call `handleOracleReport({}, {}, {}, {}, {}, {}, {}, {}, {})`.'.format(  # pylint: disable=consider-using-f-string
                timestamp,
                time_elapsed,
                validators_count,
                cl_balance,
                withdrawal_vault_balance,
                el_rewards,
                shares_to_burn,
                [],
                0,
            ),
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

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
        })
        return Wei(response)

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
        })
        return Wei(response)