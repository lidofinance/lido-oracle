"""Shape-faithful tests replaying responses recorded from the Glamsterdam devnet."""

from pathlib import Path
from typing import cast

import pytest
from eth_typing import BlockNumber
from web3.eth import Eth
from web3.types import Timestamp

from src.providers.consensus.client import ConsensusClient
from src.types import BlockStamp, EpochNumber, SlotNumber, StateRoot
from src.utils.blockstamp import get_reference_blockstamp
from tests.scenarios.cassette import Cassette
from tests.scenarios.replay import CassetteConsensusClient, CassetteKeysAPIClient


CASSETTE_PATH = Path(__file__).parents[1] / 'cassettes/glamsterdam-kurtosis-7/AC-01-confirmed-payload-36255'
SYNTHETIC_CASSETTE_PATH = (
    Path(__file__).parents[1] / 'cassettes/glamsterdam-kurtosis-7/AC-02-synthetic-withheld-payload-36255'
)
BUILDER_CASSETTE_PATH = (
    Path(__file__).parents[1] / 'cassettes/glamsterdam-kurtosis-7/AC-03-synthetic-builder-withdrawal-36255'
)
LARGE_WITHDRAWAL_CASSETTE_PATH = (
    Path(__file__).parents[1] / 'cassettes/glamsterdam-kurtosis-7/AC-04-synthetic-large-withdrawal-batch-36255'
)
NEGATIVE_REBASE_CASSETTE_PATH = (
    Path(__file__).parents[1] / 'cassettes/glamsterdam-kurtosis-7/AC-05-synthetic-negative-rebase-36255'
)
BUILDER_INDEX_FLAG = 2**40


class _UnrecordedEth:
    """Stands in for the execution client the cassettes do not record.

    A post-EIP-7732 anchor resolves its execution fields through the EL, but these cases assert
    only which beacon block was picked, so the values are never read back.
    """

    @staticmethod
    def get_block(_block_identifier: object) -> dict[str, object]:
        return {'number': BlockNumber(0), 'timestamp': Timestamp(0)}


@pytest.fixture()
def cassette() -> Cassette:
    return Cassette.load(CASSETTE_PATH)


@pytest.mark.unit
@pytest.mark.scenario
class TestGlamsterdamCassette:
    def test_build_reference_blockstamp__recorded_confirmed_payload__uses_real_gloas_shapes(
        self, cassette: Cassette
    ) -> None:
        # Arrange
        client = CassetteConsensusClient(cassette)

        # Act
        blockstamp = get_reference_blockstamp(
            cast(ConsensusClient, client),
            ref_slot=SlotNumber(36255),
            last_finalized_slot_number=SlotNumber(36256),
            ref_epoch=EpochNumber(36255 // 32),
            el=cast(Eth, _UnrecordedEth()),
        )

        # Assert -- under EIP-7732 the anchor is ref_slot's child, whose state is the first one
        # where ref_slot's payload, deposits and withdrawals are all settled.
        assert client.is_gloas_epoch(blockstamp.ref_epoch)
        assert blockstamp.ref_slot == 36255
        assert blockstamp.slot_number == 36256

    def test_get_state_view__recorded_parent_state__parses_gloas_fields(self, cassette: Cassette) -> None:
        # Arrange
        client = CassetteConsensusClient(cassette)
        parent_state_root = cast(StateRoot, '0x72b3208c35f1970ac2a68b1fce06323f38690ca0eea9079354ff6232bc6a9b5c')

        # Act
        state = client.get_state_view((parent_state_root, SlotNumber(36255)))

        # Assert
        assert state.slot == 36255
        assert len(state.validators) > 0
        assert len(state.payload_expected_withdrawals) == 16

    def test_get_used_lido_keys__recorded_keys_response__parses_all_keys(self, cassette: Cassette) -> None:
        # Arrange
        client = CassetteKeysAPIClient(cassette)

        # Act
        keys = client.get_used_lido_keys(cast(BlockStamp, None))

        # Assert
        assert len(keys) == 20
        assert all(key.used for key in keys)

    @pytest.mark.skip(
        reason='Predates the ePBS blockstamp rework: the AC-02 overlay patches the state '
        'at ref_slot, but a reference blockstamp now anchors on ref_slot\'s child and reads that '
        'state instead. The overlay has to be re-authored against the child state, and '
        'withdrawal_correction_needed no longer exists as a concept.'
    )
    def test_build_reference_blockstamp__synthetic_withheld_payload__requires_withdrawal_correction(self) -> None:
        # Arrange
        cassette = Cassette.load(SYNTHETIC_CASSETTE_PATH)
        client = CassetteConsensusClient(cassette)

        # Act
        blockstamp = get_reference_blockstamp(
            cast(ConsensusClient, client),
            ref_slot=SlotNumber(36255),
            last_finalized_slot_number=SlotNumber(36256),
            ref_epoch=EpochNumber(36255 // 32),
            el=cast(Eth, _UnrecordedEth()),
        )
        state = client.get_state_view(blockstamp)

        # Assert
        assert cassette.manifest.origin == 'synthetic'
        assert blockstamp.withdrawal_correction_needed is True
        assert [withdrawal.validator_index for withdrawal in state.payload_expected_withdrawals] == [384, 394]
        assert [withdrawal.amount for withdrawal in state.payload_expected_withdrawals] == [
            1_000_000_000,
            2_000_000_000,
        ]
        assert state.balances[384] == 31_000_000_000
        assert state.balances[394] == 30_000_000_000

    def test_get_state_view__synthetic_builder_withdrawal__preserves_flagged_index(self) -> None:
        # Arrange
        cassette = Cassette.load(BUILDER_CASSETTE_PATH)
        client = CassetteConsensusClient(cassette)
        parent_state_root = cast(StateRoot, '0x72b3208c35f1970ac2a68b1fce06323f38690ca0eea9079354ff6232bc6a9b5c')

        # Act
        state = client.get_state_view((parent_state_root, SlotNumber(36255)))

        # Assert
        assert cassette.manifest.origin == 'synthetic'
        assert cassette.manifest.base_scenario_id == 'AC-02-synthetic-withheld-payload-36255'
        assert [withdrawal.validator_index for withdrawal in state.payload_expected_withdrawals] == [
            384,
            394,
            BUILDER_INDEX_FLAG + 7,
        ]
        assert state.payload_expected_withdrawals[-1].amount == 5_000_000_000

    def test_get_state_view__synthetic_large_withdrawal_batch__balances_loss_with_evidence(self) -> None:
        # Arrange
        cassette = Cassette.load(LARGE_WITHDRAWAL_CASSETTE_PATH)
        client = CassetteConsensusClient(cassette)
        parent_state_root = cast(StateRoot, '0x72b3208c35f1970ac2a68b1fce06323f38690ca0eea9079354ff6232bc6a9b5c')

        # Act
        state = client.get_state_view((parent_state_root, SlotNumber(36255)))

        # Assert
        assert cassette.manifest.base_scenario_id == 'AC-02-synthetic-withheld-payload-36255'
        assert [withdrawal.validator_index for withdrawal in state.payload_expected_withdrawals] == list(
            range(384, 400)
        )
        assert sum(withdrawal.amount for withdrawal in state.payload_expected_withdrawals) == 16_000_000_000
        assert state.balances[384:399] == [31_000_000_000] * 15
        assert state.balances[399] == 31_044_601_085

    def test_get_state_view__synthetic_negative_rebase__preserves_loss_without_evidence(self) -> None:
        # Arrange
        cassette = Cassette.load(NEGATIVE_REBASE_CASSETTE_PATH)
        client = CassetteConsensusClient(cassette)
        parent_state_root = cast(StateRoot, '0x72b3208c35f1970ac2a68b1fce06323f38690ca0eea9079354ff6232bc6a9b5c')

        # Act
        state = client.get_state_view((parent_state_root, SlotNumber(36255)))

        # Assert
        assert cassette.manifest.base_scenario_id == 'AC-04-synthetic-large-withdrawal-batch-36255'
        assert state.payload_expected_withdrawals == []
        assert state.balances[384:399] == [31_000_000_000] * 15
        assert state.balances[399] == 31_044_601_085
