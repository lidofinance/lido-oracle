import pytest
from hexbytes import HexBytes

from src.modules.accounting.extra_data import ExtraDataService, ExtraData, FormatList
from src.web3py.extensions.lido_validators import NodeOperatorGlobalIndex, LidoValidator


pytestmark = pytest.mark.unit


@pytest.fixture()
def extra_data_service(lido_validators):
    return ExtraDataService()


def node_operator(module_id, node_operator_id) -> NodeOperatorGlobalIndex:
    return module_id, node_operator_id


class TestBuildValidators:
    def test_collect_zero(self, extra_data_service, contracts):
        extra_data = extra_data_service.collect({}, {}, 10, 10)
        assert isinstance(extra_data, ExtraData)
        assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY.value
        assert extra_data.extra_data == b''
        assert extra_data.data_hash == HexBytes(b"\xc5\xd2F\x01\x86\xf7#<\x92~}\xb2\xdc\xc7\x03\xc0\xe5\x00\xb6S\xca\x82';{\xfa\xd8\x04]\x85\xa4p")

    def test_payload(self, extra_data_service):
        vals_payload = {
            node_operator(1, 0): 1,
            node_operator(1, 1): 2,
        }
        payload, rest_items_count = extra_data_service.build_validators_payloads(vals_payload, 10, 10)
        assert payload[0].module_id == b'\x00\x00\x01'
        assert payload[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        assert payload[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert payload[0].vals_counts == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02'

    def test_order(self, extra_data_service, monkeypatch):
        vals_order = {
            node_operator(2, 0): 1,
            node_operator(2, 1): 1,
            node_operator(1, 3): 1,
            node_operator(1, 3): 1,
            node_operator(2, 2): 1,
            node_operator(3, 4): 1,
            node_operator(3, 5): 1,
        }

        payloads, rest_items_count = extra_data_service.build_validators_payloads(vals_order, 4, 10)
        assert len(payloads) == 2
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x02'

        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payloads[1].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02'

    def test_max_items_count(self, extra_data_service):
        """
        nodeOpsCount must not be greater than maxAccountingExtraDataListItemsCount specified
        in OracleReportSanityChecker contract. If a staking module has more node operators
        with total stuck validators counts changed compared to the staking module smart contract
        storage (as observed at the reference slot), reporting for that module should be split
        into multiple items.
        """
        vals_max_items_count = {
            node_operator(1, 0): 1,
            node_operator(1, 1): 1,
            node_operator(1, 1): 2,
            node_operator(1, 2): 1,
            node_operator(1, 2): 2,
            node_operator(1, 2): 3,
        }

        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_max_items_count, 10, 10)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payload_size_limit == 7
        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_max_items_count, 4, 4)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payload_size_limit == 1
        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_max_items_count, 4, 3)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payload_size_limit == 0
        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_max_items_count, 3, 4)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payload_size_limit == 0
        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_max_items_count, 3, 3)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        assert payload_size_limit == 0
        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_max_items_count, 3, 2)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        assert payload_size_limit == 0
        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_max_items_count, 2, 3)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        assert payload_size_limit == 0

    def test_stuck_exited_validators_count_non_zero(self, extra_data_service):
        vals_stuck = {
            node_operator(1, 0): 1,
            node_operator(1, 1): 1,
        }
        vals_exited = {
            node_operator(1, 0): 2,
            node_operator(1, 1): 2,
            node_operator(1, 2): 1,
        }
        stuck_validators_payload, stuck_validators_payload_size_limit = extra_data_service.build_validators_payloads(vals_stuck, 10, 10)
        exited_validators_payload, exited_validators_payload_size_limit = extra_data_service.build_validators_payloads(vals_exited, 10, 10)
        extra_data = extra_data_service.build_extra_data(stuck_validators_payload, exited_validators_payload)
        assert extra_data[0].item_payload.vals_counts == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert extra_data[1].item_payload.vals_counts == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'

    def test_stuck_exited_validators_count_is_empty(self, extra_data_service):
        vals_stuck_empty = {}
        vals_exited_empty = {}

        stuck_validators_payload, stuck_validators_payload_size_limit = extra_data_service.build_validators_payloads(vals_stuck_empty, 10, 10)
        exited_validators_payload, exited_validators_payload_size_limit = extra_data_service.build_validators_payloads(vals_exited_empty, 10, 10)
        extra_data = extra_data_service.build_extra_data(stuck_validators_payload, exited_validators_payload)
        assert extra_data == []

    def test_payload_sorting(self, extra_data_service):
        """
        Items should be sorted ascendingly by the (itemType, ...itemSortingKey) compound key
        where `itemSortingKey` calculation depends on the item's type (see below).
        Item sorting key is a compound key consisting of the module id and the first reported
        node operator's id: itemSortingKey = (moduleId, nodeOperatorIds[0:8])
        """
        vals_correct_order = {
            node_operator(1, 0): 1,
            node_operator(1, 1): 1,
            node_operator(2, 0): 1,
            node_operator(2, 0): 2,
            node_operator(3, 0): 1,
            node_operator(3, 1): 1,
        }

        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_correct_order, 10, 10)
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x02'
        assert payloads[1].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00'
        assert payloads[2].module_id == b'\x00\x00\x03'
        assert payloads[2].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'


        vals_incorrect_order = {
            node_operator(3, 0): 1,
            node_operator(1, 1): 1,
            node_operator(2, 0): 1,
            node_operator(1, 0): 1,
            node_operator(3, 1): 1,
            node_operator(2, 0): 2,
        }

        payloads, payload_size_limit = extra_data_service.build_validators_payloads(vals_incorrect_order, 10, 10)
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x02'
        assert payloads[1].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00'
        assert payloads[2].module_id == b'\x00\x00\x03'
        assert payloads[2].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
