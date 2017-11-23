"""A utility module to help convert certain things."""

from .models.exceptions import WebieselaException


def exception2dict(error):
    """Convert an exception in the form of a python Exception or a Webiesela exception to a dictionary."""
    if isinstance(error, WebieselaException):
        return error.to_dict()
    elif isinstance(error, Exception):
        return {
            "name": type(error).__name__,
            "args": [str(arg) for arg in error.args]
        }
    else:
        raise TypeError("Can't convert error of type {}".format(type(error)))
