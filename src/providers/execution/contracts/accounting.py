import logging

from eth_typing import ChecksumAddress, HexStr
from web3.types import BlockIdentifier, Wei, StateOverrideParams, StateOverride

from src.modules.accounting.types import ReportValues, ReportResults
from src.providers.execution.base_interface import ContractInterface
from src.types import SlotNumber

logger = logging.getLogger(__name__)


class AccountingContract(ContractInterface):
    abi_path = './assets/Accounting.json'

    def handle_oracle_report(
        self,
        payload: ReportValues,
        accounting_oracle_address: ChecksumAddress,
        ref_slot: SlotNumber,
        block_identifier: BlockIdentifier = 'latest',
    ) -> ReportResults:
        """
        Updates accounting stats, collects EL rewards and distributes collected rewards
        if beacon balance increased, performs withdrawal requests finalization
        periodically called by the AccountingOracle contract

        NB: `_simulatedShareRate` should be calculated off-chain by calling the method with `eth_call` JSON-RPC API
        while passing empty `_withdrawalFinalizationBatches` and `_simulatedShareRate` == 0, plugging the returned values
        to the following formula: `_simulatedShareRate = (postTotalPooledEther * 1e27) / postTotalShares`
        """

        report = (
            payload.timestamp,
            payload.time_elapsed,
            payload.cl_validators,
            payload.cl_balance,
            payload.withdrawal_vault_balance,
            payload.el_rewards_vault_balance,
            payload.shares_requested_to_burn,
            payload.withdrawal_finalization_batches,
            payload.vaults_values,
            payload.vaults_in_out_deltas,
        )

        response = self.functions.handleOracleReport(report).call(
            transaction={'from': accounting_oracle_address},
            block_identifier=block_identifier,
        )

        response = ReportResults(*response)

        logger.info(
            {
                'msg': 'Call `handleOracleReport({}, {}, {}, {}, {}, {}, {}, {}, {}, {})`.'.format(  # pylint: disable=consider-using-f-string
                    payload.timestamp,
                    payload.time_elapsed,
                    payload.cl_validators,
                    payload.cl_balance,
                    payload.withdrawal_vault_balance,
                    payload.el_rewards_vault_balance,
                    payload.shares_requested_to_burn,
                    payload.withdrawal_finalization_batches,
                    payload.vaults_values,
                    payload.vaults_in_out_deltas,
                ),
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response

    def simulate_oracle_report(
        self,
        payload: ReportValues,
        withdrawal_share_rate: int = 0,
        block_identifier: BlockIdentifier = 'latest',
    ) -> ReportResults:
        """
        Simulates the effects of the `handleOracleReport` function without actually updating the contract state.
        NB: should be calculated off-chain by calling the simulateOracleReport function with the same arguments as the
        handleOracleReport function, while keeping `_withdrawalFinalizationBatches` empty ([]) and `_simulatedShareRate` == 0,
        plugging the returned values to the following formula: `_simulatedShareRate = (postTotalPooledEther * 1e27) / postTotalShares`
        """

        report = (
            payload.timestamp,
            payload.time_elapsed,
            payload.cl_validators,
            payload.cl_balance,
            payload.withdrawal_vault_balance,
            payload.el_rewards_vault_balance,
            payload.shares_requested_to_burn,
            payload.withdrawal_finalization_batches,
            payload.vaults_values,
            payload.vaults_in_out_deltas,
        )

        response = self.functions.simulateOracleReport(report, withdrawal_share_rate).call(
            block_identifier=block_identifier
        )

        response = ReportResults(*response)

        logger.info(
            {
                'msg': 'Call `simulateOracleReport({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {})`.'.format(  # pylint: disable=consider-using-f-string
                    payload.timestamp,
                    payload.time_elapsed,
                    payload.cl_validators,
                    payload.cl_balance,
                    payload.withdrawal_vault_balance,
                    payload.el_rewards_vault_balance,
                    payload.shares_requested_to_burn,
                    payload.withdrawal_finalization_batches,
                    payload.vaults_values,
                    payload.vaults_in_out_deltas,
                    withdrawal_share_rate,
                ),
                'value': str(response),
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response
