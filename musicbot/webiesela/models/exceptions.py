"""Webiesela Exceptions."""


class WebieselaException(Exception):
    """Base class for exceptions."""

    __code__ = 0

    def __init__(self, msg, *args):
        """Create a new instance."""
        super.__init__(*args)
        self.msg = msg

    @property
    def data(self):
        """Provide additional data."""
        return {}

    def to_dict(self):
        """Return serialised version of the error."""
        return {
            "name": type(self).__name__,
            "code": self.__code__,
            "message": self.msg,
            "data": self.data
        }


class MissingParamsError(WebieselaException):
    """When not all required parameters are satisfied."""

    __code__ = 1000

    def __init__(self, missing, *args):
        """Create new."""
        super.__init__("missing parameters", *args)
        self.missing = missing

    @property
    def data(self):
        """Missing parameters."""
        return {"missing": self.missing}


class ParamError(WebieselaException):
    """When a parameter is wrong."""

    __code__ = 1001

    def __init__(self, msg, erroneous, *args):
        """Create new."""
        super.__init__(msg, *args)
        self.erroneous = erroneous

    @property
    def data(self):
        """Wrong parameter."""
        return {"erroneous": self.erroneous}
