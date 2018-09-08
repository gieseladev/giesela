from typing import Any, Optional

from giesela.errors import GieselaError


class ConfigError(GieselaError):
    def __init__(self, msg: str, key: str = None, **extra):
        self.msg = msg
        self.key = key
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


class ConfigKeyMissing(ConfigError):
    def __init__(self, msg: str, key: str, **extra):
        super().__init__(msg, key, **extra)


class ConfigValueError(ConfigError):
    def __init__(self, msg: str, key: Optional[str], value: Any, **extra):
        super().__init__(msg, key, value=value, **extra)
        self.value = value
