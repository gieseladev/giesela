import inspect
from contextlib import suppress

__all__ = ["annotation_only"]


def annotation_only(cls: object):
    """Removes all methods and attributes from a class"""
    for attr, _ in inspect.getmembers(cls):
        with suppress(Exception):
            delattr(cls, attr)

    return cls
