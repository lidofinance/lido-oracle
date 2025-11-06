import logging

from hexbytes import HexBytes
from web3 import Web3
from web3.types import BlockIdentifier

from src import variables
from src.modules.accounting.types import (
    OnChainIpfsVaultReportData,
    ValidatorStage,
    ValidatorStatus,
    VaultInfo,
)
from src.providers.execution.base_interface import ContractInterface
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


class LazyOracleContract(ContractInterface):
    abi_path = './assets/LazyOracle.json'

    @lru_cache(maxsize=1)
    def get_vaults_count(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Returns the number of vaults attached to the VaultHub.
        """
        response = self.functions.vaultsCount.call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `vaultsCount().',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return response

    def get_latest_report_data(self, block_identifier: BlockIdentifier = 'latest') -> OnChainIpfsVaultReportData:
        response = self.functions.latestReportData.call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `latestReportData()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        response = named_tuple_to_dataclass(response, OnChainIpfsVaultReportData)
        return response

    def get_vaults(self, offset: int, limit: int, block_identifier: BlockIdentifier = 'latest') -> list[VaultInfo]:
        """
        Returns the Vaults
        """
        response = self.functions.batchVaultsInfo(offset, limit).call(block_identifier=block_identifier)

        out: list[VaultInfo] = []
        for vault in response:
            out.append(VaultInfo(
                vault=vault.vault,
                aggregated_balance=vault.aggregatedBalance,
                in_out_delta=vault.inOutDelta,
                withdrawal_credentials=Web3.to_hex(vault.withdrawalCredentials),
                liability_shares=vault.liabilityShares,
                max_liability_shares=vault.maxLiabilityShares,
                mintable_st_eth=vault.mintableStETH,
                share_limit=vault.shareLimit,
                reserve_ratio_bp=vault.reserveRatioBP,
                forced_rebalance_threshold_bp=vault.forcedRebalanceThresholdBP,
                infra_fee_bp=vault.infraFeeBP,
                liquidity_fee_bp=vault.liquidityFeeBP,
                reservation_fee_bp=vault.reservationFeeBP,
                pending_disconnect=vault.pendingDisconnect,
            ))

        logger.info({
            'msg': f'Call `batchVaultsInfo({offset}, {limit}).',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })

        return out

    def get_all_vaults(self, block_identifier: BlockIdentifier = 'latest') -> list[VaultInfo]:
        """
        Fetch all vaults using pagination via `get_vaults` in batches of `page_size`.
        """
        vaults: list[VaultInfo] = []
        offset = 0

        total_count = self.get_vaults_count(block_identifier)
        if total_count == 0:
            return []

        while offset < total_count:
            batch = self.get_vaults(
                block_identifier=block_identifier, offset=offset, limit=variables.VAULT_PAGINATION_LIMIT
            )
            if not batch:
                break
            vaults.extend(batch)
            offset += variables.VAULT_PAGINATION_LIMIT

        return vaults

    def get_validator_statuses(
        self,
        pubkeys: list[str],
        batch_size: int = variables.VAULT_VALIDATOR_STAGES_BATCH_SIZE,
        block_identifier: BlockIdentifier = 'latest',
    ) -> dict[str, ValidatorStatus]:
        """
        Fetch validator statuses for a list of pubkeys, batching requests for efficiency.
        """
        out: dict[str, ValidatorStatus] = {}

        for i in range(0, len(pubkeys), batch_size):
            batch = list(map(HexBytes, pubkeys[i : i + batch_size]))
            response = self.functions.batchValidatorStatuses(batch).call(block_identifier=block_identifier)

            logger.debug({
                'msg': 'Call `batchValidatorStatuses()`.',
                'count': len(batch),
                'block_identifier': repr(block_identifier),
                'to': self.address,
            })

            out.update({
                pk.to_0x_hex(): ValidatorStatus(
                    stage=ValidatorStage(status.stage),
                    staking_vault=status.stakingVault,
                    node_operator=status.nodeOperator,
                )
                for pk, status in zip(batch, response)
            })

        return out
