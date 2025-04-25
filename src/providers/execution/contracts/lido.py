import logging

from eth_typing import ChecksumAddress, HexStr
from web3 import Web3
from web3.exceptions import Web3RPCError
from web3.types import Wei, BlockIdentifier, StateOverride, StateOverrideParams

from src.types import SlotNumber
from src.modules.accounting.types import LidoReportRebase, BeaconStat
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache

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
        ref_slot: SlotNumber,
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
        hex_ref_slot = HexStr('0x' + ref_slot.to_bytes(32).hex())

        try:
            return self._handle_oracle_report(
                timestamp,
                time_elapsed,
                validators_count,
                cl_balance,
                withdrawal_vault_balance,
                el_rewards,
                shares_to_burn,
                accounting_oracle_address,
                hex_ref_slot,
                block_identifier,
            )
        except Web3RPCError as error:
            # {'code': -32602, 'message': 'invalid argument 2: hex number with leading zero digits'}
            logger.warning({
                'msg': 'Request failed. This is expected behaviour from Erigon nodes. Try another request format.',
                'error': repr(error),
            })
            hex_ref_slot = HexStr(hex(ref_slot))
            return self._handle_oracle_report(
                timestamp,
                time_elapsed,
                validators_count,
                cl_balance,
                withdrawal_vault_balance,
                el_rewards,
                shares_to_burn,
                accounting_oracle_address,
                hex_ref_slot,
                block_identifier,
            )

    def _handle_oracle_report(
        self,
        timestamp: int,
        time_elapsed: int,
        validators_count: int,
        cl_balance: Wei,
        withdrawal_vault_balance: Wei,
        el_rewards: Wei,
        shares_to_burn: int,
        accounting_oracle_address: ChecksumAddress,
        ref_slot: HexStr,
        block_identifier: BlockIdentifier = 'latest',
    ) -> LidoReportRebase:
        state_override: StateOverride = {
            accounting_oracle_address: StateOverrideParams(
                # Fix: insufficient funds for gas * price + value
                balance=Wei(100 * 10**18),
                # Fix: Sanity checker uses `lastProcessingRefSlot` from AccountingOracle to
                # properly process negative rebase sanity checks. Since current simulation skips call to AO,
                # setting up `lastProcessingRefSlot` directly.
                stateDiff={
                    Web3.to_hex(primitive=self.w3.keccak(text="lido.BaseOracle.lastProcessingRefSlot")): ref_slot,
                }
            ),
        }

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
            state_override=state_override,
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
            'state_override': repr(state_override),
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

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
