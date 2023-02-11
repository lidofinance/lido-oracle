import pytest
from eth_typing import Address

from src.providers.keys.typings import OperatorResponse, ContractModule, Operator
from src.services.extra_data import ExtraData
from src.services import extra_data

pytestmark = pytest.mark.unit


@pytest.fixture()
def extra_data_service(web3, lido_validators):
    return ExtraData(web3)


def module(id):
    return ContractModule(nonce=0,
                          type="curated-onchain-v1",
                          id=id,
                          stakingModuleAddress=Address(b"0x000000"),
                          name="Test")


def operator(index):
    return Operator(index=index,
                    active=True,
                    name="Alex T",
                    rewardAddress=Address(b"0x1C292814671B60a56C4051cAf6E6C5fD583f2ce5"),
                    stakingLimit=0,
                    stoppedValidators=0,
                    totalSigningKeys=0,
                    usedSigningKeys=0
                    )


class TestBuildValidators:
    def test_payload(self, extra_data_service):
        operator_responses = [
            OperatorResponse(module=module(id=1),
                             operators=[
                                 operator(index=0),
                                 operator(index=1),
                             ])
        ]

        payload = extra_data_service.build_validators_payloads(operator_responses)[0]
        assert payload.module_id == b'\x00\x00\x01'
        assert payload.node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        assert payload.node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert payload.stuck_vals_counts == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

    def test_order(self, extra_data_service, monkeypatch):
        monkeypatch.setattr(extra_data, "MAX_EXTRA_DATA_LIST_ITEMS_COUNT", 2)
        operator_responses = [
            OperatorResponse(module=module(id=2),
                             operators=[
                                 operator(index=0),
                                 operator(index=1),
                             ]),
            OperatorResponse(module=module(id=1),
                             operators=[
                                 operator(index=3),
                                 operator(index=2),
                                 operator(index=4),
                                 operator(index=5),

                             ]),
        ]

        payloads = extra_data_service.build_validators_payloads(operator_responses)
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x01'
        assert payloads[2].module_id == b'\x00\x00\x02'

        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payloads[1].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x05'
        assert payloads[2].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
