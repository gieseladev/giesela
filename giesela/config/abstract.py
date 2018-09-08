import inspect
import typing
from typing import Any, Dict, Iterator, List, Tuple, Type, Union

from .errors import ConfigError, ConfigKeyMissing, ConfigValueError

__all__ = ["ConfigObject", "Check", "Truthy"]

_GENERIC_ALIAS = getattr(typing, "_GenericAlias")
_SPECIAL_FORM = getattr(typing, "_SpecialForm")

_DEFAULT = object()


def is_special_typing(cls) -> bool:
    return type(cls) is _GENERIC_ALIAS or type(cls) is _SPECIAL_FORM


def convert_typing(value, cls):
    origin = cls.__origin__
    args = cls.__args__

    if origin is list:
        cls = args[0]
        if isinstance(value, dict):
            item_iter = []
            for key, value in value.items():
                key = int(key)
                item_iter.append((key, value))
            item_iter.sort()
        elif isinstance(value, list):
            item_iter = enumerate(value)
        else:
            return _DEFAULT

        converted = []
        for i, val in item_iter:
            converted_val = convert(val, cls)
            if converted_val is _DEFAULT:
                raise ConfigValueError(f"Couldn't convert {{name}} {val} to {cls}", f"[{i}]", val)
            converted.append(converted_val)
        return converted
    elif origin is Union:
        if not isinstance(value, args):
            for arg in args:
                value = convert(value, arg)
                if value is not _DEFAULT:
                    break
            else:
                raise ConfigValueError(f"Couldn't convert {{name}} {value} to {cls}", None, value)
        return value

    raise ConfigError(f"Conversion for {cls} ({{name}}) not implemented!")


def convert(value, cls):
    if isinstance(value, Exception):
        raise value

    if inspect.isclass(cls) and issubclass(cls, ConfigObject):
        return cls.from_config(value)

    if is_special_typing(cls):
        return convert_typing(value, cls)

    if isinstance(value, cls):
        return value

    try:
        # handle simple conversions like int -> str, int -> float and so on
        value = cls(value)
    except Exception:
        pass
    else:
        return value

    return _DEFAULT


class Check:
    def __init__(self, callback, default: Any = _DEFAULT, *, fail_msg: str = None, raise_original: bool = True):
        self.callback = callback
        self.default = default

        self.fail_msg = fail_msg
        self.raise_original = raise_original

    def __str__(self) -> str:
        return f"Check {self.callback}"

    def check(self, value) -> bool:
        try:
            return bool(self.callback(value))
        except Exception:
            if self.raise_original:
                raise
            return False


class Truthy(Check):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("fail_msg", "{key} must be set!")
        super().__init__(bool, *args, **kwargs)

    def __str__(self) -> str:
        return "Truthy check"


class ConfigObject:
    __attrs__: Dict[str, Type]

    @classmethod
    def from_config(cls, data: Dict[str, Any]):
        hints = typing.get_type_hints(cls)

        inst = object.__new__(cls)

        inst.__attrs__ = hints.copy()

        for name, _type in hints.items():
            if name.startswith("_"):
                continue

            try:
                _check = getattr(inst, name)
                check = _check if isinstance(_check, Check) else None
            except Exception:
                check = None

            try:
                raw_value = data[name]
            except KeyError:
                try:
                    default = getattr(inst, name)

                    if isinstance(default, Check):
                        default = default.default
                        if default is _DEFAULT:
                            raise KeyError

                except KeyError:
                    raise ConfigKeyMissing("Config is missing a key ({key})", name)

                setattr(inst, name, default)
                continue

            try:
                value = convert(raw_value, _type)
            except ConfigError as e:
                e.trace_key(name)
                raise e

            if value is _DEFAULT:
                raise ConfigValueError(f"{{key}} needs value of type {_type}, not {type(raw_value)}", name, raw_value)

            if check and not check.check(value):
                msg = check.fail_msg or "Provided value for {key} didn't pass {check}"
                raise ConfigValueError(msg, name, value, cls=_type, check=check)

            setattr(inst, name, value)

        inst.__init__()
        return inst


def traverse_config(config: ConfigObject, key: Union[str, List[str]]):
    if isinstance(key, str):
        key = key.split(".")
    target = config
    for _key in key:
        target = getattr(target, _key)
    return target


def config_items(config: ConfigObject) -> Iterator[Tuple[str, Any]]:
    for key in config_keys(config):
        yield key, getattr(config, key)


def config_keys(config: ConfigObject):
    return config.__attrs__.keys()
