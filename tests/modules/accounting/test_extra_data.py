import pytest
from hexbytes import HexBytes

from src.modules.accounting.third_phase.extra_data import ExtraDataService
from src.modules.accounting.third_phase.types import FormatList, ExtraData
from src.web3py.extensions.lido_validators import NodeOperatorGlobalIndex


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
        assert not extra_data.extra_data_list
        assert extra_data.data_hash == HexBytes('0x0000000000000000000000000000000000000000000000000000000000000000')

    def test_collect_non_zero(self, extra_data_service):
        vals_stuck_non_zero = {
            node_operator(1, 0): 1,
        }
        vals_exited_non_zero = {
            node_operator(1, 0): 2,
        }
        extra_data = extra_data_service.collect(vals_stuck_non_zero, vals_exited_non_zero, 10, 10)
        assert isinstance(extra_data, ExtraData)
        assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value
        assert len(extra_data.extra_data_list) == 1
        assert (
            extra_data.extra_data_list[0]
            == b'\x00\x00\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x01\x00\x02\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02'
        )
        assert extra_data.data_hash == HexBytes(
            b"\x1a\xa3\x94\x9dqI\xcb\xd9y\xbf\xabG\x8d\xeb\xb1j\x91\x8b\xce\xd9\xda;!x*aPk\xf5^\x19\xd1"
        )

    def test_payload(self, extra_data_service):
        vals_payload = {
            node_operator(1, 0): 1,
            node_operator(1, 1): 2,
        }
        payload = extra_data_service.build_validators_payloads(vals_payload, 10)
        assert payload[0].module_id == b'\x00\x00\x01'
        assert payload[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        assert payload[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert (
            payload[0].vals_counts
            == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02'
        )

    def test_collect_stuck_vals_in_cap(self, extra_data_service):
        vals_stuck_non_zero = {
            node_operator(1, 0): 1,
            node_operator(1, 1): 1,
        }
        vals_exited_non_zero = {
            node_operator(1, 0): 2,
        }
        extra_data = extra_data_service.collect(vals_stuck_non_zero, vals_exited_non_zero, 1, 2)
        assert isinstance(extra_data, ExtraData)
        assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value
        assert len(extra_data.extra_data_list) == 1
        assert (
            extra_data.extra_data_list[0]
            == b'\x00\x00\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        )
        assert extra_data.data_hash == HexBytes(
            b'\xc7\x98\xd9\xa9\xe1A\xfe\x19\xc6"\xa0\xa0\xa3\x89N\xe3r\xfc\xff\xe6L\x08+K\x9doa\xabF\xc3\x0cs'
        )

        # |  3 bytes  | 2 bytes  | 3 bytes  |   8 bytes    |  nodeOpsCount * 8 bytes  |  nodeOpsCount * 16 bytes  |
        # | itemIndex | itemType | moduleId | nodeOpsCount |      nodeOperatorIds     |   stuckOrExitedValsCount  |
        # Expecting only one module with two no
        item_length = 3 + 2 + 3 + 8
        no_payload_length = 8 + 16
        # Expecting one module
        assert len(extra_data.extra_data_list[0]) == item_length + no_payload_length * 2
        # Expecting two modules
        extra_data = extra_data_service.collect(vals_stuck_non_zero, vals_exited_non_zero, 2, 2)
        assert (
            len(extra_data.extra_data_list[0]) == item_length + no_payload_length * 2 + item_length + no_payload_length
        )

    def test_order(self, extra_data_service, monkeypatch):
        vals_order = {
            node_operator(2, 0): 1,
            node_operator(2, 1): 1,
            node_operator(1, 3): 1,
            node_operator(2, 2): 1,
            node_operator(3, 4): 1,
            node_operator(3, 5): 1,
        }

        payloads = extra_data_service.build_validators_payloads(vals_order, 4)
        assert len(payloads) == 3
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x02'
        assert payloads[2].module_id == b'\x00\x00\x03'

        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        assert (
            payloads[1].node_operator_ids
            == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02'
        )

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
            node_operator(1, 2): 1,
        }

        payloads = extra_data_service.build_validators_payloads(vals_max_items_count, 3)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x03'
        payloads = extra_data_service.build_validators_payloads(vals_max_items_count, 2)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x02'
        payloads = extra_data_service.build_validators_payloads(vals_max_items_count, 1)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x01'
        payloads = extra_data_service.build_validators_payloads(vals_max_items_count, 0)
        assert payloads[0].node_ops_count == b'\x00\x00\x00\x00\x00\x00\x00\x00'

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
        stuck_validators_payload = extra_data_service.build_validators_payloads(vals_stuck, 10)
        exited_validators_payload = extra_data_service.build_validators_payloads(vals_exited, 10)
        extra_data = extra_data_service.build_extra_data(stuck_validators_payload, exited_validators_payload, 10)
        assert (
            extra_data[0].item_payload.vals_counts
            == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        )
        assert (
            extra_data[1].item_payload.vals_counts
            == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        )

    def test_stuck_exited_validators_count_is_empty(self, extra_data_service):
        vals_stuck_empty = {}
        vals_exited_empty = {}

        stuck_validators_payload = extra_data_service.build_validators_payloads(vals_stuck_empty, 10)
        exited_validators_payload = extra_data_service.build_validators_payloads(vals_exited_empty, 10)
        extra_data = extra_data_service.build_extra_data(stuck_validators_payload, exited_validators_payload, 10)
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
            node_operator(3, 0): 1,
            node_operator(3, 1): 1,
        }

        payloads = extra_data_service.build_validators_payloads(vals_correct_order, 10)
        self._check_payloads(payloads)

        vals_incorrect_order = {
            node_operator(3, 0): 1,
            node_operator(1, 1): 1,
            node_operator(2, 0): 1,
            node_operator(1, 0): 1,
            node_operator(3, 1): 1,
        }

        payloads = extra_data_service.build_validators_payloads(vals_incorrect_order, 10)
        self._check_payloads(payloads)

    @staticmethod
    def _check_payloads(payloads):
        assert payloads[0].module_id == b'\x00\x00\x01'
        assert payloads[0].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        assert payloads[1].module_id == b'\x00\x00\x02'
        assert payloads[1].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00'
        assert payloads[2].module_id == b'\x00\x00\x03'
        assert payloads[2].node_operator_ids == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
