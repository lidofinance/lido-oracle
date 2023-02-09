from dataclasses import dataclass

from src.providers.consensus.typings import Validator
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp, SlotNumber
from src.web3_extentions import LidoValidator

Gwei = int
Epoch = int


@dataclass(frozen=True)
class CommonDataToProcess:
    ref_blockstamp: BlockStamp
    ref_timestamp: int
    ref_epoch: Epoch
    ref_all_validators: list[Validator]
    ref_lido_validators: list[LidoValidator]
    lido_keys: list[LidoKey]
    last_report_ref_slot: SlotNumber
    last_report_ref_epoch: Epoch
    seconds_elapsed_since_last_report: int
