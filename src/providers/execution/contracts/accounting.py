import logging

from eth_typing import ChecksumAddress
from web3.contract.contract import ContractFunction
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.types import ReportValues

logger = logging.getLogger(__name__)


class AccountingContract(ContractInterface):
    abi_path = './assets/Accounting.json'

    def handle_oracle_report(
        self,
        report: ReportValues,
        accounting_oracle_address: ChecksumAddress,
        block_identifier: BlockIdentifier = 'latest',
    ) -> ContractFunction:
        """
        Updates accounting stats, collects EL rewards and distributes collected rewards
        if beacon balance increased, performs withdrawal requests finalization
        periodically called by the AccountingOracle contract
        """

        try:
            return self._handle_oracle_report(
                report,
                accounting_oracle_address,
                block_identifier,
            )
        except ValueError as error:
            logger.warning({
                'msg': 'Request failed. This is expected behaviour from Erigon nodes. Try another request format.',
                'error': repr(error),
            })

            return self._handle_oracle_report(
                report,
                accounting_oracle_address,
                block_identifier,
            )

    def _handle_oracle_report(
        self,
        report: ReportValues,
        accounting_oracle_address: ChecksumAddress,
        block_identifier: BlockIdentifier = 'latest',
    ) -> ContractFunction:
        # Pack the report values into a tuple to match Solidity struct
        report = (
            report.timestamp,
            report.time_elapsed,
            report.cl_validators,
            report.cl_balance,
            report.withdrawal_vault_balance,
            report.el_rewards_vault_balance,
            report.shares_requested_to_burn,
            report.withdrawal_finalization_batches,
            report.vault_values,
            report.net_cash_flows,
        )

        response = self.functions.handleOracleReport(report).call(
            transaction={'from': accounting_oracle_address},
            block_identifier=block_identifier,
        )

        logger.info({
            'msg': f'Call `handleOracleReport({report}).',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response