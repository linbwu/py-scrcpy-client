def float_to_i16(value: float) -> int:
    """
    Convert a float between -1 and 1 to a signed 16-bit fixed-point value
    """
    assert -1.0 <= value <= 1.0, "value must be between -1.0 and 1.0"
    # 0x8000 = 2^15
    return min(max(int(value * 0x8000), -0x8000), 0x7FFF)  # clamp to int16 range


def float_to_u16(value: float) -> int:
    """
    Convert a float between 0 and 1 to an unsigned 16-bit fixed-point value
    """
    assert 0.0 <= value <= 1.0, "value must be between -1.0 and 1.0"
    # 0x10000 = 2^16
    return min(int(value * 0x10000), 0xFFFF)  # clamp to uint16 range