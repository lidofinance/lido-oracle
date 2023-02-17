import pytest
from eth_typing import Address
from hexbytes import HexBytes

from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.providers.keys.typings import LidoKey
from src.modules.accounting.extra_data import ExtraDataService, ExtraData, FormatList
from src.typings import OracleReportLimits
from src.web3py.extentions.lido_validators import NodeOperatorIndex, LidoValidator

pytestmark = pytest.mark.unit


@pytest.fixture()
def extra_data_service(web3, lido_validators):
    return ExtraDataService(web3)


def validator():
    """None of the fields are used in tests"""
    return LidoValidator(
        key=LidoKey(
            key=HexBytes(b""),
            depositSignature=HexBytes(b""),
            operatorIndex=-1,
            used=True,
            moduleAddress=Address(b"")),
        validator=Validator(index="0",
                            balance="0",
                            status=ValidatorStatus.ACTIVE_ONGOING,
                            validator=ValidatorState(pubkey="0x1",
                                                     withdrawal_credentials="0x1",
                                                     effective_balance="0",
                                                     slashed=False,
                                                     activation_eligibility_epoch="0",
                                                     activation_epoch="0",
                                                     exit_epoch="0",
                                                     withdrawable_epoch="0",
                                                     ))

    )


def node_operator(module_id, node_operator_id) -> NodeOperatorIndex:
    return module_id, node_operator_id


class TestBuildValidators:

    def test_oracle_report_limits(self, extra_data_service, contracts):
        limits = extra_data_service._get_oracle_report_limits()
        assert isinstance(limits, OracleReportLimits)

    def test_collect_zero(self, extra_data_service, contracts):
        extra_data = extra_data_service.collect({}, {})
        assert isinstance(extra_data, ExtraData)
        assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY
        assert extra_data.extra_data == b''
        assert extra_data.data_hash == HexBytes(b"\xc5\xd2F\x01\x86\xf7#<\x92~}\xb2\xdc\xc7\x03\xc0\xe5\x00\xb6S\xca\x82';{\xfa\xd8\x04]\x85\xa4p")

    def test_payload(self, extra_data_service):
        vals = {
            node_operator(1, 0): [validator()],
            node_operator(1, 1): [validator(), validator()],
        }
        payload = extra_data_service.build_validators_payloads(vals, 10)[0]
        assert payload.module_id == b'\x00\x00\x01'
        assert payload.node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        assert payload.node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert payload.vals_counts == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02'

    def test_order(self, extra_data_service, monkeypatch):
        vals = {
            node_operator(2, 0): [validator()],
            node_operator(2, 1): [validator()],
            node_operator(1, 3): [validator()],
            node_operator(1, 3): [validator()],
            node_operator(1, 2): [validator()],
            node_operator(1, 4): [validator()],
            node_operator(1, 5): [validator()],
        }

        payloads = extra_data_service.build_validators_payloads(vals, 2)
        assert len(payloads) == 3
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x01'
        assert payloads[2].module_id == b'\x00\x00\x02'

        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payloads[1].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x05'
        assert payloads[2].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
