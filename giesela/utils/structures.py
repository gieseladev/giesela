from typing import Sequence

__all__ = ["batch_gen"]


def batch_gen(iterable: Sequence, n: int) -> Sequence:
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]
