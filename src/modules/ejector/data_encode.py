from eth_typing import HexStr

from src.utils.types import hex_str_to_bytes
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperatorGlobalIndex


DATA_FORMAT_LIST = 1

MODULE_ID_LENGTH = 3
NODE_OPERATOR_ID_LENGTH = 5
VALIDATOR_INDEX_LENGTH = 8
VALIDATOR_PUB_KEY_LENGTH = 48


def encode_data(validators_to_eject: list[tuple[NodeOperatorGlobalIndex, LidoValidator]]):
    """
    Encodes report data for Exit Bus Contract into bytes.

    MSB <------------------------------------------------------- LSB
    |  3 bytes   |  5 bytes   |     8 bytes      |    48 bytes     |
    |  moduleId  |  nodeOpId  |  validatorIndex  | validatorPubkey |
    """
    validators = sort_validators_to_eject(validators_to_eject)

    result = b''

    for (module_id, op_id), validator in validators:
        result += module_id.to_bytes(MODULE_ID_LENGTH)
        result += op_id.to_bytes(NODE_OPERATOR_ID_LENGTH)
        result += int(validator.index).to_bytes(VALIDATOR_INDEX_LENGTH)

        pubkey_bytes = hex_str_to_bytes(HexStr(validator.validator.pubkey))

        if len(pubkey_bytes) != VALIDATOR_PUB_KEY_LENGTH:
            raise ValueError(f'Unexpected size of validator pub key. Pub key size: {len(validator.validator.pubkey)}')

        result += pubkey_bytes

    return result, DATA_FORMAT_LIST


def sort_validators_to_eject(
    validators_to_eject: list[tuple[NodeOperatorGlobalIndex, LidoValidator]],
) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
    def _nog_validator_key(no_validator: tuple[NodeOperatorGlobalIndex, LidoValidator]) -> tuple[int, int, int]:
        (module_id, no_id), validator = no_validator
        return module_id, no_id, int(validator.index)

    validators = sorted(validators_to_eject, key=_nog_validator_key)

    return validators
