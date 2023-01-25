import binascii
from functools import lru_cache
from typing import List, Dict

from hexbytes import HexBytes
from lido_sdk import Lido
from lido_sdk.methods.typing import OperatorKey
from web3 import Web3

from src.providers.beacon import BeaconChainClient
from src.typings import MergedLidoValidator, ModifiedOperatorKey, ModifiedOperator


def _get_dict_of_keys(validators: List[OperatorKey]) -> Dict[str, OperatorKey]:
    """Key is pubkey in hex format. Value is data from key registry."""
    return {
        '0x' + binascii.hexlify(validator['key']).decode(): validator for validator in validators
    }


@lru_cache(maxsize=2)
def get_lido_node_operators(w3: Web3, block_hash: HexBytes) -> List[ModifiedOperator]:
    # TODO Fix library - add fetch by block configuration and rewrite using not just NO module (in future)
    lido = Lido(w3)
    lido.get_operators_indexes()
    return [ModifiedOperator(module_id='0x9D4AF1Ee19Dad8857db3a45B0374c81c8A1C6320', **op) for op in lido.get_operators_data()]


@lru_cache(maxsize=2)
def get_validators_keys(w3: Web3, block_hash: HexBytes) -> List[OperatorKey]:
    """Fetch all validator's keys from NO registry"""
    # TODO Fix library - add fetch by block configuration and rewrite using not just NO module (in future)
    lido = Lido(w3)
    lido.get_operators_indexes()
    lido.get_operators_data()
    return lido.get_operators_keys()


@lru_cache(maxsize=5)
def get_lido_validators(w3: Web3, block_hash: HexBytes, beacon: BeaconChainClient, slot: int) -> List[MergedLidoValidator]:
    """Fetch all Lido validators on Execution and Consensus layer. Merge execution data and consensus data."""
    validators_from_storage = get_validators_keys(w3, block_hash)
    keys = _get_dict_of_keys(validators_from_storage)

    validators = beacon.get_validators(slot)

    result = []
    for validator in validators:
        if validator['validator']['pubkey'] in keys:
            result.append(MergedLidoValidator(
                validator=validator,
                key=ModifiedOperatorKey(
                    module_id='0x9D4AF1Ee19Dad8857db3a45B0374c81c8A1C6320',
                    **keys[validator['validator']['pubkey']],
                ),
            ))

    return result
