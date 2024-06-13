from unittest.mock import Mock

import pytest

from src.modules.csm.csm import CSOracle
from src.modules.csm.state import AttestationsAggregate, State
from src.types import NodeOperatorId, ValidatorIndex
from src.web3py.extensions.csm import CSM


@pytest.fixture()
def module(web3, csm: CSM):
    yield CSOracle(web3)


def test_init(module: CSOracle):
    assert module


def test_calculate_distribution(module: CSOracle, csm: CSM):
    csm.fee_distributor.shares_to_distribute = Mock(return_value=10_000)
    csm.oracle.perf_leeway = Mock(return_value=0.05)

    module.module_validators_by_node_operators = Mock(
        return_value={
            (None, NodeOperatorId(0)): [Mock(index=0)],
            (None, NodeOperatorId(1)): [Mock(index=1)],
            (None, NodeOperatorId(2)): [Mock(index=2)],  # stuck
            (None, NodeOperatorId(3)): [Mock(index=3)],
            (None, NodeOperatorId(4)): [Mock(index=4)],  # stuck
            (None, NodeOperatorId(5)): [Mock(index=5), Mock(index=6)],
            (None, NodeOperatorId(6)): [Mock(index=7), Mock(index=8)],
            (None, NodeOperatorId(7)): [Mock(index=9)],
        }
    )
    module.stuck_operators = Mock(
        return_value=[
            NodeOperatorId(2),
            NodeOperatorId(4),
        ]
    )

    module.state = State(
        {
            ValidatorIndex(0): AttestationsAggregate(included=200, assigned=200),  # short on frame
            ValidatorIndex(1): AttestationsAggregate(included=1000, assigned=1000),
            ValidatorIndex(2): AttestationsAggregate(included=1000, assigned=1000),
            ValidatorIndex(3): AttestationsAggregate(included=999, assigned=1000),
            ValidatorIndex(4): AttestationsAggregate(included=900, assigned=1000),
            ValidatorIndex(5): AttestationsAggregate(included=500, assigned=1000),  # underperforming
            ValidatorIndex(5): AttestationsAggregate(included=500, assigned=1000),  # underperforming
            ValidatorIndex(6): AttestationsAggregate(included=0, assigned=0),  # underperforming
            ValidatorIndex(7): AttestationsAggregate(included=900, assigned=1000),
            ValidatorIndex(8): AttestationsAggregate(included=500, assigned=1000),  # underperforming
            # ValidatorIndex(9): AttestationsAggregate(included=0, assigned=0),  # missing in state
        }
    )
    _, shares = module.calculate_distribution(blockstamp=Mock())

    assert tuple(shares.items()) == (
        (NodeOperatorId(0), 625),
        (NodeOperatorId(1), 3125),
        (NodeOperatorId(3), 3125),
        (NodeOperatorId(6), 3125),
    )
