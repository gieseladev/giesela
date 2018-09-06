from typing import Sequence

__all__ = ["batch_gen"]


def batch_gen(iterable: Sequence, n: int) -> Sequence:
    length = len(iterable)
    for ndx in range(0, length, n):
        yield iterable[ndx:min(ndx + n, length)]
