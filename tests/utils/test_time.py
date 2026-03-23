import pytest

from src.utils.time import eip7805_float_seconds_to_int, ms_to_seconds, seconds_to_ms


class TestTimeConversion:
    @pytest.mark.unit
    def test_ms_to_seconds_standard_slot_duration(self):
        """Test conversion of standard Ethereum slot duration."""
        assert ms_to_seconds(12000) == 12.0

    @pytest.mark.unit
    def test_ms_to_seconds_non_round_values(self):
        """Test conversion of non-round millisecond values."""
        assert ms_to_seconds(12500) == 12.5
        assert ms_to_seconds(11750) == 11.75
        assert ms_to_seconds(1) == 0.001

    @pytest.mark.unit
    def test_ms_to_seconds_zero(self):
        """Test conversion of zero milliseconds."""
        assert ms_to_seconds(0) == 0.0

    @pytest.mark.unit
    def test_seconds_to_ms_standard_values(self):
        """Test conversion of standard second values."""
        assert seconds_to_ms(12.0) == 12000
        assert seconds_to_ms(12) == 12000

    @pytest.mark.unit
    def test_seconds_to_ms_non_round_values(self):
        """Test conversion of non-round second values."""
        assert seconds_to_ms(12.5) == 12500
        assert seconds_to_ms(11.75) == 11750
        assert seconds_to_ms(0.001) == 1

    @pytest.mark.unit
    def test_seconds_to_ms_zero(self):
        """Test conversion of zero seconds."""
        assert seconds_to_ms(0.0) == 0
        assert seconds_to_ms(0) == 0

    @pytest.mark.unit
    def test_round_trip_conversion(self):
        """Test that round-trip conversions preserve values."""
        # For round values
        assert seconds_to_ms(ms_to_seconds(12000)) == 12000
        assert ms_to_seconds(seconds_to_ms(12.0)) == 12.0

        # For precise values
        assert seconds_to_ms(ms_to_seconds(12500)) == 12500
        assert ms_to_seconds(seconds_to_ms(12.5)) == 12.5


class TestEip7805FloatSecondsToInt:
    @pytest.mark.unit
    def test_floor_rounding_behavior(self):
        """Test that the function uses floor rounding for positive values."""
        assert eip7805_float_seconds_to_int(12.0) == 12
        assert eip7805_float_seconds_to_int(12.1) == 12
        assert eip7805_float_seconds_to_int(12.7) == 12
        assert eip7805_float_seconds_to_int(12.9) == 12

    @pytest.mark.unit
    def test_whole_numbers(self):
        """Test conversion of whole numbers."""
        assert eip7805_float_seconds_to_int(0.0) == 0
        assert eip7805_float_seconds_to_int(1.0) == 1
        assert eip7805_float_seconds_to_int(86400.0) == 86400

    @pytest.mark.unit
    def test_typical_slot_duration_scenarios(self):
        """Test typical Ethereum slot duration calculations."""
        # Standard 12s slots
        assert eip7805_float_seconds_to_int(12.0 * 7200) == 86400  # 1 day in seconds

        # Non-standard 12.5s slots
        assert eip7805_float_seconds_to_int(12.5 * 7200) == 90000  # 90000.0 → 90000

        # Fractional timestamp
        assert eip7805_float_seconds_to_int(1675263480.7) == 1675263480

    @pytest.mark.unit
    def test_int_input_compatibility(self):
        """Test that int inputs work correctly."""
        assert eip7805_float_seconds_to_int(12) == 12
        assert eip7805_float_seconds_to_int(0) == 0
        assert eip7805_float_seconds_to_int(86400) == 86400

    @pytest.mark.unit
    def test_type_validation(self):
        """Test type validation for invalid inputs."""
        with pytest.raises(TypeError):
            eip7805_float_seconds_to_int("12.5")

        with pytest.raises(TypeError):
            eip7805_float_seconds_to_int(None)

        with pytest.raises(TypeError):
            eip7805_float_seconds_to_int([12.5])
