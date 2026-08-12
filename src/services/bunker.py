import logging

from src.constants import PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX, TOTAL_PARTS_PER_MILLION
from src.metrics.prometheus.duration_meter import duration_meter
from src.metrics.prometheus.validators import (
    ALL_SLASHED_VALIDATORS,
    ALL_VALIDATORS,
    LIDO_SLASHED_VALIDATORS,
    LIDO_VALIDATORS,
)
from src.modules.oracles.accounting.types import ReportSimulationResults
from src.providers.consensus.types import Validator
from src.types import Gwei, ReferenceBlockStamp
from src.utils.validator_state import calculate_total_active_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.types import Web3


logger = logging.getLogger(__name__)


class BunkerService:
    """Determine whether the Accounting Oracle report should enable Bunker Mode."""

    def __init__(self, w3: Web3):
        self.w3 = w3

    @duration_meter()
    def is_bunker_mode(
        self,
        blockstamp: ReferenceBlockStamp,
        simulated_cl_rebase: ReportSimulationResults,
    ) -> bool:
        last_report_ref_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(blockstamp)
        if not last_report_ref_slot:
            logger.info({'msg': 'No reports have been processed yet. Bunker status will not be checked.'})
            return False

        logger.info({'msg': 'Checking Bunker Mode'})

        state = self.w3.cc.get_state_view(blockstamp)
        all_validators = state.indexed_validators
        lido_validators = self.w3.lido_validators.get_active_lido_validators(blockstamp)

        ALL_VALIDATORS.set(len(all_validators))
        LIDO_VALIDATORS.set(len(lido_validators))
        ALL_SLASHED_VALIDATORS.set(sum(validator.validator.slashed for validator in all_validators))
        LIDO_SLASHED_VALIDATORS.set(sum(validator.validator.slashed for validator in lido_validators))

        if self.is_negative_cl_rebase(blockstamp, simulated_cl_rebase):
            logger.info({'msg': 'Bunker ON. Simulated CL rebase is negative.'})
            return True

        if self.is_slashing_impact_big_enough(blockstamp, all_validators, lido_validators, state.slashings):
            logger.info({'msg': 'Bunker ON. Slashing impact reached the configured threshold.'})
            return True

        return False

    def is_negative_cl_rebase(
        self,
        blockstamp: ReferenceBlockStamp,
        simulated_cl_rebase: ReportSimulationResults,
    ) -> bool:
        pre_report_total_pooled_ether = self.w3.lido_contracts.lido.total_supply(blockstamp.block_hash)
        post_report_total_pooled_ether = simulated_cl_rebase.post_total_pooled_ether

        logger.info(
            {
                'msg': 'Calculated simulated CL rebase.',
                'value': post_report_total_pooled_ether - pre_report_total_pooled_ether,
            }
        )
        return post_report_total_pooled_ether < pre_report_total_pooled_ether

    def is_slashing_impact_big_enough(
        self,
        blockstamp: ReferenceBlockStamp,
        all_validators: list[Validator],
        lido_validators: list[LidoValidator],
        slashings: list[Gwei],
    ) -> bool:
        lido_exposure = [
            validator
            for validator in lido_validators
            if validator.validator.activation_epoch <= blockstamp.ref_epoch < validator.validator.withdrawable_epoch
        ]
        lido_exposure_balance = sum(
            (validator.validator.effective_balance for validator in lido_exposure),
            Gwei(0),
        )

        if lido_exposure_balance == 0:
            logger.info({'msg': 'Slashing impact is zero because Lido exposure is zero.'})
            return False

        lido_non_withdrawable_slashed_balance = sum(
            (validator.validator.effective_balance for validator in lido_exposure if validator.validator.slashed),
            Gwei(0),
        )
        network_recent_slashed_balance = sum(slashings, Gwei(0))
        network_active_balance = calculate_total_active_effective_balance(all_validators, blockstamp.ref_epoch)

        config = self.w3.lido_contracts.oracle_daemon_config
        base_slashing_impact_rate_ppm = config.bunker_base_slashing_impact_rate_ppm(blockstamp.block_hash)
        slashing_impact_threshold_ppm = config.bunker_slashing_impact_threshold_ppm(blockstamp.block_hash)

        adjusted_network_slashed_balance = min(
            PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX * network_recent_slashed_balance,
            network_active_balance,
        )
        slashing_impact_factor_numerator = (
            base_slashing_impact_rate_ppm * network_active_balance
            + TOTAL_PARTS_PER_MILLION * adjusted_network_slashed_balance
        )
        slashing_impact_share_ppm = (
            lido_non_withdrawable_slashed_balance
            * slashing_impact_factor_numerator
            // (lido_exposure_balance * network_active_balance)
        )

        logger.info(
            {
                'msg': 'Calculated slashing impact.',
                'slashing_impact_share_ppm': slashing_impact_share_ppm,
                'slashing_impact_threshold_ppm': slashing_impact_threshold_ppm,
                'lido_exposure_balance': lido_exposure_balance,
                'lido_non_withdrawable_slashed_balance': lido_non_withdrawable_slashed_balance,
                'network_active_balance': network_active_balance,
                'network_recent_slashed_balance': network_recent_slashed_balance,
            }
        )
        return slashing_impact_share_ppm >= slashing_impact_threshold_ppm
