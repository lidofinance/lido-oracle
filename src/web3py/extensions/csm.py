import logging
from functools import partial
from itertools import groupby
from time import sleep
from typing import Callable, Iterator, cast

from eth_typing import BlockNumber
from hexbytes import HexBytes
from lazy_object_proxy import Proxy
from web3 import Web3
from web3.contract.contract import ContractEvent
from web3.exceptions import Web3Exception
from web3.module import Module
from web3.types import BlockIdentifier, EventData

from src import variables
from src.metrics.prometheus.business import FRAME_PREV_REPORT_REF_SLOT
from src.providers.execution.contracts.cs_accounting import CSAccountingContract
from src.providers.execution.contracts.cs_fee_distributor import CSFeeDistributorContract
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.contracts.cs_module import CSModuleContract
from src.providers.execution.contracts.cs_parameters_registry import CSParametersRegistryContract
from src.providers.ipfs import CID, CIDv0, CIDv1, is_cid_v0
from src.types import BlockStamp, SlotNumber
from src.utils.events import get_events_in_range
from src.web3py.extensions.lido_validators import NodeOperatorId

logger = logging.getLogger(__name__)


class CSM(Module):
    w3: Web3

    oracle: CSFeeOracleContract
    accounting: CSAccountingContract
    fee_distributor: CSFeeDistributorContract
    module: CSModuleContract
    params: CSParametersRegistryContract

    def __init__(self, w3: Web3) -> None:
        super().__init__(w3)
        self._load_contracts()

    def get_csm_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        FRAME_PREV_REPORT_REF_SLOT.labels("csm_oracle").set(result)
        return result

    def get_csm_tree_root(self, blockstamp: BlockStamp) -> HexBytes:
        return self.fee_distributor.tree_root(blockstamp.block_hash)

    def get_csm_tree_cid(self, blockstamp: BlockStamp) -> CID | None:
        result = self.fee_distributor.tree_cid(blockstamp.block_hash)
        if result == "":
            return None
        return CIDv0(result) if is_cid_v0(result) else CIDv1(result)

    def get_operators_with_stucks_in_range(
        self,
        l_block: BlockIdentifier,
        r_block: BlockIdentifier,
    ) -> Iterator[NodeOperatorId]:
        """Returns node operators assumed to be stuck for the given frame (defined by the block identifiers)"""

        l_block_number = self.w3.eth.get_block(l_block).get("number", BlockNumber(0))
        r_block_number = self.w3.eth.get_block(r_block).get("number", BlockNumber(0))

        by_no_id: Callable[[EventData], int] = lambda e: e["args"]["nodeOperatorId"]

        events = sorted(
            get_events_in_range(
                cast(ContractEvent, self.module.events.StuckSigningKeysCountChanged),
                l_block_number,
                r_block_number,
            ),
            key=by_no_id,
        )

        for no_id, group in groupby(events, key=by_no_id):
            if any(e["args"]["stuckKeysCount"] > 0 for e in group):
                yield NodeOperatorId(no_id)

    def _load_contracts(self) -> None:
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
        except Web3Exception as ex:
            logger.error({"msg": "Some of the contracts aren't healthy", "error": str(ex)})
            sleep(60)
            self._load_contracts()


class LazyCSM(CSM):
    """A wrapper around CSM module to achieve lazy-loading behaviour"""

    def __new__(cls, w3: Web3):
        return Proxy(partial(CSM, w3))  # type: ignore
