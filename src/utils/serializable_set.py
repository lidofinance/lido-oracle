"""
Serializable Set Implementation

A set-like data structure with adaptive serialization that automatically chooses
the most efficient encoding strategy between run-length encoding and direct storage.
"""


class SerializableSet(set):
    """
    An adaptive implementation with variable-length encoding.

    Extends built-in set with serialization that automatically chooses optimal strategy:
    - Run-length encoding for clustered data (efficient for consecutive ranges)
    - Direct value list for sparse data (efficient when ranges are ineffective)
    - Automatically chooses the most compact representation during serialization
    """
    
    def _build_ranges(self, sorted_values: list[int]) -> list[tuple[int, int]]:
        if not sorted_values:
            return []
            
        ranges = []
        start = sorted_values[0]
        end = sorted_values[0]
        
        for val in sorted_values[1:]:
            if val == end + 1:
                end = val
            else:
                ranges.append((start, end))
                start = end = val

        ranges.append((start, end))
        return ranges
    
    def serialize(self) -> bytes:
        """
        Serialize using adaptive encoding.
        Chooses between run-length encoding and direct value list based on efficiency.
        Format: [encoding_type: 1 byte] + data
        - Type 0: Run-length encoding (ranges)
        - Type 1: Direct value list
        """
        if not self:
            return bytes([0]) + self._encode_varint(0)

        sorted_values = sorted(self)
        ranges = self._build_ranges(sorted_values)
        
        # Calculate size for run-length encoding
        rle_data = [self._encode_varint(len(ranges))]
        for start, end in ranges:
            length = end - start + 1
            rle_data.append(self._encode_varint(start))
            rle_data.append(self._encode_varint(length))
        rle_bytes = b"".join(rle_data)
        rle_size = 1 + len(rle_bytes)  # +1 for type byte
        
        # Calculate size for direct value list
        direct_data = [self._encode_varint(len(self))]
        for value in sorted_values:
            direct_data.append(self._encode_varint(value))
        direct_bytes = b"".join(direct_data)
        direct_size = 1 + len(direct_bytes)  # +1 for type byte
        
        # Choose more efficient encoding
        if rle_size <= direct_size:
            return bytes([0]) + rle_bytes  # Use run-length encoding
        else:
            return bytes([1]) + direct_bytes  # Use direct value list
    
    @classmethod
    def deserialize(cls, data: bytes) -> "SerializableSet":
        _set = cls()

        if not data:
            return _set

        encoding_type = data[0]
        offset = 1
        
        if encoding_type == 0:
            if offset >= len(data):
                return _set
            
            num_ranges, offset = cls._decode_varint(data, offset)
            
            for _ in range(num_ranges):
                start, offset = cls._decode_varint(data, offset)
                length, offset = cls._decode_varint(data, offset)
                end = start + length - 1
                # Add all values in this range to our set
                _set.update(range(start, end + 1))

            return _set
                
        if encoding_type == 1:
            # Direct value list
            num_values, offset = cls._decode_varint(data, offset)
            
            for _ in range(num_values):
                value, offset = cls._decode_varint(data, offset)
                _set.add(value)

            return _set

        raise ValueError(f"Unknown encoding type: {encoding_type}")

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        # Reference: https://protobuf.dev/programming-guides/encoding/#varints
        payload_mask = 0x7F
        continuation_flag = 0x80

        result = []
        while value >= continuation_flag:  # While value does not fit in 7 bits
            result.append((value & payload_mask) | continuation_flag)
            value >>= 7  # Shift to the next byte
        result.append(value & payload_mask)
        return bytes(result)
    
    @staticmethod
    def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
        # Reference: https://protobuf.dev/programming-guides/encoding/#varints
        payload_mask = 0x7F
        continuation_flag = 0x80

        decoded_value = 0
        bit_shift_position = 0
        current_offset = offset
        
        while current_offset < len(data):
            current_byte = data[current_offset]
            current_offset += 1
            
            # Extract data bits and place them at the correct position
            data_bits = current_byte & payload_mask
            decoded_value |= (data_bits << bit_shift_position)
            
            # Check if this is the last byte (no continuation flag)
            has_continuation = (current_byte & continuation_flag) != 0
            if not has_continuation:
                break
            
            # Move to the next 7-bit group
            bit_shift_position += 7
            
            # Can't be greater than uint64
            if bit_shift_position >= 64:
                raise ValueError("Varint too long")
        else:
            raise ValueError("Incomplete varint")
        
        return decoded_value, current_offset
    
    def __repr__(self) -> str:
        return f"SerializableSet({sorted(self)})"
    
    def __str__(self) -> str:
        return f"SerializableSet({len(self)} values)"
    
    def copy(self):
        return SerializableSet(self)
