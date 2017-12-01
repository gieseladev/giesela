"""Webiesela Exceptions."""

import logging

log = logging.getLogger(__name__)


class WebieselaExceptionMount(type):
    """Mount for exceptions to make sure that error codes are unique."""

    def __init__(cls, name, bases, attrs):
        """Add exception to list."""
        if not hasattr(cls, "exceptions"):
            # only add it to the first deriver (the WebieselaException class)
            cls.exceptions = {}
            log.debug("setup base exception")
        else:
            # warn when exception codes already in use
            if cls.__code__ in cls.exceptions:
                raise SyntaxError("Exception code {} already exists! (Couldn't register Exception \"{}\")".format(cls.__code__, name))
            else:
                cls.exceptions[cls.__code__] = cls
                log.debug("registered exception \"{}\" ({})".format(name, cls.__code__))


class WebieselaException(Exception, metaclass=WebieselaExceptionMount):
    """Base class for exceptions."""

    __code__ = 0

    def __init__(self, msg, *args):
        """Create a new instance."""
        super().__init__(*args)
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
        super().__init__("missing parameters", *args)
        self.missing = list(missing)

    @property
    def data(self):
        """Missing parameters."""
        return {"missing": self.missing}


class ParamError(WebieselaException):
    """When a parameter is wrong."""

    __code__ = 1001

    def __init__(self, msg, erroneous, *args):
        """Create new."""
        super().__init__(msg, *args)
        self.erroneous = erroneous

    @property
    def data(self):
        """Wrong parameter."""
        return {"erroneous": self.erroneous}


class AuthError(WebieselaException):
    """Some error with reg or auth."""

    __code__ = 2000


class AuthorisationRequired(AuthError):
    """Trying to use an endpoint which requires auth."""

    __code__ = 2001


class TokenUnknown(AuthError):
    """When a token doesn't exist."""

    __code__ = 2002


class TokenExpired(AuthError):
    """When a token has expired."""

    __code__ = 2003
