import logging
from functools import partial
from time import sleep
from typing import Iterable, cast

from hexbytes import HexBytes
from lazy_object_proxy import Proxy
from web3 import Web3
from web3.exceptions import Web3Exception
from web3.module import Module
from web3.types import BlockIdentifier

from src import variables
from src.metrics.prometheus.business import FRAME_PREV_REPORT_REF_SLOT
from src.providers.execution.contracts.cs_fee_distributor import CSFeeDistributorContract
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.contracts.cs_module import CSModuleContract
from src.providers.ipfs import CIDv0, CIDv1, is_cid_v0
from src.types import BlockStamp, SlotNumber
from src.web3py.extensions.lido_validators import NodeOperatorId

logger = logging.getLogger(__name__)


class CSM(Module):
    w3: Web3

    oracle: CSFeeOracleContract
    fee_distributor: CSFeeDistributorContract
    module: CSModuleContract

    def __init__(self, w3: Web3) -> None:
        super().__init__(w3)
        self._load_contracts()

    def get_csm_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        FRAME_PREV_REPORT_REF_SLOT.labels("csm_oracle").set(result)
        return result

    def get_csm_tree_root(self, blockstamp: BlockStamp) -> HexBytes:
        return self.fee_distributor.tree_root(blockstamp.block_hash)

    def get_csm_tree_cid(self, blockstamp: BlockStamp) -> CIDv0 | CIDv1:
        result = self.fee_distributor.tree_cid(blockstamp.block_hash)
        return CIDv0(result) if is_cid_v0(result) else CIDv1(result)

    def get_csm_stuck_node_operators(
        self, l_block: BlockIdentifier, r_block: BlockIdentifier
    ) -> Iterable[NodeOperatorId]:
        """Returns node operators assumed to be stuck for the given frame (defined by the blocks identifiers)"""

        stuck: set[NodeOperatorId] = set()
        stuck.update(self.module.get_stuck_operators_ids(l_block))
        stuck.update(
            self.module.new_stuck_operators_ids(
                l_block,
                r_block,
            )
        )

        return stuck

    def _load_contracts(self) -> None:
        try:
            self.oracle = cast(
                CSFeeOracleContract,
                self.w3.eth.contract(
                    address=variables.CSM_ORACLE_ADDRESS,  # type: ignore
                    ContractFactoryClass=CSFeeOracleContract,
                    decode_tuples=True,
                ),
            )

            self.module = cast(
                CSModuleContract,
                self.w3.eth.contract(
                    address=variables.CSM_MODULE_ADDRESS,  # type: ignore
                    ContractFactoryClass=CSModuleContract,
                    decode_tuples=True,
                ),
            )

            self.fee_distributor = cast(
                CSFeeDistributorContract,
                self.w3.eth.contract(
                    address=self.oracle.fee_distributor(),
                    ContractFactoryClass=CSFeeDistributorContract,
                    decode_tuples=True,
                ),
            )
        except Web3Exception as ex:
            logger.error({"msg": "Some of the contracts aren't healthy", "error": str(ex)})
            sleep(60)
            self._load_contracts()


class LazyCSM(CSM):
    """A wrapper around CSM module to achieve lazy-loading behaviour"""

    def __new__(cls, w3: Web3):
        return Proxy(partial(CSM, w3))  # type: ignore
