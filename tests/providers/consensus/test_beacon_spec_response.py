import pytest

from src.providers.consensus.types import BeaconSpecResponse


class TestBeaconSpecResponse:
    @pytest.mark.unit
    def test_with_seconds_per_slot_only__converts_to_slot_duration_ms(self):
        """When only SECONDS_PER_SLOT is provided, SLOT_DURATION_MS should be calculated."""
        spec = BeaconSpecResponse(
            DEPOSIT_CHAIN_ID=1,
            SLOTS_PER_EPOCH=32,
            SECONDS_PER_SLOT=12,
            DEPOSIT_CONTRACT_ADDRESS="0x123",
            SLOTS_PER_HISTORICAL_ROOT=8192,
        )

        assert spec.SECONDS_PER_SLOT == 12.0
        assert spec.SLOT_DURATION_MS == 12000

    @pytest.mark.unit
    def test_with_slot_duration_ms_only__converts_to_seconds_per_slot(self):
        """When only SLOT_DURATION_MS is provided, SECONDS_PER_SLOT should be calculated."""
        spec = BeaconSpecResponse(
            DEPOSIT_CHAIN_ID=1,
            SLOTS_PER_EPOCH=32,
            SLOT_DURATION_MS=12000,
            DEPOSIT_CONTRACT_ADDRESS="0x123",
            SLOTS_PER_HISTORICAL_ROOT=8192,
        )

        assert spec.SLOT_DURATION_MS == 12000
        assert spec.SECONDS_PER_SLOT == 12.0

    @pytest.mark.unit
    def test_with_slot_duration_ms_non_round__precise_float_conversion(self):
        """When SLOT_DURATION_MS is not divisible by 1000, SECONDS_PER_SLOT uses precise float conversion."""
        spec = BeaconSpecResponse(
            DEPOSIT_CHAIN_ID=1,
            SLOTS_PER_EPOCH=32,
            SLOT_DURATION_MS=11500,
            DEPOSIT_CONTRACT_ADDRESS="0x123",
            SLOTS_PER_HISTORICAL_ROOT=8192,
        )

        assert spec.SLOT_DURATION_MS == 11500
        assert spec.SECONDS_PER_SLOT == 11.5  # 11500 / 1000

    @pytest.mark.unit
    def test_with_both_fields__keeps_as_is(self):
        """When both fields are provided, they should be kept as-is."""
        spec = BeaconSpecResponse(
            DEPOSIT_CHAIN_ID=1,
            SLOTS_PER_EPOCH=32,
            SLOT_DURATION_MS=12000,
            SECONDS_PER_SLOT=12,
            DEPOSIT_CONTRACT_ADDRESS="0x123",
            SLOTS_PER_HISTORICAL_ROOT=8192,
        )

        assert spec.SLOT_DURATION_MS == 12000
        assert spec.SECONDS_PER_SLOT == 12.0

    @pytest.mark.unit
    def test_with_neither_field__raises_exception(self):
        """When neither field is provided, should raise NeitherSlotDurationFieldPresent."""
        with pytest.raises(BeaconSpecResponse.NeitherSlotDurationFieldPresent) as exc_info:
            BeaconSpecResponse(
                DEPOSIT_CHAIN_ID=1,
                SLOTS_PER_EPOCH=32,
                DEPOSIT_CONTRACT_ADDRESS="0x123",
                SLOTS_PER_HISTORICAL_ROOT=8192,
            )

        assert "contains neither SECONDS_PER_SLOT nor SLOT_DURATION_MS" in str(exc_info.value)
