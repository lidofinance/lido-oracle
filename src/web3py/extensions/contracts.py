import json
import logging
from time import sleep
from typing import Any

from web3 import Web3
from web3.contract import Contract
from web3.exceptions import BadFunctionCallOutput
from web3.module import Module
from web3.types import Wei

from src import variables
from src.metrics.prometheus.business import FRAME_PREV_REPORT_REF_SLOT
from src.typings import BlockStamp, SlotNumber
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger()


class LidoContracts(Module):
    w3: Web3

    lido_locator: Contract
    lido: Contract
    accounting_oracle: Contract
    staking_router: Contract
    validators_exit_bus_oracle: Contract
    withdrawal_queue_nft: Contract
    oracle_report_sanity_checker: Contract
    oracle_daemon_config: Contract
    burner: Contract
    # XXX: It seems it can be a separate module with these contracts
    csm_oracle: Contract
    csm_distributor: Contract

    def __init__(self, w3: Web3):
        super().__init__(w3)
        self._load_contracts()

    def __setattr__(self, key, value):
        current_value = getattr(self, key, None)
        if isinstance(current_value, Contract) and isinstance(value, Contract):
            if value.address != current_value.address:
                logger.info({'msg': f'Contract {key} has been changed to {value.address}'})
        super().__setattr__(key, value)

    def has_contract_address_changed(self) -> bool:
        addresses = [contract.address for contract in self.__dict__.values() if isinstance(contract, Contract)]
        self._load_contracts()
        new_addresses = [contract.address for contract in self.__dict__.values() if isinstance(contract, Contract)]
        return addresses != new_addresses

    def _check_contracts(self):
        """This is startup check that checks that contract are deployed and has valid implementation"""
        contract: Contract = None # type: ignore
        try:
            # TODO: Do we really have to care about all the contracts if we just run one module at a time?
            for contract in [self.accounting_oracle, self.validators_exit_bus_oracle, self.csm_oracle]:
                contract.functions.getContractVersion().call()
        except BadFunctionCallOutput:
            logger.info({
                'msg': f'getContractVersion method from one of the oracle contracts {contract.address=}'
                       'doesn\'t return any data. Probably addresses from Lido Locator refer to the wrong '
                       'implementation or contracts don\'t exist. Sleep for 1 minute.'
            })
            sleep(60)
            self._load_contracts()
        else:
            return

    def _load_contracts(self):
        # Contract that stores all lido contract addresses
        self.lido_locator = self.w3.eth.contract(
            address=variables.LIDO_LOCATOR_ADDRESS, # type: ignore
            abi=self.load_abi('LidoLocator'),
            decode_tuples=True,
        )

        self.lido = self.w3.eth.contract(
            address=self.lido_locator.functions.lido().call(),
            abi=self.load_abi('Lido'),
            decode_tuples=True,
        )

        self.accounting_oracle = self.w3.eth.contract(
            address=self.lido_locator.functions.accountingOracle().call(),
            abi=self.load_abi('AccountingOracle'),
            decode_tuples=True,
        )

        self.staking_router = self.w3.eth.contract(
            address=self.lido_locator.functions.stakingRouter().call(),
            abi=self.load_abi('StakingRouter'),
            decode_tuples=True,
        )

        self.validators_exit_bus_oracle = self.w3.eth.contract(
            address=self.lido_locator.functions.validatorsExitBusOracle().call(),
            abi=self.load_abi('ValidatorsExitBusOracle'),
            decode_tuples=True,
        )

        self.withdrawal_queue_nft = self.w3.eth.contract(
            address=self.lido_locator.functions.withdrawalQueue().call(),
            abi=self.load_abi('WithdrawalQueueERC721'),
            decode_tuples=True,
        )

        self.oracle_report_sanity_checker = self.w3.eth.contract(
            address=self.lido_locator.functions.oracleReportSanityChecker().call(),
            abi=self.load_abi('OracleReportSanityChecker'),
            decode_tuples=True,
        )

        self.oracle_daemon_config = self.w3.eth.contract(
            address=self.lido_locator.functions.oracleDaemonConfig().call(),
            abi=self.load_abi('OracleDaemonConfig'),
            decode_tuples=True,
        )

        self.burner = self.w3.eth.contract(
            address=self.lido_locator.functions.burner().call(),
            abi=self.load_abi('Burner'),
            decode_tuples=True,
        )

        # TODO: Move to a separate module.
        # {{{
        self.csm_oracle = self.w3.eth.contract(
            address=variables.CSM_ORACLE_ADDRESS,
            abi=self.load_abi('CSFeeOracle'),
            decode_tuples=True,
        )

        self.csm_distributor = self.w3.eth.contract(
            address=self.csm_oracle.functions.feeDistributor().call(),
            abi=self.load_abi('CSFeeDistributor'),
            decode_tuples=True,
        )
        # }}}

        self._check_contracts()

    @staticmethod
    def load_abi(abi_name: str, abi_path: str = './assets/'):
        with open(f'{abi_path}{abi_name}.json') as f:
            return json.load(f)

    # --- Contract methods ---
    @lru_cache(maxsize=1)
    def get_withdrawal_balance(self, blockstamp: BlockStamp) -> Wei:
        return self.get_withdrawal_balance_no_cache(blockstamp)

    def get_withdrawal_balance_no_cache(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.lido_locator.functions.withdrawalVault().call(
                block_identifier=blockstamp.block_hash
            ),
            block_identifier=blockstamp.block_hash,
        ))

    @lru_cache(maxsize=1)
    def get_el_vault_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.lido_locator.functions.elRewardsVault().call(
                block_identifier=blockstamp.block_hash
            ),
            block_identifier=blockstamp.block_hash,
        ))

    @lru_cache(maxsize=1)
    def get_accounting_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.accounting_oracle.functions.getLastProcessingRefSlot().call(block_identifier=blockstamp.block_hash)
        logger.info({'msg': f'Accounting last processing ref slot {result}'})
        FRAME_PREV_REPORT_REF_SLOT.labels('accounting').set(result)
        return result

    @lru_cache(maxsize=1)
    def get_ejector_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.validators_exit_bus_oracle.functions.getLastProcessingRefSlot().call(
            block_identifier=blockstamp.block_hash
        )
        logger.info({'msg': f'Ejector last processing ref slot {result}'})
        FRAME_PREV_REPORT_REF_SLOT.labels('ejector').set(result)
        return result

    # TODO: Move to a separate module.
    @lru_cache(maxsize=1)
    def get_csm_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.csm_oracle.functions.getLastProcessingRefSlot().call(
            block_identifier=blockstamp.block_hash
        )
        logger.info({'msg': f'CSM oracle last processing ref slot {result}'})
        FRAME_PREV_REPORT_REF_SLOT.labels('csm_oracle').set(result)
        return result

    # TODO: Move to a separate module.
    def get_csm_stuck_keys_events(self, blockstamp: BlockStamp) -> list[Any]:
        # TODO: Fetch for stuck keys events from the module directly.
        raise NotImplementedError()

    # TODO: Move to a separate module.
    def get_csm_tree_cid(self, blockstamp: BlockStamp) -> str:
        raise NotImplementedError()
