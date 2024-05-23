import logging
from functools import partial
from time import sleep
from typing import Iterable, cast

from hexbytes import HexBytes
from lazy_object_proxy import Proxy
from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import BadFunctionCallOutput
from web3.module import Module
from web3.types import BlockIdentifier

from src import variables
from src.metrics.prometheus.business import FRAME_PREV_REPORT_REF_SLOT
from src.providers.execution.contracts import CSFeeDistributor, CSFeeOracle, CSModule
from src.providers.ipfs import CIDv0, CIDv1, is_cid_v0
from src.types import BlockStamp, SlotNumber
from src.web3py.extensions.lido_validators import NodeOperatorId

logger = logging.getLogger(__name__)


class CSM(Module):
    w3: Web3

    oracle: CSFeeOracle
    fee_distributor: CSFeeDistributor
    module: CSModule

    def __init__(self, w3: Web3) -> None:
        super().__init__(w3)
        self._load_contracts()

    def get_csm_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        logger.info({"msg": f"CSM oracle last processing ref slot {result}"})
        FRAME_PREV_REPORT_REF_SLOT.labels("csm_oracle").set(result)
        return result

    def get_csm_tree_root(self, blockstamp: BlockStamp) -> HexBytes:
        result = HexBytes(self.fee_distributor.tree_root(blockstamp.block_hash))
        logger.info({"msg": f"CSM distributor latest tree root {repr(result)}"})
        return result

    def get_csm_tree_cid(self, blockstamp: BlockStamp) -> CIDv0 | CIDv1:
        result = self.fee_distributor.tree_cid(blockstamp.block_hash)
        logger.info({"msg": f"CSM distributor latest tree CID '{result}'"})
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
        self.oracle = cast(
            CSFeeOracle,
            self.w3.eth.contract(
                address=variables.CSM_ORACLE_ADDRESS,  # type: ignore
                ContractFactoryClass=CSFeeOracle,
                decode_tuples=True,
            ),
        )

        self.module = cast(
            CSModule,
            self.w3.eth.contract(
                address=variables.CSM_MODULE_ADDRESS,  # type: ignore
                ContractFactoryClass=CSModule,
                decode_tuples=True,
            ),
        )

        self.fee_distributor = cast(
            CSFeeDistributor,
            self.w3.eth.contract(
                address=self.oracle.fee_distributor(),
                ContractFactoryClass=CSFeeDistributor,
                decode_tuples=True,
            ),
        )

    def _check_contracts(self):
        """This is startup check that checks that contract are deployed and has valid implementation"""
        try:
            self.oracle.functions.getContractVersion().call()
        except BadFunctionCallOutput:
            logger.info({"msg": "Some of the contracts aren't healthy"})
            sleep(60)
            self._load_contracts()
        else:
            return

    def __setattr__(self, key, value):
        current_value = getattr(self, key, None)
        if isinstance(current_value, Contract) and isinstance(value, Contract):
            if value.address != current_value.address:
                logger.info({"msg": f"Contract {key} has been changed to {value.address}"})
        super().__setattr__(key, value)


class LazyCSM(CSM):
    """A wrapper around CSM module to achieve lazy-loading behaviour"""

    def __new__(cls, w3: Web3):
        return Proxy(partial(CSM, w3))  # type: ignore
