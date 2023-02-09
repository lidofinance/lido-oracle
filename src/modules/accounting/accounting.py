import logging

from src.modules.accounting.typings import CommonDataToProcess
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.services.bunker import BunkerService
from src.typings import BlockStamp
from src.web3_extentions.typings import Web3

logger = logging.getLogger(__name__)


class Accounting(BaseModule, ConsensusModule):
    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.accounting_oracle
        ConsensusModule.report_contract = self.report_contract
        BunkerService.report_contract = self.report_contract
        super().__init__(w3)

    def execute_module(self, blockstamp: BlockStamp):
        """
        1. Get slot to report getMemberInfo(address)
        2. If slot finalized - build report for slot
        3. Check members hash
            1. If it is actual - no steps
            2. If this is old hash - resubmit to new
        4. If consensus are done - send report data
        5. Send extra data
        """
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.build_report(report_blockstamp)

    def build_report(self, blockstamp: BlockStamp):
        member_info = self.get_member_info(blockstamp)
        frame_config = self.get_frame_config(blockstamp)
        chain_config = self.get_chain_config(blockstamp)

        all_validators, lido_keys, lido_validators = self.w3.lido_validators.get_lido_validators_with_others(blockstamp)
        logger.info({"msg": f"Validators - all: {len(all_validators)} lido: {len(lido_validators)}"})

        cdtp = CommonDataToProcess(
          blockstamp,
          blockstamp.slot_number * chain_config.seconds_per_slot + chain_config.genesis_time,
          blockstamp.slot_number // chain_config.slots_per_epoch,
          all_validators,
          lido_validators,
          lido_keys,
          member_info.last_report_ref_slot,
          member_info.last_report_ref_slot // chain_config.slots_per_epoch,
          (blockstamp.slot_number - member_info.last_report_ref_slot) * chain_config.seconds_per_slot,
        )

        b = BunkerService(self.w3, frame_config, chain_config)
        is_bunker = b.is_bunker_mode(cdtp)
        ...
