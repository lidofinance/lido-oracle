import logging

from eth_typing import ChecksumAddress
from web3.contract.contract import ContractFunction
from web3.types import BlockIdentifier

from src.modules.accounting.types import ReportValues, CalculatedReportResults
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass

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

    def simulate_oracle_report(
        self,
        report: ReportValues,
        withdrawal_share_rate: int = 0,
        block_identifier: BlockIdentifier = 'latest',
    ) -> CalculatedReportResults:
        """
        Simulates the effects of the `handleOracleReport` function without actually updating the contract state.
        """

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

        response = self.functions.simulateOracleReport(report, withdrawal_share_rate).call(
            block_identifier=block_identifier
        )
        response = named_tuple_to_dataclass(response, CalculatedReportResults)

        logger.info({
            'msg': f'Call `simulateOracleReport({report}, {withdrawal_share_rate}).',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response
