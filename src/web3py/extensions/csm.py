import logging
from functools import partial
from time import sleep
from typing import Iterable, cast

from lazy_object_proxy import Proxy
from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import BadFunctionCallOutput
from web3.module import Module
from web3.types import BlockIdentifier

from src import variables
from src.metrics.prometheus.business import FRAME_PREV_REPORT_REF_SLOT
from src.providers.execution.contracts.CSFeeDistributor import CSFeeDistributor
from src.providers.execution.contracts.CSFeeOracle import CSFeeOracle

# TODO: Export the classes from the top-level module.
from src.providers.execution.contracts.CSModule import CSModule
from src.typings import BlockStamp, SlotNumber
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

    def get_csm_tree_cid(self, blockstamp: BlockStamp) -> str:
        result = self.fee_distributor.tree_cid(blockstamp.block_hash)
        logger.info({"msg": f"CSM distributor latest tree CID {result}"})
        return result

    def get_csm_stuck_node_operators(
        self, l_block: BlockIdentifier, r_block: BlockIdentifier
    ) -> Iterable[NodeOperatorId]:
        """Returns node operators assumed to be stuck for the given frame (defined by the slots)"""

        yield from (
            NodeOperatorId(id)
            for id in self.module.get_stuck_node_operators(
                r_block,
                l_block,
            )
        )

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