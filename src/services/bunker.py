import logging
from functools import lru_cache

from src.constants import TOTAL_BASIS_POINTS, GWEI_TO_WEI
from src.providers.keys.typings import LidoKey
from src.services.bunker_cases.abnormal_cl_rebase import AbnormalClRebase
from src.services.bunker_cases.midterm_slashing_penalty import MidtermSlashingPenalty

from src.modules.accounting.typings import LidoReportRebase
from src.modules.submodules.consensus import FrameConfig, ChainConfig
from src.providers.consensus.typings import Validator
from src.services.bunker_cases.typings import BunkerConfig
from src.typings import BlockStamp, SlotNumber, ReferenceBlockStamp, Gwei
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class BunkerService(MidtermSlashingPenalty, AbnormalClRebase):
    """
    https://research.lido.fi/t/withdrawals-for-lido-on-ethereum-bunker-mode-design-and-implementation/
    """
    b_conf: BunkerConfig
    c_conf: ChainConfig
    f_conf: FrameConfig

    simulated_cl_rebase: LidoReportRebase

    last_report_ref_slot: SlotNumber

    all_validators: dict[str, Validator]
    lido_keys: dict[str, LidoKey]
    lido_validators: dict[str, LidoValidator]

    def __init__(self, w3: Web3):
        self.w3 = w3
        super().__init__(w3)

    @lru_cache(maxsize=1)
    def is_bunker_mode(
        self,
        blockstamp: ReferenceBlockStamp,
        frame_config: FrameConfig,
        chain_config: ChainConfig,
        simulated_cl_rebase: LidoReportRebase,
    ) -> bool:
        self.f_conf = frame_config
        self.c_conf = chain_config
        self.simulated_cl_rebase = simulated_cl_rebase
        self.b_conf = self._get_config(blockstamp)
        self.last_report_ref_slot = self.w3.lido_contracts.accounting_oracle.functions.getLastProcessingRefSlot().call(
            block_identifier=blockstamp.block_hash
        )

        if self.last_report_ref_slot == 0:
            logger.info({"msg": "No one report yet. Bunker status will not be checked"})
            return False

        self.lido_keys = {k.key: k for k in self.w3.kac.get_all_lido_keys(blockstamp)}
        self.all_validators: dict[str, Validator] = {
            v.validator.pubkey: v for v in self.w3.cc.get_validators(blockstamp)
        }
        self.lido_validators: dict[str, LidoValidator] = {
            v.validator.pubkey: v
            for v in self.w3.lido_validators.get_lido_validators(blockstamp)
        }
        logger.info({"msg": f"Validators - all: {len(self.all_validators)} lido: {len(self.lido_validators)}"})

        logger.info({"msg": "Checking bunker mode"})
        current_report_cl_rebase = self._get_cl_rebase_for_current_report(blockstamp)
        if current_report_cl_rebase < 0:
            logger.info({"msg": "Bunker ON. CL rebase is negative"})
            return True
        if self.is_high_midterm_slashing_penalty(blockstamp, current_report_cl_rebase):
            logger.info({"msg": "Bunker ON. High midterm slashing penalty"})
            return True
        if self.is_abnormal_cl_rebase(blockstamp, current_report_cl_rebase):
            logger.info({"msg": "Bunker ON. Abnormal CL rebase"})
            return True

        return False

    def _get_config(self, blockstamp: BlockStamp) -> BunkerConfig:
        """
        Get config values from OracleDaemonConfig contract
        """
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

    def _get_cl_rebase_for_current_report(self, blockstamp: BlockStamp) -> Gwei:
        """
        Get CL rebase from Accounting contract
        """
        logger.info({"msg": "Getting CL rebase for frame"})
        before_report_total_pooled_ether = self._get_total_supply(blockstamp)

        # Can't use from_wei - because rebase can be negative
        frame_cl_rebase = (self.simulated_cl_rebase.post_total_pooled_ether - before_report_total_pooled_ether) // GWEI_TO_WEI
        logger.info({"msg": f"Simulated CL rebase for frame: {frame_cl_rebase} Gwei"})
        return Gwei(frame_cl_rebase)

    def _get_total_supply(self, blockstamp: BlockStamp) -> Gwei:
        return self.w3.lido_contracts.lido.functions.totalSupply().call(block_identifier=blockstamp.block_hash)
