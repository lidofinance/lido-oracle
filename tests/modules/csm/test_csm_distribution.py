import re
from collections import defaultdict
from unittest.mock import Mock

import pytest
from hexbytes import HexBytes
from web3.types import Wei

from src.constants import TOTAL_BASIS_POINTS
from src.modules.csm.distribution import Distribution, ValidatorDuties, ValidatorDutiesOutcome
from src.modules.csm.log import FramePerfLog, ValidatorFrameSummary, OperatorFrameSummary
from src.modules.csm.state import DutyAccumulator, State, NetworkDuties, Frame
from src.modules.csm.types import StrikesList
from src.providers.execution.contracts.cs_fee_distributor import CSFeeDistributorContract
from src.providers.execution.contracts.cs_parameters_registry import (
    StrikesParams,
    PerformanceCoefficients,
    CurveParams,
    KeyNumberValueInterval,
    KeyNumberValueIntervalList,
)
from src.providers.execution.exceptions import InconsistentData
from src.types import NodeOperatorId, EpochNumber, ValidatorIndex, ReferenceBlockStamp
from src.web3py.extensions import CSM
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


@pytest.mark.parametrize(
    (
        "frames",
        "last_report",
        "mocked_curve_params",
        "frame_blockstamps",
        "shares_to_distribute",
        "distribution_in_frame",
        "expected_total_rewards",
        "expected_total_rewards_map",
        "expected_total_rebate",
        "expected_strikes",
    ),
    [
        # One frame
        (
            [(0, 31)],
            Mock(
                strikes={(NodeOperatorId(1), HexBytes("0x01")): StrikesList([1, 0, 0, 0, 1, 1])},
                rewards=[(NodeOperatorId(1), 500)],
            ),
            Mock(
                return_value=CurveParams(
                    strikes_params=StrikesParams(lifetime=6, threshold=...),
                    perf_leeway_data=...,
                    reward_share_data=...,
                    perf_coeffs=...,
                )
            ),
            [ReferenceBlockStampFactory.build(ref_epoch=31)],
            [500],
            [
                (
                    # rewards
                    {NodeOperatorId(1): 500},
                    # distributed_rewards
                    500,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {(NodeOperatorId(1), HexBytes("0x01")): 1},
                )
            ],
            500,
            {NodeOperatorId(1): 1000},
            0,
            {(NodeOperatorId(1), HexBytes("0x01")): [1, 1, 0, 0, 0, 1]},
        ),
        # One frame, no strikes and rewards before
        (
            [(0, 31)],
            Mock(strikes={}, rewards=[]),
            Mock(
                return_value=CurveParams(
                    strikes_params=StrikesParams(lifetime=6, threshold=...),
                    perf_leeway_data=...,
                    reward_share_data=...,
                    perf_coeffs=...,
                )
            ),
            [ReferenceBlockStampFactory.build(ref_epoch=31)],
            [500],
            [
                (
                    # rewards
                    {NodeOperatorId(1): 500},
                    # distributed_rewards
                    500,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {(NodeOperatorId(1), HexBytes("0x01")): 1},
                )
            ],
            500,
            {NodeOperatorId(1): 500},
            0,
            {(NodeOperatorId(1), HexBytes("0x01")): [1, 0, 0, 0, 0, 0]},
        ),
        # Multiple frames
        (
            [(0, 31), (32, 63), (64, 95)],
            Mock(
                strikes={
                    (NodeOperatorId(1), HexBytes("0x01")): StrikesList([1, 0, 0, 0, 1, 1]),
                    (NodeOperatorId(100500), HexBytes("0x100500")): StrikesList([0, 0, 0, 1, 1, 1]),
                },
                rewards=[(NodeOperatorId(1), 500)],
            ),
            Mock(
                return_value=CurveParams(
                    strikes_params=StrikesParams(lifetime=6, threshold=...),
                    perf_leeway_data=...,
                    reward_share_data=...,
                    perf_coeffs=...,
                )
            ),
            [
                ReferenceBlockStampFactory.build(ref_epoch=31),
                ReferenceBlockStampFactory.build(ref_epoch=63),
                ReferenceBlockStampFactory.build(ref_epoch=95),
            ],
            [
                500,
                500 + 700,
                500 + 700 + 300,
            ],
            [
                (
                    # rewards
                    {NodeOperatorId(1): 500},
                    # distributed_rewards
                    500,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {(NodeOperatorId(1), HexBytes("0x01")): 1},
                ),
                (
                    # rewards
                    {NodeOperatorId(1): 700},
                    # distributed_rewards
                    700,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {(NodeOperatorId(2), HexBytes("0x02")): 1},
                ),
                (
                    # rewards
                    {NodeOperatorId(1): 300},
                    # distributed_rewards
                    300,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {},
                ),
            ],
            1500,
            {NodeOperatorId(1): 2000},
            0,
            {
                (NodeOperatorId(1), HexBytes("0x01")): [0, 0, 1, 1, 0, 0],
                (NodeOperatorId(2), HexBytes("0x02")): [0, 1, 0, 0, 0, 0],
            },
        ),
        # One frame with no distribution
        (
            [(0, 31)],
            Mock(
                strikes={(NodeOperatorId(1), HexBytes("0x01")): StrikesList([1, 0, 0, 0, 1, 1])},
                rewards=[(NodeOperatorId(1), 500)],
            ),
            Mock(
                return_value=CurveParams(
                    strikes_params=StrikesParams(lifetime=6, threshold=...),
                    perf_leeway_data=...,
                    reward_share_data=...,
                    perf_coeffs=...,
                )
            ),
            [ReferenceBlockStampFactory.build(ref_epoch=31)],
            [500],
            [
                (
                    # rewards
                    {},
                    # distributed_rewards
                    0,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {(NodeOperatorId(1), HexBytes("0x01")): 1},
                )
            ],
            0,
            {NodeOperatorId(1): 500},
            0,
            {(NodeOperatorId(1), HexBytes("0x01")): [1, 1, 0, 0, 0, 1]},
        ),
        # Multiple frames, some of which are not distributed
        (
            [(0, 31), (32, 63), (64, 95)],
            Mock(
                strikes={
                    (NodeOperatorId(1), HexBytes("0x01")): StrikesList([1, 0, 0, 0, 1, 1]),
                    (NodeOperatorId(100500), HexBytes("0x100500")): StrikesList([0, 0, 0, 1, 1, 1]),
                },
                rewards=[(NodeOperatorId(1), 500)],
            ),
            Mock(
                return_value=CurveParams(
                    strikes_params=StrikesParams(lifetime=6, threshold=...),
                    perf_leeway_data=...,
                    reward_share_data=...,
                    perf_coeffs=...,
                )
            ),
            [
                ReferenceBlockStampFactory.build(ref_epoch=31),
                ReferenceBlockStampFactory.build(ref_epoch=63),
                ReferenceBlockStampFactory.build(ref_epoch=95),
            ],
            [
                500,
                500 + 700,
                500 + 700 + 300,
            ],
            [
                (
                    # rewards
                    {},
                    # distributed_rewards
                    0,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {(NodeOperatorId(1), HexBytes("0x01")): 1},
                ),
                (
                    # rewards
                    {NodeOperatorId(1): 500 + 700},
                    # distributed_rewards
                    500 + 700,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {(NodeOperatorId(2), HexBytes("0x02")): 1},
                ),
                (
                    # rewards
                    {},
                    # distributed_rewards
                    0,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {},
                ),
            ],
            500 + 700,
            {NodeOperatorId(1): 500 + 500 + 700},
            0,
            {
                (NodeOperatorId(1), HexBytes("0x01")): [0, 0, 1, 1, 0, 0],
                (NodeOperatorId(2), HexBytes("0x02")): [0, 1, 0, 0, 0, 0],
            },
        ),
    ],
)
@pytest.mark.unit
def test_calculate_distribution(
    frames: list[Frame],
    last_report,
    mocked_curve_params,
    frame_blockstamps,
    shares_to_distribute,
    distribution_in_frame,
    expected_total_rewards,
    expected_total_rewards_map,
    expected_total_rebate,
    expected_strikes,
):
    # Mocking the data from EL
    w3 = Mock(spec=Web3, csm=Mock(spec=CSM, fee_distributor=Mock(spec=CSFeeDistributorContract)))
    w3.csm.fee_distributor.shares_to_distribute = Mock(side_effect=shares_to_distribute)
    w3.csm.get_curve_params = mocked_curve_params

    distribution = Distribution(w3, converter=..., state=State())
    distribution._get_module_validators = Mock(...)
    distribution.state.data = {f: {} for f in frames}
    distribution._get_frame_blockstamp = Mock(side_effect=frame_blockstamps)
    distribution._calculate_distribution_in_frame = Mock(side_effect=distribution_in_frame)

    result = distribution.calculate(blockstamp=..., last_report=last_report)

    assert result.total_rewards == expected_total_rewards
    assert result.total_rewards_map == expected_total_rewards_map
    assert result.total_rebate == expected_total_rebate
    assert result.strikes == expected_strikes

    assert len(result.logs) == len(frames)
    for i, log in enumerate(result.logs):
        assert log.blockstamp == frame_blockstamps[i]
        assert log.frame == frames[i]


@pytest.mark.unit
def test_calculate_distribution_handles_invalid_distribution():
    # Mocking the data from EL
    w3 = Mock(spec=Web3, csm=Mock(spec=CSM, fee_distributor=Mock(spec=CSFeeDistributorContract)))
    w3.csm.fee_distributor.shares_to_distribute = Mock(return_value=500)
    w3.csm.get_curve_params = Mock(...)

    distribution = Distribution(w3, converter=..., state=State())
    distribution._get_module_validators = Mock(...)
    distribution.state.data = {(EpochNumber(0), EpochNumber(31)): {}}
    distribution._get_frame_blockstamp = Mock(return_value=ReferenceBlockStampFactory.build(ref_epoch=31))
    distribution._calculate_distribution_in_frame = Mock(
        return_value=(
            # rewards
            {NodeOperatorId(1): 500},
            # distributed_rewards
            500,
            # rebate_to_protocol
            1,
            # strikes
            {},
        )
    )

    with pytest.raises(ValueError, match=re.escape("Invalid distribution: 500 + 1 > 500")):
        distribution.calculate(..., Mock(strikes={}, rewards=[]))


@pytest.mark.unit
def test_calculate_distribution_handles_invalid_distribution_in_total():
    # Mocking the data from EL
    w3 = Mock(spec=Web3, csm=Mock(spec=CSM, fee_distributor=Mock(spec=CSFeeDistributorContract)))
    w3.csm.fee_distributor.shares_to_distribute = Mock(return_value=500)
    w3.csm.get_curve_params = Mock(...)

    distribution = Distribution(w3, converter=..., state=State())
    distribution._get_module_validators = Mock(...)
    distribution.state.data = {(EpochNumber(0), EpochNumber(31)): {}}
    distribution._get_frame_blockstamp = Mock(return_value=ReferenceBlockStampFactory.build(ref_epoch=31))
    distribution._calculate_distribution_in_frame = Mock(
        return_value=(
            # rewards
            {NodeOperatorId(1): 500},
            # distributed_rewards
            400,
            # rebate_to_protocol
            1,
            # strikes
            {},
        )
    )

    with pytest.raises(InconsistentData, match="Invalid distribution"):
        distribution.calculate(..., Mock(strikes={}, rewards=[]))


@pytest.mark.parametrize(
    (
        "to_distribute",
        "frame_validators",
        "frame_state_data",
        "mocked_curve_params",
        "expected_rewards_distribution_map",
        "expected_distributed_rewards",
        "expected_rebate_to_protocol",
        "expected_frame_strikes",
        "expected_log",
    ),
    [
        # All above threshold performance
        (
            100,
            {
                (..., NodeOperatorId(1)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(1), validator=ValidatorStateFactory.build(slashed=False)
                    ),
                ],
            },
            NetworkDuties(
                attestations=defaultdict(
                    DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(assigned=10, included=6)}
                ),
                proposals=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(assigned=10, included=6)}),
                syncs=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(assigned=10, included=6)}),
            ),
            Mock(
                return_value=CurveParams(
                    strikes_params=...,
                    perf_leeway_data=Mock(get_for=Mock(return_value=0.1)),
                    reward_share_data=Mock(get_for=Mock(return_value=1)),
                    perf_coeffs=PerformanceCoefficients(),
                )
            ),
            # Expected:
            # Rewards map
            {
                NodeOperatorId(1): 100,
            },
            # Distributed rewards
            100,
            # Rebate to protocol
            0,
            # Strikes
            {},
            FramePerfLog(
                blockstamp=...,
                frame=...,
                distributable=100,
                distributed_rewards=100,
                rebate_to_protocol=0,
                operators={
                    NodeOperatorId(1): OperatorFrameSummary(
                        distributed_rewards=100,
                        performance_coefficients=PerformanceCoefficients(),
                        validators={
                            ValidatorIndex(1): ValidatorFrameSummary(
                                distributed_rewards=100,
                                performance=0.6,
                                threshold=0.5,
                                rewards_share=1.0,
                                slashed=False,
                                strikes=0,
                                attestation_duty=DutyAccumulator(assigned=10, included=6),
                                proposal_duty=DutyAccumulator(assigned=10, included=6),
                                sync_duty=DutyAccumulator(assigned=10, included=6),
                            )
                        },
                    )
                },
            ),
        ),
        # All below threshold performance
        (
            100,
            {
                (..., NodeOperatorId(1)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(1), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x01")
                    ),
                ],
            },
            NetworkDuties(
                attestations=defaultdict(
                    DutyAccumulator,
                    {
                        ValidatorIndex(1): DutyAccumulator(assigned=10, included=5),
                        ValidatorIndex(2): DutyAccumulator(assigned=10, included=10),
                    },
                ),
                proposals=defaultdict(
                    DutyAccumulator,
                    {
                        ValidatorIndex(1): DutyAccumulator(assigned=10, included=5),
                        ValidatorIndex(2): DutyAccumulator(assigned=10, included=10),
                    },
                ),
                syncs=defaultdict(
                    DutyAccumulator,
                    {
                        ValidatorIndex(1): DutyAccumulator(assigned=10, included=5),
                        ValidatorIndex(2): DutyAccumulator(assigned=10, included=10),
                    },
                ),
            ),
            Mock(
                return_value=CurveParams(
                    strikes_params=...,
                    perf_leeway_data=Mock(get_for=Mock(return_value=0.1)),
                    reward_share_data=Mock(get_for=Mock(return_value=1)),
                    perf_coeffs=PerformanceCoefficients(),
                )
            ),
            # Expected:
            # Distribution map
            {},
            # Distributed rewards
            0,
            # Rebate to protocol
            0,
            # Strikes
            {
                (NodeOperatorId(1), HexBytes('0x01')): 1,
            },
            FramePerfLog(
                blockstamp=...,
                frame=...,
                distributable=100,
                distributed_rewards=0,
                rebate_to_protocol=0,
                operators={
                    NodeOperatorId(1): OperatorFrameSummary(
                        distributed_rewards=0,
                        performance_coefficients=PerformanceCoefficients(),
                        validators={
                            ValidatorIndex(1): ValidatorFrameSummary(
                                performance=0.5,
                                threshold=0.65,
                                rewards_share=1.0,
                                slashed=False,
                                strikes=1,
                                attestation_duty=DutyAccumulator(assigned=10, included=5),
                                proposal_duty=DutyAccumulator(assigned=10, included=5),
                                sync_duty=DutyAccumulator(assigned=10, included=5),
                            )
                        },
                    )
                },
            ),
        ),
        #  Mixed. With custom threshold and reward share
        (
            100,
            {
                # Operator 1. One above threshold performance, one slashed
                (..., NodeOperatorId(1)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(1), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x01")
                    ),
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(2), validator=ValidatorStateFactory.build(slashed=True, pubkey="0x02")
                    ),
                ],
                # Operator 2. One above threshold performance, one below
                (..., NodeOperatorId(2)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(3), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x03")
                    ),
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(4), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x04")
                    ),
                ],
                # Operator 3. All below threshold performance
                (..., NodeOperatorId(3)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(5), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x05")
                    ),
                ],
                # Operator 4. No duties
                (..., NodeOperatorId(4)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(6), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x06")
                    ),
                ],
                # Operator 5. All above threshold performance
                (..., NodeOperatorId(5)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(7), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x07")
                    ),
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(8), validator=ValidatorStateFactory.build(slashed=False, pubkey="0x08")
                    ),
                ],
            },
            NetworkDuties(
                attestations=defaultdict(
                    DutyAccumulator,
                    {
                        ValidatorIndex(1): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(2): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(3): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(4): DutyAccumulator(assigned=10, included=0),
                        ValidatorIndex(5): DutyAccumulator(assigned=10, included=0),
                        ValidatorIndex(7): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(8): DutyAccumulator(assigned=10, included=10),
                        # Network validator
                        ValidatorIndex(100500): DutyAccumulator(assigned=1000, included=1000),
                    },
                ),
                proposals=defaultdict(
                    DutyAccumulator,
                    {
                        ValidatorIndex(1): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(4): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(7): DutyAccumulator(assigned=10, included=10),
                        # Network validator
                        ValidatorIndex(100500): DutyAccumulator(assigned=1000, included=1000),
                    },
                ),
                syncs=defaultdict(
                    DutyAccumulator,
                    {
                        ValidatorIndex(2): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(3): DutyAccumulator(assigned=10, included=10),
                        ValidatorIndex(8): DutyAccumulator(assigned=10, included=10),
                        # Network validator
                        ValidatorIndex(100500): DutyAccumulator(assigned=1000, included=1000),
                    },
                ),
            ),
            Mock(
                side_effect=lambda no_id, _: {
                    NodeOperatorId(5): CurveParams(
                        strikes_params=...,
                        perf_leeway_data=KeyNumberValueIntervalList(
                            [KeyNumberValueInterval(1, 1000), KeyNumberValueInterval(2, 2000)]
                        ),
                        reward_share_data=KeyNumberValueIntervalList(
                            [KeyNumberValueInterval(1, 10000), KeyNumberValueInterval(2, 9000)]
                        ),
                        perf_coeffs=PerformanceCoefficients(attestations_weight=1, blocks_weight=0, sync_weight=0),
                    ),
                }.get(
                    no_id,
                    CurveParams(
                        strikes_params=...,
                        perf_leeway_data=Mock(get_for=Mock(return_value=0.1)),
                        reward_share_data=Mock(get_for=Mock(return_value=1)),
                        perf_coeffs=PerformanceCoefficients(),
                    ),
                ),
            ),
            # Expected:
            # Distribution map
            {
                NodeOperatorId(1): 25,
                NodeOperatorId(2): 25,
                NodeOperatorId(5): 47,
            },
            # Distributed rewards
            97,
            # Rebate to protocol
            3,
            # Strikes
            {
                (NodeOperatorId(1), HexBytes('0x02')): 1,  # Slashed
                (NodeOperatorId(2), HexBytes('0x04')): 1,  # Below threshold
                (NodeOperatorId(3), HexBytes('0x05')): 1,  # Below threshold
            },
            FramePerfLog(
                blockstamp=...,
                frame=...,
                distributable=100,
                distributed_rewards=97,
                rebate_to_protocol=3,
                operators=defaultdict(
                    OperatorFrameSummary,
                    {
                        NodeOperatorId(1): OperatorFrameSummary(
                            distributed_rewards=25,
                            performance_coefficients=PerformanceCoefficients(),
                            validators=defaultdict(
                                ValidatorFrameSummary,
                                {
                                    ValidatorIndex(1): ValidatorFrameSummary(
                                        distributed_rewards=25,
                                        performance=1.0,
                                        threshold=0.8842289719626168,
                                        rewards_share=1,
                                        attestation_duty=DutyAccumulator(assigned=10, included=10),
                                        proposal_duty=DutyAccumulator(assigned=10, included=10),
                                    ),
                                    ValidatorIndex(2): ValidatorFrameSummary(
                                        slashed=True,
                                        strikes=1,
                                    ),
                                },
                            ),
                        ),
                        NodeOperatorId(2): OperatorFrameSummary(
                            distributed_rewards=25,
                            performance_coefficients=PerformanceCoefficients(),
                            validators=defaultdict(
                                ValidatorFrameSummary,
                                {
                                    ValidatorIndex(3): ValidatorFrameSummary(
                                        distributed_rewards=25,
                                        performance=1.0,
                                        threshold=0.8842289719626168,
                                        rewards_share=1,
                                        attestation_duty=DutyAccumulator(assigned=10, included=10),
                                        sync_duty=DutyAccumulator(assigned=10, included=10),
                                    ),
                                    ValidatorIndex(4): ValidatorFrameSummary(
                                        distributed_rewards=0,
                                        performance=0.12903225806451613,
                                        threshold=0.8842289719626168,
                                        rewards_share=1,
                                        strikes=1,
                                        attestation_duty=DutyAccumulator(assigned=10, included=0),
                                        proposal_duty=DutyAccumulator(assigned=10, included=10),
                                    ),
                                },
                            ),
                        ),
                        NodeOperatorId(3): OperatorFrameSummary(
                            distributed_rewards=0,
                            performance_coefficients=PerformanceCoefficients(),
                            validators=defaultdict(
                                ValidatorFrameSummary,
                                {
                                    ValidatorIndex(5): ValidatorFrameSummary(
                                        performance=0.0,
                                        threshold=0.8842289719626168,
                                        rewards_share=1,
                                        strikes=1,
                                        attestation_duty=DutyAccumulator(assigned=10, included=0),
                                    ),
                                },
                            ),
                        ),
                        NodeOperatorId(5): OperatorFrameSummary(
                            distributed_rewards=47,
                            performance_coefficients=PerformanceCoefficients(
                                attestations_weight=1,
                                blocks_weight=0,
                                sync_weight=0,
                            ),
                            validators=defaultdict(
                                ValidatorFrameSummary,
                                {
                                    ValidatorIndex(7): ValidatorFrameSummary(
                                        distributed_rewards=25,
                                        performance=1.0,
                                        threshold=0.8842289719626168,
                                        rewards_share=1.0,
                                        slashed=False,
                                        strikes=0,
                                        attestation_duty=DutyAccumulator(assigned=10, included=10),
                                        proposal_duty=DutyAccumulator(assigned=10, included=10),
                                    ),
                                    ValidatorIndex(8): ValidatorFrameSummary(
                                        distributed_rewards=22,
                                        performance=1.0,
                                        threshold=0.7842289719626168,
                                        rewards_share=0.9,
                                        slashed=False,
                                        strikes=0,
                                        attestation_duty=DutyAccumulator(assigned=10, included=10),
                                        sync_duty=DutyAccumulator(assigned=10, included=10),
                                    ),
                                },
                            ),
                        ),
                    },
                ),
            ),
        ),
        # No duties
        (
            100,
            {
                (..., NodeOperatorId(1)): [
                    LidoValidatorFactory.build(
                        index=ValidatorIndex(1), validator=ValidatorStateFactory.build(slashed=False)
                    ),
                ],
            },
            NetworkDuties(),
            Mock(
                return_value=CurveParams(
                    strikes_params=...,
                    perf_leeway_data=Mock(get_for=Mock(return_value=0.1)),
                    reward_share_data=Mock(get_for=Mock(return_value=1)),
                    perf_coeffs=PerformanceCoefficients(),
                )
            ),
            # Expected:
            # Distribution map
            {},
            # Distributed rewards
            0,
            # Rebate to protocol
            0,
            # Strikes
            {},
            FramePerfLog(
                blockstamp=...,
                frame=...,
                distributable=100,
                distributed_rewards=0,
                rebate_to_protocol=0,
                operators={},
            ),
        ),
    ],
)
@pytest.mark.unit
def test_calculate_distribution_in_frame(
    to_distribute,
    frame_validators,
    frame_state_data,
    mocked_curve_params,
    expected_rewards_distribution_map,
    expected_distributed_rewards,
    expected_rebate_to_protocol,
    expected_frame_strikes,
    expected_log,
):
    log = FramePerfLog(blockstamp=..., frame=...)
    # Mocking the data from EL
    w3 = Mock(spec=Web3, csm=Mock(spec=CSM))
    w3.csm.get_curve_params = mocked_curve_params

    frame = (EpochNumber(0), EpochNumber(31))
    state = State()
    state.migrate(*frame, epochs_per_frame=32)
    state.data = {frame: frame_state_data}

    distribution = Distribution(w3, converter=..., state=state)

    (rewards_distribution, distributed_rewards, rebate_to_protocol, strikes_in_frame) = (
        distribution._calculate_distribution_in_frame(
            frame,
            blockstamp=...,
            rewards_to_distribute=to_distribute,
            operators_to_validators=frame_validators,
            log=log,
        )
    )

    assert dict(rewards_distribution) == expected_rewards_distribution_map
    assert distributed_rewards == expected_distributed_rewards
    assert rebate_to_protocol == expected_rebate_to_protocol
    assert strikes_in_frame == expected_frame_strikes
    assert log == expected_log


@pytest.mark.parametrize(
    "att_perf, prop_perf, sync_perf, expected",
    [
        (1.0, 1.0, 1.0, 1.0),
        (0.0, 0.0, 0.0, 0.0),
        (0.5, 0.5, 0.5, 0.5),
        (0.9, None, 0.7, pytest.approx(0.8928, rel=1e-4)),
        (0.95, None, None, 0.95),
        (0.95, 0.5, None, pytest.approx(0.8919, rel=1e-4)),
        (0.95, None, 0.7, pytest.approx(0.9410, rel=1e-4)),
        (0.95, 0.5, 0.7, pytest.approx(0.8859, rel=1e-4)),
    ],
)
@pytest.mark.unit
def test_get_network_performance(att_perf, prop_perf, sync_perf, expected):
    distribution = Distribution(Mock(), Mock(), Mock())
    distribution.state.get_att_network_aggr = Mock(return_value=Mock(perf=att_perf) if att_perf is not None else None)
    distribution.state.get_prop_network_aggr = Mock(
        return_value=Mock(perf=prop_perf) if prop_perf is not None else None
    )
    distribution.state.get_sync_network_aggr = Mock(
        return_value=Mock(perf=sync_perf) if sync_perf is not None else None
    )
    frame = Mock(spec=Frame)

    result = distribution._get_network_performance(frame)

    assert result == expected


@pytest.mark.unit
def test_get_network_performance_raises_error_for_invalid_performance():
    distribution = Distribution(Mock(), Mock(), Mock())
    distribution.state.get_att_network_aggr = Mock(return_value=Mock(perf=1.1))
    distribution.state.get_prop_network_aggr = Mock(return_value=Mock(perf=1.0))
    distribution.state.get_sync_network_aggr = Mock(return_value=Mock(perf=1.0))
    frame = Mock(spec=Frame)

    with pytest.raises(ValueError, match="Invalid performance: performance"):
        distribution._get_network_performance(frame)


@pytest.mark.parametrize(
    "validator_duties, is_slashed, threshold, reward_share, expected_outcome",
    [
        (
            ValidatorDuties(
                attestation=DutyAccumulator(assigned=10, included=6),
                proposal=DutyAccumulator(assigned=10, included=6),
                sync=DutyAccumulator(assigned=10, included=6),
            ),
            False,
            0.5,
            1,
            ValidatorDutiesOutcome(participation_share=10, rebate_share=0, strikes=0),
        ),
        (
            ValidatorDuties(
                attestation=DutyAccumulator(assigned=10, included=4),
                proposal=DutyAccumulator(assigned=10, included=4),
                sync=DutyAccumulator(assigned=10, included=4),
            ),
            False,
            0.5,
            1,
            ValidatorDutiesOutcome(participation_share=0, rebate_share=0, strikes=1),
        ),
        (
            ValidatorDuties(attestation=None, proposal=None, sync=None),
            False,
            0.5,
            1,
            ValidatorDutiesOutcome(participation_share=0, rebate_share=0, strikes=0),
        ),
        (
            ValidatorDuties(
                attestation=DutyAccumulator(assigned=1, included=1),
                proposal=DutyAccumulator(assigned=1, included=1),
                sync=DutyAccumulator(assigned=1, included=1),
            ),
            True,
            0.5,
            1,
            ValidatorDutiesOutcome(participation_share=0, rebate_share=0, strikes=1),
        ),
    ],
)
@pytest.mark.unit
def test_process_validator_duty(validator_duties, is_slashed, threshold, reward_share, expected_outcome):
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = is_slashed
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)

    outcome = Distribution.get_validator_duties_outcome(
        validator,
        validator_duties,
        threshold,
        reward_share,
        PerformanceCoefficients(),
        log_operator,
    )

    assert outcome == expected_outcome
    if validator_duties.attestation and not is_slashed:
        assert log_operator.validators[validator.index].threshold == threshold
        assert log_operator.validators[validator.index].rewards_share == reward_share
        if validator_duties.attestation:
            assert log_operator.validators[validator.index].attestation_duty == validator_duties.attestation
        if validator_duties.proposal:
            assert log_operator.validators[validator.index].proposal_duty == validator_duties.proposal
        if validator_duties.sync:
            assert log_operator.validators[validator.index].sync_duty == validator_duties.sync

    if not validator_duties.attestation:
        assert validator.index not in log_operator.validators

    assert log_operator.validators[validator.index].slashed is is_slashed


@pytest.mark.parametrize(
    "participation_shares, rewards_to_distribute, rebate_share, expected_distribution",
    [
        (
            {NodeOperatorId(1): {ValidatorIndex(0): 100}, NodeOperatorId(2): {ValidatorIndex(1): 200}},
            Wei(1 * 10**18),
            0,
            {NodeOperatorId(1): Wei(333333333333333333), NodeOperatorId(2): Wei(666666666666666666)},
        ),
        (
            {NodeOperatorId(1): {ValidatorIndex(0): 0}, NodeOperatorId(2): {ValidatorIndex(1): 0}},
            Wei(1 * 10**18),
            0,
            {},
        ),
        (
            {},
            Wei(1 * 10**18),
            0,
            {},
        ),
        (
            {NodeOperatorId(1): {ValidatorIndex(0): 100}, NodeOperatorId(2): {ValidatorIndex(1): 0}},
            Wei(1 * 10**18),
            0,
            {NodeOperatorId(1): Wei(1 * 10**18)},
        ),
        (
            {NodeOperatorId(1): {ValidatorIndex(0): 100}, NodeOperatorId(2): {ValidatorIndex(1): 200}},
            Wei(1 * 10**18),
            10,
            {NodeOperatorId(1): Wei(322580645161290322), NodeOperatorId(2): Wei(645161290322580645)},
        ),
    ],
)
@pytest.mark.unit
def test_calc_rewards_distribution_in_frame(
    participation_shares, rewards_to_distribute, rebate_share, expected_distribution
):
    log = FramePerfLog(ReferenceBlockStampFactory.build(), (EpochNumber(100), EpochNumber(500)))
    rewards_distribution = Distribution.calc_rewards_distribution_in_frame(
        participation_shares, rebate_share, rewards_to_distribute, log
    )
    assert rewards_distribution == expected_distribution


@pytest.mark.unit
def test_calc_rewards_distribution_in_frame_handles_negative_to_distribute():
    participation_shares = {NodeOperatorId(1): {ValidatorIndex(0): 100}, NodeOperatorId(2): {ValidatorIndex(1): 200}}
    rewards_to_distribute = Wei(-1)
    rebate_share = 0

    with pytest.raises(ValueError, match="Invalid rewards to distribute"):
        Distribution.calc_rewards_distribution_in_frame(
            participation_shares, rebate_share, rewards_to_distribute, log=Mock()
        )


@pytest.mark.parametrize(
    ("acc", "strikes_in_frame", "threshold_per_op", "expected"),
    [
        pytest.param({}, {}, {}, {}, id="empty_acc_empty_strikes_in_frame"),
        pytest.param(
            {},
            {
                (NodeOperatorId(42), b"00"): 3,
                (NodeOperatorId(17), b"01"): 1,
            },
            {
                NodeOperatorId(42): Mock(lifetime=6),
                NodeOperatorId(17): Mock(lifetime=4),
            },
            {
                (NodeOperatorId(42), b"00"): [3, 0, 0, 0, 0, 0],
                (NodeOperatorId(17), b"01"): [1, 0, 0, 0],
            },
            id="empty_acc_non_empty_strikes_in_frame",
        ),
        pytest.param(
            {
                (NodeOperatorId(42), b"00"): StrikesList([3, 0, 0, 0, 0, 0]),
                (NodeOperatorId(17), b"01"): StrikesList([1, 0, 0, 0]),
                (NodeOperatorId(17), b"02"): StrikesList([0, 0, 0, 1]),
            },
            {},
            {
                NodeOperatorId(42): Mock(lifetime=5),
                NodeOperatorId(17): Mock(lifetime=4),
            },
            {
                (NodeOperatorId(42), b"00"): [0, 3, 0, 0, 0],
                (NodeOperatorId(17), b"01"): [0, 1, 0, 0],
            },
            id="non_empty_acc_empty_strikes_in_frame",
        ),
        pytest.param(
            {
                (NodeOperatorId(42), b"00"): StrikesList([3, 0, 0, 0, 0, 0]),
                (NodeOperatorId(17), b"01"): StrikesList([1, 0, 0, 0]),
            },
            {
                (NodeOperatorId(42), b"00"): 2,
                (NodeOperatorId(18), b"02"): 1,
            },
            {
                NodeOperatorId(42): Mock(lifetime=5),
                NodeOperatorId(17): Mock(lifetime=4),
                NodeOperatorId(18): Mock(lifetime=6),
            },
            {
                (NodeOperatorId(42), b"00"): [2, 3, 0, 0, 0],
                (NodeOperatorId(17), b"01"): [0, 1, 0, 0],
                (NodeOperatorId(18), b"02"): [1, 0, 0, 0, 0, 0],
            },
            id="non_empty_acc_non_empty_strikes_in_frame",
        ),
    ],
)
@pytest.mark.unit
def test_merge_strikes(
    acc: dict,
    strikes_in_frame: dict,
    threshold_per_op: dict,
    expected: dict,
):
    distribution = Distribution(Mock(csm=Mock()), Mock(), Mock())
    distribution.w3.csm.get_curve_params = Mock(
        side_effect=lambda no_id, _: Mock(strikes_params=threshold_per_op[no_id])
    )

    result = distribution._process_strikes(acc, strikes_in_frame, frame_blockstamp=Mock())

    assert result == expected


@pytest.mark.parametrize(
    "total_distributed_rewards, total_rebate, total_rewards_to_distribute",
    [
        (100, 50, 150),
        (0, 0, 0),
        (50, 50, 100),
    ],
)
@pytest.mark.unit
def tests_validates_correct_distribution(total_distributed_rewards, total_rebate, total_rewards_to_distribute):
    Distribution.validate_distribution(total_distributed_rewards, total_rebate, total_rewards_to_distribute)


@pytest.mark.parametrize(
    "total_distributed_rewards, total_rebate, total_rewards_to_distribute",
    [
        (100, 51, 150),
        (200, 0, 199),
    ],
)
@pytest.mark.unit
def test_raises_error_for_invalid_distribution(total_distributed_rewards, total_rebate, total_rewards_to_distribute):
    with pytest.raises(ValueError, match="Invalid distribution"):
        Distribution.validate_distribution(total_distributed_rewards, total_rebate, total_rewards_to_distribute)


@pytest.mark.parametrize(
    "attestation_perf, proposal_perf, sync_perf, expected",
    [
        (0.95, None, None, 0.95),
        (0.95, 0.5, None, pytest.approx(0.8919, rel=1e-4)),
        (0.95, None, 0.7, pytest.approx(0.9410, rel=1e-4)),
        (0.95, 0.5, 0.7, pytest.approx(0.8859, rel=1e-4)),
        (1, 1, 1, 1),
    ],
)
@pytest.mark.unit
def test_performance_coefficients_calc_performance(attestation_perf, proposal_perf, sync_perf, expected):
    performance_coefficients = PerformanceCoefficients()
    duties = ValidatorDuties(
        attestation=Mock(perf=attestation_perf),
        proposal=Mock(perf=proposal_perf) if proposal_perf is not None else None,
        sync=Mock(perf=sync_perf) if sync_perf is not None else None,
    )
    assert performance_coefficients.calc_performance(duties) == expected


@pytest.mark.parametrize(
    "intervals, key_index, expected",
    [
        ([KeyNumberValueInterval(1, 10000)], 100500, 10000 / TOTAL_BASIS_POINTS),
        ([KeyNumberValueInterval(1, 10000), KeyNumberValueInterval(2, 9000)], 1, 10000 / TOTAL_BASIS_POINTS),
        ([KeyNumberValueInterval(1, 10000), KeyNumberValueInterval(2, 9000)], 2, 9000 / TOTAL_BASIS_POINTS),
        (
            [KeyNumberValueInterval(1, 1000), KeyNumberValueInterval(11, 2000), KeyNumberValueInterval(21, 3000)],
            4,
            1000 / TOTAL_BASIS_POINTS,
        ),
        (
            [KeyNumberValueInterval(1, 1000), KeyNumberValueInterval(11, 2000), KeyNumberValueInterval(21, 3000)],
            9,
            1000 / TOTAL_BASIS_POINTS,
        ),
        (
            [KeyNumberValueInterval(1, 1000), KeyNumberValueInterval(11, 2000), KeyNumberValueInterval(21, 3000)],
            14,
            2000 / TOTAL_BASIS_POINTS,
        ),
        (
            [KeyNumberValueInterval(1, 1000), KeyNumberValueInterval(11, 2000), KeyNumberValueInterval(21, 3000)],
            19,
            2000 / TOTAL_BASIS_POINTS,
        ),
        (
            [KeyNumberValueInterval(1, 1000), KeyNumberValueInterval(11, 2000), KeyNumberValueInterval(21, 3000)],
            24,
            3000 / TOTAL_BASIS_POINTS,
        ),
    ],
)
@pytest.mark.unit
def test_interval_mapping_returns_correct_reward_share(intervals, key_index, expected):
    reward_share = KeyNumberValueIntervalList(intervals)
    assert reward_share.get_for(key_index) == expected


@pytest.mark.unit
def test_interval_mapping_raises_error_for_invalid_key_number():
    reward_share = KeyNumberValueIntervalList(
        [KeyNumberValueInterval(1, 1000), KeyNumberValueInterval(11, 2000), KeyNumberValueInterval(21, 3000)]
    )
    with pytest.raises(ValueError, match="Key number should be greater than 1 or equal"):
        reward_share.get_for(-1)


@pytest.mark.unit
def test_interval_mapping_raises_error_for_key_number_out_of_range():
    reward_share = KeyNumberValueIntervalList([KeyNumberValueInterval(11, 10000)])
    with pytest.raises(ValueError, match="No value found for key number=2"):
        reward_share.get_for(2)
