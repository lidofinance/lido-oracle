import logging

from src.constants import TOTAL_BASIS_POINTS, GWEI_TO_WEI
from src.metrics.prometheus.validators import (
    ALL_VALIDATORS,
    LIDO_VALIDATORS,
    ALL_SLASHED_VALIDATORS,
    LIDO_SLASHED_VALIDATORS,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.services.bunker_cases.abnormal_cl_rebase import AbnormalClRebase
from src.services.bunker_cases.midterm_slashing_penalty import MidtermSlashingPenalty

from src.modules.accounting.typings import LidoReportRebase
from src.modules.submodules.consensus import FrameConfig, ChainConfig
from src.services.bunker_cases.typings import BunkerConfig
from src.services.safe_border import filter_slashed_validators
from src.typings import BlockStamp, ReferenceBlockStamp, Gwei
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class BunkerService:
    """
    The "bunker mode" would be triggered by one of three cases:
      - Negative CL rebase
      - High midterm slashing penalty
      - Abnormal CL rebase

    Its purpose is to maintain socialization of all problems in Lido validators pool and to prevent sophisticated attacks.
    To achieve this, "bunker mode" limits an operations in Lido protocol (withdrawal requests finalization)

    For more info about bunker mode see:
    https://research.lido.fi/t/withdrawals-for-lido-on-ethereum-bunker-mode-design-and-implementation/
    """
    def __init__(self, w3: Web3):
        self.w3 = w3

    @duration_meter()
    def is_bunker_mode(
        self,
        blockstamp: ReferenceBlockStamp,
        frame_config: FrameConfig,
        chain_config: ChainConfig,
        simulated_cl_rebase: LidoReportRebase,
    ) -> bool:
        """If any of cases is True, then bunker mode is ON"""
        bunker_config = self._get_config(blockstamp)
        all_validators = self.w3.cc.get_validators(blockstamp)
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)

        # Set metrics
        ALL_VALIDATORS.set(len(all_validators))
        LIDO_VALIDATORS.set(len(lido_validators))
        ALL_SLASHED_VALIDATORS.set(len(filter_slashed_validators(all_validators)))
        LIDO_SLASHED_VALIDATORS.set(len(filter_slashed_validators(lido_validators)))

        last_report_ref_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(blockstamp)
        # If it is the very first run, we don't check bunker mode
        if not last_report_ref_slot:
            logger.info({"msg": "No one report yet. Bunker status will not be checked"})
            return False

        logger.info({"msg": "Checking bunker mode"})

        current_report_cl_rebase = self.get_cl_rebase_for_current_report(blockstamp, simulated_cl_rebase)
        if current_report_cl_rebase < 0:
            logger.info({"msg": "Bunker ON. CL rebase is negative"})
            return True

        high_midterm_slashing_penalty = MidtermSlashingPenalty.is_high_midterm_slashing_penalty(
            blockstamp, frame_config, chain_config, all_validators, lido_validators, current_report_cl_rebase, last_report_ref_slot
        )
        if high_midterm_slashing_penalty:
            logger.info({"msg": "Bunker ON. High midterm slashing penalty"})
            return True

        abnormal_cl_rebase = AbnormalClRebase(self.w3, chain_config, bunker_config).is_abnormal_cl_rebase(
            blockstamp, all_validators, lido_validators, current_report_cl_rebase
        )
        if abnormal_cl_rebase:
            logger.info({"msg": "Bunker ON. Abnormal CL rebase"})
            return True

        return False

    def get_cl_rebase_for_current_report(self, blockstamp: BlockStamp, simulated_cl_rebase: LidoReportRebase) -> Gwei:
        """
        Get simulated Cl rebase and subtract total supply before report
        """
        logger.info({"msg": "Getting CL rebase for frame"})
        before_report_total_pooled_ether = self._get_total_supply(blockstamp)

        # Can't use from_wei - because rebase can be negative
        frame_cl_rebase = (simulated_cl_rebase.post_total_pooled_ether - before_report_total_pooled_ether) // GWEI_TO_WEI
        logger.info({"msg": f"Simulated CL rebase for frame: {frame_cl_rebase} Gwei"})
        return Gwei(frame_cl_rebase)

    def _get_total_supply(self, blockstamp: BlockStamp) -> Gwei:
        return self.w3.lido_contracts.lido.functions.totalSupply().call(block_identifier=blockstamp.block_hash)

    def _get_config(self, blockstamp: BlockStamp) -> BunkerConfig:
        """Get config values from OracleDaemonConfig contract"""
        config = self.w3.lido_contracts.oracle_daemon_config
        return BunkerConfig(
            Web3.to_int(
                config.functions.get('NORMALIZED_CL_REWARD_PER_EPOCH').call(block_identifier=blockstamp.block_hash)
            ),
            Web3.to_int(
                config.functions.get('NORMALIZED_CL_REWARD_MISTAKE_RATE_BP').call(block_identifier=blockstamp.block_hash)
            ) / TOTAL_BASIS_POINTS,
            Web3.to_int(
                config.functions.get('REBASE_CHECK_NEAREST_EPOCH_DISTANCE').call(block_identifier=blockstamp.block_hash)
            ),
            Web3.to_int(
                config.functions.get('REBASE_CHECK_DISTANT_EPOCH_DISTANCE').call(block_identifier=blockstamp.block_hash)
            )
        )
