import logging
from collections import UserList
from dataclasses import dataclass

from web3.types import BlockIdentifier

from src.constants import TOTAL_BASIS_POINTS, ATTESTATIONS_WEIGHT, BLOCKS_WEIGHT, SYNC_WEIGHT
from src.modules.csm.state import ValidatorDuties
from src.providers.execution.base_interface import ContractInterface
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


@dataclass
class PerformanceCoefficients:
    attestations_weight: int = ATTESTATIONS_WEIGHT
    blocks_weight: int = BLOCKS_WEIGHT
    sync_weight: int = SYNC_WEIGHT

    def calc_performance(self, duties: ValidatorDuties) -> float:
        base = 0
        performance = 0.0

        if duties.attestation:
            base += self.attestations_weight
            performance += duties.attestation.perf * self.attestations_weight

        if duties.proposal:
            base += self.blocks_weight
            performance += duties.proposal.perf * self.blocks_weight

        if duties.sync:
            base += self.sync_weight
            performance += duties.sync.perf * self.sync_weight

        performance /= base

        if performance > 1:
            raise ValueError(f"Invalid performance: {performance=}")

        return performance


@dataclass
class KeyNumberValueInterval:
    minKeyNumber: int
    value: int


class KeyNumberValueIntervalList(UserList[KeyNumberValueInterval]):

    def get_for(self, key_number: int) -> float:
        if key_number < 1:
            raise ValueError("Key number should be greater than 1 or equal")
        for interval in sorted(self, key=lambda x: x.minKeyNumber, reverse=True):
            if key_number >= interval.minKeyNumber:
                return interval.value / TOTAL_BASIS_POINTS
        raise ValueError(f"No value found for key number={key_number}")


@dataclass
class StrikesParams:
    lifetime: int
    threshold: int


@dataclass
class CurveParams:
    perf_coeffs: PerformanceCoefficients
    perf_leeway_data: KeyNumberValueIntervalList
    reward_share_data: KeyNumberValueIntervalList
    strikes_params: StrikesParams


class CSParametersRegistryContract(ContractInterface):
    abi_path = "./assets/CSParametersRegistry.json"

    @lru_cache()
    def get_performance_coefficients(
        self,
        curve_id: int,
        block_identifier: BlockIdentifier = "latest",
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

    @lru_cache()
    def get_reward_share_data(
        self,
        curve_id: int,
        block_identifier: BlockIdentifier = "latest",
    ) -> KeyNumberValueIntervalList:
        """Returns reward share data for given node operator"""

        resp = self.functions.getRewardShareData(curve_id).call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": f"Call `getRewardShareData({curve_id})`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return KeyNumberValueIntervalList([KeyNumberValueInterval(r.minKeyNumber, r.value) for r in resp])

    @lru_cache()
    def get_performance_leeway_data(
        self,
        curve_id: int,
        block_identifier: BlockIdentifier = "latest",
    ) -> KeyNumberValueIntervalList:
        """Returns performance leeway data for given node operator"""

        resp = self.functions.getPerformanceLeewayData(curve_id).call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": f"Call `getPerformanceLeewayData({curve_id})`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return KeyNumberValueIntervalList([KeyNumberValueInterval(r.minKeyNumber, r.value) for r in resp])

    @lru_cache()
    def get_strikes_params(
        self,
        curve_id: int,
        block_identifier: BlockIdentifier = "latest",
    ) -> StrikesParams:
        """Returns strikes params for a given curve id"""

        resp = self.functions.getStrikesParams(curve_id).call(block_identifier=block_identifier)
        logger.info(
            {
                "msg": f"Call `getStrikesParams({curve_id})`.",
                "value": resp,
                "block_identifier": repr(block_identifier),
            }
        )
        return StrikesParams(*resp)
