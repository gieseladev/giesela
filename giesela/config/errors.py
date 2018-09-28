from typing import Any, Optional

from giesela.errors import GieselaError

__all__ = ["ConfigError", "ConfigKeyMissing", "ConfigValueError",
           "TraverseError"]


class ConfigError(GieselaError):
    def __init__(self, msg: str, key: str = None, **extra) -> None:
        self.msg = msg
        self.key = key or None
        self.extra = extra

    def __str__(self) -> str:
        kwargs = self.extra.copy()
        kwargs.update(key=self.key)
        return self.msg.format(**kwargs)

    def trace_key(self, name: str):
        key = self.key or ""

        if key.startswith("["):
            self.key = f"{name}{key}"
        else:
            self.key = f"{name}.{key}"


class ConfigKeyMissing(ConfigError, KeyError):
    def __init__(self, msg: str, key: str, **extra) -> None:
        super().__init__(msg, key, **extra)


class ConfigValueError(ConfigError, ValueError):
    def __init__(self, msg: str, key: Optional[str], value: Any, **extra) -> None:
        super().__init__(msg, key, value=value, **extra)
        self.value = value


class TraverseError(ConfigError, AttributeError):
    def __init__(self, msg: str, parent: str, key: str, **extra) -> None:
        super().__init__(msg, parent, target=key, **extra)
        self.target = key
