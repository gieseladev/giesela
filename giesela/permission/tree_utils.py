import inspect
import typing
from typing import Any, Dict, List, Tuple, Union

__all__ = ["Node"]


class PermNodeMeta(type):
    __namespace__: str
    __children__: Dict[str, "PermNodeMeta"]
    __perms__: List[str]

    def __init__(cls, name: str, bases: Tuple[type, ...], body: Dict[str, Any]) -> None:
        super().__init__(name, bases, body)

        cls.__namespace__ = None
        cls.__children__ = {}
        cls.__perms__ = []

        for name, value in inspect.getmembers(cls):
            if name.startswith("_"):
                continue

            if isinstance(value, PermNodeMeta):
                cls.__children__[name] = value

    def __str__(cls) -> str:
        return cls.__namespace__ or "root"

    @property
    def qualified_perms(cls) -> List[str]:
        return [f"{cls.__namespace__}.{perm}" for perm in cls.__perms__]

    @property
    def all_permissions(cls) -> List[str]:
        perms = cls.qualified_perms

        for child in cls.__children__.values():
            perms.extend(child.all_permissions)
        return perms

    def prepare(cls) -> None:
        targets: List[PermNodeMeta] = [cls]

        while targets:
            target = targets.pop()
            target_ns = target.__namespace__

            for name, child in target.__children__.items():
                targets.append(child)

                child_ns = (f"{target_ns}." if target_ns else "") + name
                child.__namespace__ = child_ns

                for perm, value in typing.get_type_hints(child).items():
                    if value is str:
                        child.__perms__.append(perm)
                        qualified_name = f"{child_ns}.{perm}"
                        setattr(child, perm, qualified_name)

    def _render(cls, prefix: str = " ", *, level: int = 0) -> List[str]:
        lines: List[str] = []
        for perm in cls.__perms__:
            lines.append(level * prefix + perm)

        for child in cls.__children__.values():
            lines.append(f"{level * prefix}{child.__name__}:")
            lines.extend(child._render(prefix, level=level + 1))

        return lines

    def traverse(cls, key: str) -> Union["PermNodeMeta", str]:
        parts = key.split(".")
        target = cls
        for part in parts:
            target = getattr(target, part)

        return target

    def match(cls, query: str) -> List[str]:
        if query == "*":
            return cls.all_permissions
        else:
            raise Exception(f"Unknown match query: {query}")


class Node(metaclass=PermNodeMeta): ...
