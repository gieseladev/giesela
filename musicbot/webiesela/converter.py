from .models.exceptions import Exceptions


def exception2dict(error):
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
