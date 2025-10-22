def float_toi16(value: float) -> int:
    """
    Convert float to 16.16 fixed-point integer

    Args:
        value: float value

    Returns:
        16.16 fixed-point integer
    """
    assert -1.0 <= value <= 1.0, "value must be between -1.0 and 1.0"
    # 0x8000 = 2^15
    return min(max(int(value * 0x8000), -0x8000), 0x7FFF)  # clamp to int16 range
