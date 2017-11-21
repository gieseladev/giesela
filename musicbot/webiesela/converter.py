"""A utility module to help convert certain things."""

from .models.exceptions import Exceptions


def exception2dict(error):
    """Convert an exception in the form of a python Exception or a Webiesela exception to a dictionary."""
    if isinstance(error, Exception):
        return {
            "name": type(error).__name__,
            "args": [str(arg) for arg in error.args]
        }
    elif isinstance(error, Exceptions):
        return {
            "name": error.name,
            "id": error.value
        }
    else:
        raise TypeError("Can't convert error of type {}".format(type(error)))
