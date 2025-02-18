import logging
from dataclasses import dataclass

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface

logger = logging.getLogger(__name__)


@dataclass
class PerformanceCoefficients:
    attestations_weight: int
    blocks_weight: int
    sync_weight: int


@dataclass
class RewardShare:
    key_pivots: list[int]
    reward_shares: list[int]


@dataclass
class PerformanceLeeway:
    key_pivots: list[int]
    performance_leeways: list[int]


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