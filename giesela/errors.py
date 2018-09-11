from discord.ext.commands import CommandError

__all__ = ["GieselaError", "ExtractionError", "PermissionDenied"]


class GieselaError(Exception):
    pass


class ExtractionError(GieselaError):
    pass


class PermissionDenied(GieselaError, CommandError):
    pass
