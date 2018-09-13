from typing import Iterator, Sequence, TypeVar

__all__ = ["batch_gen"]

ST = TypeVar("ST")


def batch_gen(iterable: Sequence[ST], n: int) -> Iterator[Sequence[ST]]:
    length = len(iterable)
    for ndx in range(0, length, n):
        yield iterable[ndx:min(ndx + n, length)]
