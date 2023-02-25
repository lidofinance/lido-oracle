from src.web3py.extentions.lido_validators import NodeOperatorIndex, LidoValidator


DATA_FORMAT_LIST = 1

MODULE_ID_LENGTH = 3
NODE_OPERATOR_ID_LENGTH = 5
VALIDATOR_INDEX_LENGTH = 8
VALIDATOR_PUB_KEY_LENGTH = 48


def encode_data(validators: list[tuple[NodeOperatorIndex, LidoValidator]]):
    #     /// MSB <------------------------------------------------------- LSB
    #     /// |  3 bytes   |  5 bytes   |     8 bytes      |    48 bytes     |
    #     /// |  moduleId  |  nodeOpId  |  validatorIndex  | validatorPubkey |

    result = b''

    for (module_id, op_id), validator in validators:
        result += module_id.to_bytes(MODULE_ID_LENGTH)
        result += op_id.to_bytes(NODE_OPERATOR_ID_LENGTH)
        result += int(validator.validator.index).to_bytes(VALIDATOR_INDEX_LENGTH)

        if len(validator.validator.validator.pubkey) != VALIDATOR_PUB_KEY_LENGTH:
            raise ValueError(f'Unexpected size of validator pub key. Pub key size: {len(validator.validator.validator.pubkey)}')

        result += int(validator.validator.validator.pubkey)

    return result, DATA_FORMAT_LIST
