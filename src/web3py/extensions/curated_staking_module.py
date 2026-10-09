from typing import cast

from web3.exceptions import BadFunctionCallOutput, ContractLogicError

from src.constants import TOTAL_BASIS_POINTS
from src.providers.execution.contracts.curated_staking_module import CuratedStakingModuleContract
from src.providers.execution.contracts.custom_fee_registry import CustomFeeRegistryContract
from src.providers.execution.contracts.meta_registry import MetaRegistryContract
from src.providers.execution.exceptions import InconsistentData
from src.types import BlockHash, BlockStamp, NodeOperatorId
from src.utils.cache import global_lru_cache as lru_cache
from src.web3py.extensions.staking_module import StakingModuleContracts


CUSTOM_FEE_MIN_CONSENSUS_VERSION = 5
FEE_SHARE_DISCOUNT_STEP = 100


class CuratedModuleContracts(StakingModuleContracts):
    """Staking module contracts of the Curated Module, which also applies operators' custom fee share discounts."""

    def get_fee_share_discount(self, no_id: NodeOperatorId, blockstamp: BlockStamp) -> int:
        registry = self._get_custom_fee_registry(blockstamp.block_hash)
        if registry is None:
            return 0

        discount = registry.get_fee_share_discount(no_id, blockstamp.block_hash)
        if not 0 <= discount <= TOTAL_BASIS_POINTS or discount % FEE_SHARE_DISCOUNT_STEP:
            raise InconsistentData(f"Invalid fee share discount for {no_id=}: {discount=}")
        return discount

    @lru_cache(maxsize=1)
    def _get_custom_fee_registry(self, block_hash: BlockHash) -> CustomFeeRegistryContract | None:
        # Weight boost providers do not exist in MetaRegistry before the consensus version that introduces the discount.
        if self.oracle.get_consensus_version(block_hash) < CUSTOM_FEE_MIN_CONSENSUS_VERSION:
            return None

        module = cast(
            CuratedStakingModuleContract,
            self.w3.eth.contract(
                address=self.module.address,
                ContractFactoryClass=CuratedStakingModuleContract,
                decode_tuples=True,
            ),
        )
        meta_registry = cast(
            MetaRegistryContract,
            self.w3.eth.contract(
                address=module.get_meta_registry_address(block_hash),
                ContractFactoryClass=MetaRegistryContract,
                decode_tuples=True,
            ),
        )

        # TODO: probe-based discovery is a stopgap, a cleaner way to locate CustomFeeRegistry is needed
        registries: list[CustomFeeRegistryContract] = []
        for provider_address in meta_registry.get_weight_boost_providers(block_hash):
            candidate = cast(
                CustomFeeRegistryContract,
                self.w3.eth.contract(
                    address=provider_address,
                    ContractFactoryClass=CustomFeeRegistryContract,
                    decode_tuples=True,
                ),
            )
            try:
                step = candidate.fee_share_discount_step(block_hash)
            except (ContractLogicError, BadFunctionCallOutput):
                # Other providers do not implement FEE_SHARE_DISCOUNT_STEP
                continue
            if step == FEE_SHARE_DISCOUNT_STEP:
                registries.append(candidate)

        if len(registries) > 1:
            raise InconsistentData(f"Multiple CustomFeeRegistry providers found: {[r.address for r in registries]}")

        return registries[0] if registries else None
