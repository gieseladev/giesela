import inspect
import typing
from typing import Any, Dict, Iterable, List, Tuple, Union

__all__ = ["Node", "PermSelector", "PermSpecType", "PermissionType", "CompiledPerms"]

CompiledPerms = Dict[str, int]

PermSelector = Dict[str, Any]
PermSpecType = Union[PermSelector, str]


class PermNodeMeta(type):
    """Metaclass of a `Node` of a permission tree."""
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
        """Direct permissions of this node with namespace."""
        return [f"{cls.__namespace__}.{perm}" for perm in cls.__perms__]

    @property
    def all_permissions(cls) -> List[str]:
        """Own qualified permissions and children's qualified permissions"""
        perms = cls.qualified_perms

        for child in cls.__children__.values():
            perms.extend(child.all_permissions)
        return perms

    def prepare(cls) -> None:
        """Prepare this node and all its children."""
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
        """Create an indented tree-like structure of the node and its children."""
        lines: List[str] = []
        for perm in cls.__perms__:
            lines.append(level * prefix + perm)

        for child in cls.__children__.values():
            lines.append(f"{level * prefix}{child.__name__}:")
            lines.extend(child._render(prefix, level=level + 1))

        return lines

    def traverse(cls, key: str) -> Union["PermNodeMeta", str]:
        """Go down the tree and return the result."""
        parts = key.split(".")
        target = cls
        for part in parts:
            target = getattr(target, part)

        return target

    def has(cls, key: str) -> bool:
        """Check whether this tree has the qualified permission."""
        try:
            target = cls.traverse(key)
        except AttributeError:
            return False
        else:
            return isinstance(target, (str, PermNodeMeta))

    def match(cls, query: str) -> List[str]:
        if "*" in query:
            start, end = query.split("*", maxsplit=1)
            return [perm for perm in cls.all_permissions if perm.startswith(start) and perm.endswith(end)]
        else:
            raise Exception(f"Unknown match query: {query}")

    def unfold_perm(cls, perm: "PermissionType") -> List[str]:
        if isinstance(perm, str):
            perm = cls.traverse(perm)

        if isinstance(perm, str):
            return [perm]
        else:
            return perm.all_permissions

    def unfold_perms(cls, sorted_perms: Iterable[Tuple[str, int]]) -> CompiledPerms:
        """Unfold the given permissions to fully qualified permissions."""
        perms: CompiledPerms = {}

        for key, value in sorted_perms:
            perm = cls.traverse(key)
            if isinstance(perm, str):
                perms[perm] = value
            else:
                for _perm in perm.all_permissions:
                    perms[_perm] = value

        return perms

    def resolve_permission_selector(cls, selector: PermSelector) -> List[str]:
        """Resolve a special selector for permissions."""
        match = selector.get("match")
        if match:
            return cls.match(match)

        raise ValueError(f"Unknown permission selector {selector}")

    def resolve_permission_specifiers(cls, perms: CompiledPerms, specifiers: Iterable[PermSpecType], grant: int) -> None:
        """Resolve a bunch of permission specifiers and store the result in the provided permission object."""
        _targets = list(specifiers)

        while _targets:
            target = _targets.pop()
            if isinstance(target, dict):
                _targets.extend(cls.resolve_permission_selector(target))
                continue

            if not cls.has(target):
                raise KeyError(f"Permission \"{target}\" doesn't exist!")

            perms[target] = grant

    def compile_permissions(cls, grant: List[PermSpecType], deny: List[PermSpecType]) -> CompiledPerms:
        """Compile the given permissions into a single object."""
        perms = {}
        cls.resolve_permission_specifiers(perms, grant, 1)
        cls.resolve_permission_specifiers(perms, deny, 0)

        sorted_perms = order_by_least_specificity(perms)
        return cls.unfold_perms(sorted_perms)


class Node(metaclass=PermNodeMeta):
    """Node of a permission tree."""
    ...


PermissionType = Union[str, Node]


def order_by_least_specificity(perms: CompiledPerms) -> List[Tuple[str, int]]:
    """Order the permissions by their specificity in ascending orrder"""
    return [(key, perms[key]) for key in sorted(perms.keys(), key=len)]
