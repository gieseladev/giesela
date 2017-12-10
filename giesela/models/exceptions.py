"""Giesela Exceptions."""


class GieselaException(Exception):
    """A Giesela exception."""

    def __init__(self, msg, *args):
        """Create a new instance."""
        super().__init__(*args)
        self.msg = msg


class MissingParamsError(GieselaException):
    """When there are missing params for a command."""

    def __init__(self, missing, *args):
        """Create new."""
        super().__init__("missing parameters", *args)
        self.missing = list(missing)


class ParamError(GieselaException):
    """When a parameter is wrong."""

    def __init__(self, msg, erroneous, *args):
        """Create new."""
        super().__init__(msg, *args)
        self.erroneous = erroneous


class ConfigException(GieselaException):
    """When there's something wrong with the config."""

    pass


class ConfigKeysMissing(ConfigException):
    """When the config file isn't complete."""

    def __init__(self, missing, *args):
        """Create new."""
        super().__init__("Not all keys provided!", *args)
        self.missing = missing
