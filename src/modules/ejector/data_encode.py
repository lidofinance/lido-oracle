from eth_typing import HexStr

from src.utils.types import hex_str_to_bytes
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperatorGlobalIndex

DATA_FORMAT_LIST = 1

MODULE_ID_LENGTH = 3
NODE_OPERATOR_ID_LENGTH = 5
VALIDATOR_INDEX_LENGTH = 8
VALIDATOR_PUB_KEY_LENGTH = 48


def encode_data(validators: list[tuple[NodeOperatorGlobalIndex, LidoValidator]]):
    #  MSB <------------------------------------------------------- LSB
    #  |  3 bytes   |  5 bytes   |     8 bytes      |    48 bytes     |
    #  |  moduleId  |  nodeOpId  |  validatorIndex  | validatorPubkey |

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
