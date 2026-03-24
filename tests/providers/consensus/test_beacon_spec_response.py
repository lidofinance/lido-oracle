import pytest

from src.providers.consensus.types import BeaconSpecResponse


class TestBeaconSpecResponse:
    @pytest.mark.unit
    def test_with_seconds_per_slot_only__converts_to_slot_duration_ms(self):
        spec = BeaconSpecResponse(
            DEPOSIT_CHAIN_ID=1,
            SLOTS_PER_EPOCH=32,
            SECONDS_PER_SLOT=12,
            DEPOSIT_CONTRACT_ADDRESS="0x123",
            SLOTS_PER_HISTORICAL_ROOT=8192,
        )

        assert spec.SECONDS_PER_SLOT == 12
        assert spec.SLOT_DURATION_MS == 12000

    @pytest.mark.unit
    def test_with_slot_duration_ms_only__converts_to_seconds_per_slot(self):
        spec = BeaconSpecResponse(
            DEPOSIT_CHAIN_ID=1,
            SLOTS_PER_EPOCH=32,
            SLOT_DURATION_MS=12000,
            DEPOSIT_CONTRACT_ADDRESS="0x123",
            SLOTS_PER_HISTORICAL_ROOT=8192,
        )

        assert spec.SLOT_DURATION_MS == 12000
        assert spec.SECONDS_PER_SLOT == 12

    @pytest.mark.unit
    def test_with_both_fields__keeps_as_is(self):
        spec = BeaconSpecResponse(
            DEPOSIT_CHAIN_ID=1,
            SLOTS_PER_EPOCH=32,
            SLOT_DURATION_MS=12000,
            SECONDS_PER_SLOT=12,
            DEPOSIT_CONTRACT_ADDRESS="0x123",
            SLOTS_PER_HISTORICAL_ROOT=8192,
        )

        assert spec.SLOT_DURATION_MS == 12000
        assert spec.SECONDS_PER_SLOT == 12

    @pytest.mark.unit
    def test_with_neither_field__raises_exception(self):
        with pytest.raises(BeaconSpecResponse.NeitherSlotDurationFieldPresent) as exc_info:
            BeaconSpecResponse(
                DEPOSIT_CHAIN_ID=1,
                SLOTS_PER_EPOCH=32,
                DEPOSIT_CONTRACT_ADDRESS="0x123",
                SLOTS_PER_HISTORICAL_ROOT=8192,
            )

        assert "contains neither SECONDS_PER_SLOT nor SLOT_DURATION_MS" in str(exc_info.value)

    @pytest.mark.unit
    def test_unsupported_fractional_slot_duration__raises_exception(self):
        with pytest.raises(BeaconSpecResponse.UnsupportedSlotDuration) as exc_info:
            BeaconSpecResponse(
                DEPOSIT_CHAIN_ID=1,
                SLOTS_PER_EPOCH=32,
                DEPOSIT_CONTRACT_ADDRESS="0x123",
                SLOTS_PER_HISTORICAL_ROOT=8192,
                SLOT_DURATION_MS=12500,  # 12.5 seconds - not supported
            )

        assert "Non-integer slot duration not supported: 12500ms (12.5s)" in str(exc_info.value)
        assert "Oracle requires whole-second slot durations" in str(exc_info.value)

    @pytest.mark.unit
    def test_unsupported_fractional_slot_duration_with_both_fields__raises_exception(self):
        with pytest.raises(BeaconSpecResponse.UnsupportedSlotDuration):
            BeaconSpecResponse(
                DEPOSIT_CHAIN_ID=1,
                SLOTS_PER_EPOCH=32,
                DEPOSIT_CONTRACT_ADDRESS="0x123",
                SLOTS_PER_HISTORICAL_ROOT=8192,
                SLOT_DURATION_MS=12500,
                SECONDS_PER_SLOT=12,
            )

    @pytest.mark.unit
    def test_inconsistent_slot_duration_fields__raises_exception(self):
        with pytest.raises(BeaconSpecResponse.InconsistentSlotDuration) as exc_info:
            BeaconSpecResponse(
                DEPOSIT_CHAIN_ID=1,
                SLOTS_PER_EPOCH=32,
                DEPOSIT_CONTRACT_ADDRESS="0x123",
                SLOTS_PER_HISTORICAL_ROOT=8192,
                SLOT_DURATION_MS=12000,
                SECONDS_PER_SLOT=11,
            )

        assert "does not match" in str(exc_info.value)
