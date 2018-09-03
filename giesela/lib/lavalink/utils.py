def to_milli(value: float) -> int:
    return round(1000 * value)


def from_milli(value: int) -> float:
    return value / 1000
