import pytest
from eth_typing import Address
from hexbytes import HexBytes

from src.providers.keys.typings import ContractModule, LidoKey
from src.services.extra_data import ExtraData

pytestmark = pytest.mark.unit


@pytest.fixture()
def extra_data_service(web3, lido_validators):
    return ExtraData(web3)


def module(id, module_address):
    return ContractModule(nonce=0,
                          type="curated-onchain-v1",
                          id=id,
                          stakingModuleAddress=Address(module_address),
                          name="Test")


def lido_key(op_index, module_address):
    return LidoKey(
        key=HexBytes(b""),
        depositSignature=HexBytes(b""),
        operatorIndex=op_index,
        used=True,
        moduleAddress=Address(module_address),
    )


class TestBuildValidators:
    def test_payload(self, extra_data_service):
        modules = [module(id=1, module_address=b"0x1")]
        lido_keys = [lido_key(op_index=0, module_address=b"0x1"),
                     lido_key(op_index=1, module_address=b"0x1"),
                     lido_key(op_index=1, module_address=b"0x1")]

        payload = extra_data_service.build_validators_payloads(lido_keys, modules, 10)[0]
        assert payload.module_id == b'\x00\x00\x01'
        assert payload.node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        assert payload.node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert payload.vals_counts == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02'

    def test_order(self, extra_data_service, monkeypatch):
        modules = [module(id=2, module_address=b"0x2"), module(id=1, module_address=b"0x1")]
        lido_keys = [lido_key(op_index=0, module_address=b"0x2"),
                     lido_key(op_index=1, module_address=b"0x2"),
                     lido_key(op_index=3, module_address=b"0x1"),
                     lido_key(op_index=3, module_address=b"0x1"),
                     lido_key(op_index=2, module_address=b"0x1"),
                     lido_key(op_index=4, module_address=b"0x1"),
                     lido_key(op_index=5, module_address=b"0x1"),
                     ]

        payloads = extra_data_service.build_validators_payloads(lido_keys, modules, 2)
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x01'
        assert payloads[2].module_id == b'\x00\x00\x02'

        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payloads[1].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x05'
        assert payloads[2].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
