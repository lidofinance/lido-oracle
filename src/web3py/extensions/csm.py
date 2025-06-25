import logging
from functools import partial
from time import sleep
from typing import cast

from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import Web3Exception
from web3.module import Module

from src import variables
from src.metrics.prometheus.business import FRAME_PREV_REPORT_REF_SLOT
from src.providers.execution.contracts.cs_accounting import CSAccountingContract
from src.providers.execution.contracts.cs_fee_distributor import CSFeeDistributorContract
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.contracts.cs_module import CSModuleContract
from src.providers.execution.contracts.cs_parameters_registry import CSParametersRegistryContract, CurveParams
from src.providers.execution.contracts.cs_strikes import CSStrikesContract
from src.providers.ipfs import CID, CIDv0, CIDv1, is_cid_v0
from src.utils.lazy_object_proxy import LazyObjectProxy
from src.types import BlockStamp, NodeOperatorId, SlotNumber

logger = logging.getLogger(__name__)


class CSM(Module):
    w3: Web3

    oracle: CSFeeOracleContract
    accounting: CSAccountingContract
    fee_distributor: CSFeeDistributorContract
    strikes: CSStrikesContract
    module: CSModuleContract
    params: CSParametersRegistryContract

    CONTRACT_LOAD_MAX_RETRIES: int = 100
    CONTRACT_LOAD_RETRY_DELAY: int = 60

    def __init__(self, w3: Web3) -> None:
        super().__init__(w3)
        self._load_contracts()

    def get_csm_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        FRAME_PREV_REPORT_REF_SLOT.labels("csm_oracle").set(result)
        return result

    def get_rewards_tree_root(self, blockstamp: BlockStamp) -> HexBytes:
        return self.fee_distributor.tree_root(blockstamp.block_hash)

    def get_rewards_tree_cid(self, blockstamp: BlockStamp) -> CID | None:
        result = self.fee_distributor.tree_cid(blockstamp.block_hash)
        if result == "":
            return None
        return CIDv0(result) if is_cid_v0(result) else CIDv1(result)

    def get_strikes_tree_root(self, blockstamp: BlockStamp) -> HexBytes:
        return self.strikes.tree_root(blockstamp.block_hash)

    def get_strikes_tree_cid(self, blockstamp: BlockStamp) -> CID | None:
        result = self.strikes.tree_cid(blockstamp.block_hash)
        if result == "":
            return None
        return CIDv0(result) if is_cid_v0(result) else CIDv1(result)

    def get_curve_params(self, no_id: NodeOperatorId, blockstamp: BlockStamp) -> CurveParams:
        curve_id = self.accounting.get_bond_curve_id(no_id, blockstamp.block_hash)
        perf_coeffs = self.params.get_performance_coefficients(curve_id, blockstamp.block_hash)
        perf_leeway_data = self.params.get_performance_leeway_data(curve_id, blockstamp.block_hash)
        reward_share_data = self.params.get_reward_share_data(curve_id, blockstamp.block_hash)
        strikes_params = self.params.get_strikes_params(curve_id, blockstamp.block_hash)
        return CurveParams(perf_coeffs, perf_leeway_data, reward_share_data, strikes_params)

    def _load_contracts(self) -> None:
        last_error = None

        for attempt in range(self.CONTRACT_LOAD_MAX_RETRIES):
            try:
                self.module = cast(
                    CSModuleContract,
                    self.w3.eth.contract(
                        address=variables.CSM_MODULE_ADDRESS,  # type: ignore
                        ContractFactoryClass=CSModuleContract,
                        decode_tuples=True,
                    ),
                )

                self.params = cast(
                    CSParametersRegistryContract,
                    self.w3.eth.contract(
                        address=self.module.parameters_registry(),
                        ContractFactoryClass=CSParametersRegistryContract,
                        decode_tuples=True,
                    ),
                )

                self.accounting = cast(
                    CSAccountingContract,
                    self.w3.eth.contract(
                        address=self.module.accounting(),
                        ContractFactoryClass=CSAccountingContract,
                        decode_tuples=True,
                    ),
                )

                self.fee_distributor = cast(
                    CSFeeDistributorContract,
                    self.w3.eth.contract(
                        address=self.accounting.fee_distributor(),
                        ContractFactoryClass=CSFeeDistributorContract,
                        decode_tuples=True,
                    ),
                )

                self.oracle = cast(
                    CSFeeOracleContract,
                    self.w3.eth.contract(
                        address=self.fee_distributor.oracle(),
                        ContractFactoryClass=CSFeeOracleContract,
                        decode_tuples=True,
                    ),
                )

                self.strikes = cast(
                    CSStrikesContract,
                    self.w3.eth.contract(
                        address=self.oracle.strikes(),
                        ContractFactoryClass=CSStrikesContract,
                        decode_tuples=True,
                    ),
                )
                return
            except Web3Exception as e:
                last_error = e
                logger.error({
                    "msg": f"Attempt {attempt + 1}/{self.CONTRACT_LOAD_MAX_RETRIES} failed to load contracts",
                    "error": str(e)
                })
                sleep(self.CONTRACT_LOAD_RETRY_DELAY)

        raise Web3Exception(
            f"Failed to load contracts in CSM module "
            f"after {self.CONTRACT_LOAD_MAX_RETRIES} attempts"
        ) from last_error


class LazyCSM(CSM):
    """A wrapper around CSM module to achieve lazy-loading behaviour"""

    def __new__(cls, w3: Web3) -> 'LazyCSM':
        return LazyObjectProxy(partial(CSM, w3))  # type: ignore
