from typing import Sequence, TypeVar

__all__ = ["interpolate_seq"]

ST = TypeVar("ST")


def interpolate_seq(seq: Sequence[ST], progress: float) -> ST:
    if not 0 <= progress <= 1:
        raise ValueError("progress needs to be <= 0 and <= 1")
    max_index = len(seq) - 1
    i = round(progress * max_index)
    return seq[i]
