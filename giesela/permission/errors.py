from giesela import GieselaError

__all__ = ["PermissionFileError"]

PermissionFileError = type("PermissionFileError", (GieselaError,), {})
