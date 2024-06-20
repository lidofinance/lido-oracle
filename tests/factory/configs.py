from typing import overload
from src.modules.accounting.types import OracleReportLimits
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.consensus.types import (
    BeaconSpecResponse,
    SlotAttestationCommittee,
    BlockAttestation,
    AttestationData,
    Checkpoint,
)
from src.services.bunker_cases.types import BunkerConfig
from tests.factory.web3_factory import Web3Factory


class ChainConfigFactory(Web3Factory):
    __model__ = ChainConfig

    slots_per_epoch = 32
    seconds_per_slot = 12
    genesis_time = 0


class FrameConfigFactory(Web3Factory):
    __model__ = FrameConfig

    initial_epoch = 0
    epochs_per_frame = 10


class OracleReportLimitsFactory(Web3Factory):
    __model__ = OracleReportLimits

    churn_validators_per_day_limit = 0
    one_off_cl_balance_decrease_bp_limit = 0
    annual_balance_increase_bp_limit = 0
    simulated_share_rate_deviation_bp_limit = 0
    max_validator_exit_requests_per_report = 0
    max_accounting_extra_data_list_items_count = 0
    max_node_operators_per_extra_data_item_count = 0
    request_timestamp_margin = 0
    max_positive_token_rebase = 0


class BunkerConfigFactory(Web3Factory):
    __model__ = BunkerConfig


class BeaconSpecResponseFactory(Web3Factory):
    __model__ = BeaconSpecResponse

    SECONDS_PER_SLOT = 12
    SLOTS_PER_EPOCH = 32
    SLOTS_PER_HISTORICAL_ROOT = 8192


class SlotAttestationCommitteeFactory(Web3Factory):
    __model__ = SlotAttestationCommittee

    slot = 0
    index = 0
    validators = []


class BlockAttestationFactory(Web3Factory):
    __model__ = BlockAttestation

    aggregation_bits = "0x"
    data = AttestationData(
        slot="0",
        index="0",
        beacon_block_root="0x",
        source=Checkpoint("0", "0x"),
        target=Checkpoint("0", "0x"),
    )
