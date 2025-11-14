"""
Tests for SerializableSet

Comprehensive test suite covering all functionality of the SerializableSet class
including adaptive serialization, set operations, and edge cases.
"""

import pytest
from src.utils.serializable_set import SerializableSet


class TestSerializableSet:
    """Test suite for SerializableSet class."""

    @pytest.mark.unit
    def test_initialization_empty(self):
        """Test creating an empty SerializableSet."""
        ss = SerializableSet()
        assert len(ss) == 0
        assert isinstance(ss, set)
        assert not ss

    @pytest.mark.unit
    def test_initialization_with_values(self):
        """Test creating SerializableSet with initial values."""
        values = [1, 2, 3, 5, 8]
        ss = SerializableSet(values)
        assert len(ss) == 5
        assert 3 in ss
        assert 4 not in ss
        assert sorted(ss) == [1, 2, 3, 5, 8]

    @pytest.mark.unit
    def test_set_operations(self):
        """Test basic set operations."""
        ss = SerializableSet([1, 2, 3])
        
        # Add
        ss.add(4)
        assert 4 in ss
        assert len(ss) == 4
        
        # Remove
        ss.remove(2)
        assert 2 not in ss
        assert len(ss) == 3
        
        # Discard
        ss.discard(10)  # Should not raise error
        ss.discard(1)
        assert 1 not in ss
        assert len(ss) == 2
        
        # Update
        ss.update([5, 6, 7])
        assert sorted(ss) == [3, 4, 5, 6, 7]
        
        # Clear
        ss.clear()
        assert len(ss) == 0

    @pytest.mark.unit
    def test_set_operators(self):
        """Test set operators (union, intersection, etc.)."""
        ss1 = SerializableSet([1, 2, 3, 4])
        ss2 = SerializableSet([3, 4, 5, 6])
        
        # Union
        union = ss1 | ss2
        assert sorted(union) == [1, 2, 3, 4, 5, 6]
        
        # Intersection
        intersection = ss1 & ss2
        assert sorted(intersection) == [3, 4]
        
        # Difference
        diff = ss1 - ss2
        assert sorted(diff) == [1, 2]
        
        # Symmetric difference
        sym_diff = ss1 ^ ss2
        assert sorted(sym_diff) == [1, 2, 5, 6]

    @pytest.mark.unit
    def test_equality(self):
        """Test equality comparisons."""
        ss1 = SerializableSet([1, 2, 3])
        ss2 = SerializableSet([3, 1, 2])
        ss3 = SerializableSet([1, 2, 4])
        regular_set = {1, 2, 3}
        
        assert ss1 == ss2
        assert ss1 != ss3
        assert ss1 == regular_set
        assert ss1 != [1, 2, 3]  # Different type

    @pytest.mark.unit
    def test_build_ranges(self):
        """Test the internal _build_ranges method."""
        ss = SerializableSet()
        
        # Empty
        ranges = ss._build_ranges([])
        assert ranges == []
        
        # Single value
        ranges = ss._build_ranges([5])
        assert ranges == [(5, 5)]
        
        # Consecutive sequence
        ranges = ss._build_ranges([1, 2, 3, 4, 5])
        assert ranges == [(1, 5)]
        
        # Multiple ranges
        ranges = ss._build_ranges([1, 2, 3, 7, 8, 10])
        assert ranges == [(1, 3), (7, 8), (10, 10)]
        
        # Sparse values
        ranges = ss._build_ranges([1, 5, 10, 20])
        assert ranges == [(1, 1), (5, 5), (10, 10), (20, 20)]

    @pytest.mark.unit
    def test_varint_encoding(self):
        """Test varint encoding and decoding."""
        # Test small values (1 byte)
        for value in [0, 1, 127]:
            encoded = SerializableSet._encode_varint(value)
            decoded, offset = SerializableSet._decode_varint(encoded, 0)
            assert decoded == value
            assert offset == len(encoded)
        
        # Test medium values (2 bytes)
        for value in [128, 255, 16383]:
            encoded = SerializableSet._encode_varint(value)
            decoded, offset = SerializableSet._decode_varint(encoded, 0)
            assert decoded == value
            assert offset == len(encoded)
        
        # Test large values
        for value in [16384, 65535, 1048575]:
            encoded = SerializableSet._encode_varint(value)
            decoded, offset = SerializableSet._decode_varint(encoded, 0)
            assert decoded == value
            assert offset == len(encoded)

    @pytest.mark.unit
    def test_serialization_empty(self):
        """Test serialization of empty set."""
        ss = SerializableSet()
        serialized = ss.serialize()
        deserialized = SerializableSet.deserialize(serialized)
        
        assert ss == deserialized
        assert len(deserialized) == 0

    @pytest.mark.unit
    def test_serialization_single_value(self):
        """Test serialization of single value."""
        ss = SerializableSet([42])
        serialized = ss.serialize()
        deserialized = SerializableSet.deserialize(serialized)
        
        assert ss == deserialized
        assert 42 in deserialized
        assert len(deserialized) == 1

    @pytest.mark.unit
    def test_serialization_consecutive_values(self):
        """Test serialization with consecutive values (should prefer RLE)."""
        # Large consecutive range should use run-length encoding
        ss = SerializableSet(range(1, 1001))  # 1000 consecutive numbers
        serialized = ss.serialize()
        deserialized = SerializableSet.deserialize(serialized)
        
        assert ss == deserialized
        assert len(deserialized) == 1000
        assert min(deserialized) == 1
        assert max(deserialized) == 1000
        
        # Should be very compact (RLE encoding)
        assert len(serialized) < 20  # Much smaller than 1000 * varint_size

    @pytest.mark.unit
    def test_serialization_sparse_values(self):
        """Test serialization with sparse values (should prefer direct list)."""
        # Sparse values should use direct encoding
        sparse_values = [1, 100, 1000, 10000, 100000]
        ss = SerializableSet(sparse_values)
        serialized = ss.serialize()
        deserialized = SerializableSet.deserialize(serialized)
        
        assert ss == deserialized
        assert sorted(deserialized) == sparse_values

    @pytest.mark.unit
    def test_serialization_mixed_ranges(self):
        """Test serialization with mixed consecutive and sparse values."""
        # Mix of ranges and sparse values
        values = list(range(1, 11)) + list(range(50, 61)) + [100, 200, 300]
        ss = SerializableSet(values)
        serialized = ss.serialize()
        deserialized = SerializableSet.deserialize(serialized)
        
        assert ss == deserialized
        assert len(deserialized) == len(values)

    @pytest.mark.unit
    def test_serialization_adaptive_strategy(self):
        """Test that serialization chooses the most efficient strategy."""
        # Test that RLE is chosen for consecutive data
        consecutive_ss = SerializableSet(range(1, 100))
        consecutive_serialized = consecutive_ss.serialize()
        
        # Test that direct list is chosen for sparse data
        sparse_ss = SerializableSet([1, 1000, 10000, 100000, 1000000])
        sparse_serialized = sparse_ss.serialize()
        
        # Consecutive should be more compact
        assert len(consecutive_serialized) < 50  # Very compact with RLE
        
        # Both should deserialize correctly
        assert consecutive_ss == SerializableSet.deserialize(consecutive_serialized)
        assert sparse_ss == SerializableSet.deserialize(sparse_serialized)

    @pytest.mark.unit
    def test_deserialization_invalid_data(self):
        """Test deserialization with invalid data."""
        # Empty data
        empty_ss = SerializableSet.deserialize(b"")
        assert len(empty_ss) == 0
        
        # Invalid encoding type
        with pytest.raises(ValueError, match="Unknown encoding type"):
            SerializableSet.deserialize(bytes([99, 1, 2, 3]))
        
        # Incomplete varint
        with pytest.raises(ValueError, match="Incomplete varint"):
            SerializableSet.deserialize(bytes([1, 0xFF]))  # Incomplete varint

    @pytest.mark.unit
    def test_repr_and_str(self):
        """Test string representations."""
        ss = SerializableSet([3, 1, 2])
        
        # __repr__ should show sorted values
        assert repr(ss) == "SerializableSet([1, 2, 3])"
        
        # __str__ should show count
        assert str(ss) == "SerializableSet(3 values)"
        
        # Empty set
        empty_ss = SerializableSet()
        assert repr(empty_ss) == "SerializableSet([])"
        assert str(empty_ss) == "SerializableSet(0 values)"

    @pytest.mark.unit
    def test_copy_and_iteration(self):
        """Test copy and iteration functionality."""
        original = SerializableSet([1, 2, 3, 4, 5])
        
        # Copy (inherited from set)
        copied = original.copy()
        assert copied == original
        assert copied is not original
        assert isinstance(copied, SerializableSet)
        
        # Iteration
        values = list(original)
        assert sorted(values) == [1, 2, 3, 4, 5]
        
        # Iteration is same as set iteration
        set_values = list(set([1, 2, 3, 4, 5]))
        assert sorted(values) == sorted(set_values)

    @pytest.mark.unit
    def test_large_dataset_performance(self):
        """Test performance with larger datasets."""
        # Create a large dataset with mixed patterns
        large_values = (
            list(range(1, 1000)) +           # Consecutive range
            list(range(10000, 10100)) +      # Another consecutive range
            [50000, 60000, 70000, 80000]     # Sparse values
        )
        
        ss = SerializableSet(large_values)
        serialized = ss.serialize()
        deserialized = SerializableSet.deserialize(serialized)
        
        assert ss == deserialized
        assert len(deserialized) == len(large_values)
        
        # Should be reasonably compact
        assert len(serialized) < len(large_values) * 4  # Much better than 4 bytes per value