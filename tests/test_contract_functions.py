from unittest.mock import patch

from app.contracts import get_validators_keys
from lido import Lido


# fmt: off
operators_with_keys = [
    {
        'keys':
        [
            {
                'key': b'\x81',
            },
            {
                'key': b'\x95',
            }
        ]
    }, 
    {
        'keys':
        [
            {
                'key': b'\xa5',
            }
        ]
    }
]
# fmt: on


@patch.object(Lido, '__init__')
@patch.object(Lido, 'get_operators_data')
@patch.object(Lido, 'get_operators_keys')
def test_validators_keys(get_keys_method, get_ops_method, init_method):
    init_method.return_value = None
    get_ops_method.return_value = None
    get_keys_method.return_value = operators_with_keys

    keys = get_validators_keys(None, None)

    assert keys == [b'\x81', b'\x95', b'\xa5']
