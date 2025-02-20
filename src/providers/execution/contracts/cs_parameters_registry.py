import logging
from dataclasses import dataclass

from web3.types import BlockIdentifier

from src.constants import UINT256_MAX, TOTAL_BASIS_POINTS
from src.providers.execution.base_interface import ContractInterface

logger = logging.getLogger(__name__)


@dataclass
class PerformanceCoefficients:
    attestations_weight: int = 54
    blocks_weight: int = 8
    sync_weight: int = 2

    def calc_performance(self, att_aggr, prop_aggr, sync_aggr) -> float:
        base = self.attestations_weight
        performance = att_aggr.perf * self.attestations_weight

        if prop_aggr:
            base += self.blocks_weight
            performance += prop_aggr.perf * self.blocks_weight

        if sync_aggr:
            base += self.sync_weight
            performance += sync_aggr.perf * self.sync_weight

        performance /= base

        if performance > 1:
            raise ValueError(f"Invalid performance: {performance=}")

        return performance


@dataclass
class RewardShare:
    key_pivots: list[int]
    reward_shares: list[int]

    def get_for(self, key_number: int) -> float:
        for i, pivot_number in enumerate(self.key_pivots + [UINT256_MAX]):
            if key_number <= pivot_number:
                return self.reward_shares[i] / TOTAL_BASIS_POINTS
        raise ValueError(f"Key number {key_number} is out of {self.key_pivots}")


@dataclass
class PerformanceLeeway:
    key_pivots: list[int]
    performance_leeways: list[int]

    def get_for(self, key_number: int) -> float:
        for i, pivot_number in enumerate(self.key_pivots + [UINT256_MAX]):
            if key_number <= pivot_number:
                return self.performance_leeways[i] / TOTAL_BASIS_POINTS
        raise ValueError(f"Key number {key_number} is out of {self.key_pivots}")


class CSParametersRegistryContract(ContractInterface):
    abi_path = "./assets/CSParametersRegistry.json"

    def get_performance_coefficients(
        self,
        curve_id: int,
        block_identifier: BlockIdentifier = "latest"
    ) -> PerformanceCoefficients:
        """Returns performance coefficients for given node operator"""

        resp = self.functions.getPerformanceCoefficients(curve_id).call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": f"Call `getPerformanceCoefficients({curve_id})`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return PerformanceCoefficients(*resp)

    def get_reward_share_data(
        self,
        curve_id: int,
        block_identifier: BlockIdentifier = "latest"
    ) -> RewardShare:
        """Returns reward share data for given node operator"""

        resp = self.functions.getRewardShareData(curve_id).call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": f"Call `getRewardShareData({curve_id})`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return RewardShare(*resp)

    def get_performance_leeway_data(
        self,
        curve_id: int,
        block_identifier: BlockIdentifier = "latest"
    ) -> PerformanceLeeway:
        """Returns performance leeway data for given node operator"""

        resp = self.functions.getPerformanceLeewayData(curve_id).call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": f"Call `getPerformanceLeewayData({curve_id})`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return PerformanceLeeway(*resp)