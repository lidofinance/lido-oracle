import logging

from web3.types import BlockIdentifier

from src.modules.accounting.types import (
    ReportSimulationPayload,
    ReportSimulationResults,
)
from src.providers.execution.base_interface import ContractInterface

logger = logging.getLogger(__name__)


class AccountingContract(ContractInterface):
    abi_path = './assets/Accounting.json'

    def simulate_oracle_report(
        self,
        payload: ReportSimulationPayload,
        block_identifier: BlockIdentifier = 'latest',
    ) -> ReportSimulationResults:
        """
        Simulates the effects of the `handleOracleReport` function without actually updating the contract state.
        NB: should be calculated off-chain by calling the simulateOracleReport function with the same arguments as the
        handleOracleReport function, while keeping `_withdrawalFinalizationBatches` empty ([]) and `_simulatedShareRate` == 0,
        plugging the returned values to the following formula: `_simulatedShareRate = (postTotalPooledEther * 1e27) / postTotalShares`
        """

        response = self.functions.simulateOracleReport(payload.as_tuple()).call(block_identifier=block_identifier)

        response = ReportSimulationResults(*response)

        logger.info(
            {
                'msg': 'Call `simulateOracleReport({}, {}, {}, {}, {}, {}, {}, {}, {})`.'.format(  # pylint: disable=consider-using-f-string
                    payload.timestamp,
                    payload.time_elapsed,
                    payload.cl_validators,
                    payload.cl_balance,
                    payload.withdrawal_vault_balance,
                    payload.el_rewards_vault_balance,
                    payload.shares_requested_to_burn,
                    payload.withdrawal_finalization_batches,
                    payload.simulated_share_rate,
                ),
                'value': str(response),
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response
