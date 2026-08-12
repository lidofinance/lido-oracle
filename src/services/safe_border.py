from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.oracles.common.consensus import ChainConfig
from src.types import EpochNumber, ReferenceBlockStamp
from src.web3py.types import Web3


class SafeBorder:
    """Calculate the request-creation cutoff for withdrawal finalization."""

    def __init__(self, w3: Web3, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig) -> None:
        self.w3 = w3
        self.blockstamp = blockstamp

        limits_list = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(
            self.blockstamp.block_hash
        )
        seconds_per_epoch = chain_config.slots_per_epoch * chain_config.seconds_per_slot
        self.finalization_default_shift = (
            limits_list.request_timestamp_margin + seconds_per_epoch - 1
        ) // seconds_per_epoch

    @duration_meter()
    def get_safe_border_epoch(self, is_bunker: bool) -> EpochNumber:
        finalization_shift = self.finalization_default_shift

        if is_bunker:
            bunker_finalization_delay = self.w3.lido_contracts.oracle_daemon_config.bunker_finalization_delay_epochs(
                self.blockstamp.block_hash
            )
            finalization_shift = max(finalization_shift, bunker_finalization_delay)

        return EpochNumber(max(0, self.blockstamp.ref_epoch - finalization_shift))
