from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, TextIO, Tuple, Union

import yaml
from aioredis import Redis
from motor.motor_asyncio import AsyncIOMotorCollection

from .tree import perm_tree

__all__ = ["LoadedRole", "PermLoader"]


class LoadedRole:
    _permissions: Dict[str, bool]
    _bases: List["LoadedRole"]

    def __init__(self, *, role_id: str, role_name: str, is_global: bool, bases: List[str] = None, permissions: Dict[str, bool] = None) -> None:
        self._role_id = role_id
        self._role_name = role_name
        self._is_global = is_global

        self._base_ids = bases or []
        self._permissions = permissions or {}

        self._bases = []

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    @property
    def role_id(self) -> str:
        return self._role_id

    @property
    def role_name(self) -> str:
        return self._role_name

    @property
    def is_global(self) -> bool:
        return self._is_global

    @classmethod
    def _resolve_permission_selector(cls, selector: Dict[str, str]) -> List[str]:
        target = perm_tree

        match = selector.get("match")
        if match:
            return target.match(match)

        raise Exception(f"Unknown permission selector {selector}")

    @classmethod
    def _specify_permission(cls, perms: Dict[str, bool], targets: Union[Iterable[str], Dict[str, str], None], grant: bool) -> None:
        if not targets:
            return

        if isinstance(targets, dict):
            targets = cls._resolve_permission_selector(targets)

        for target in targets:
            perms[target] = grant

    @classmethod
    def load(cls, data: Dict[str, Any]) -> "LoadedRole":
        bases = data.get("inherits_from")

        if bases and not isinstance(bases, list):
            bases = [bases]

        permissions = data.get("permissions") or {}

        cls._specify_permission(permissions, data.get("grant"), True)
        cls._specify_permission(permissions, data.get("deny"), False)

        role_name = data["name"]
        role_id = data.get("_id") or data.get("id") or role_name

        return cls(role_id=role_id, role_name=role_name, is_global=data.get("global", False), bases=bases, permissions=permissions)

    @classmethod
    def load_roles(cls, raw_roles: List[Dict[str, Any]]) -> List["LoadedRole"]:
        roles = []

        for role in raw_roles:
            roles.append(cls.load(role))

        return roles

    def is_explicit(self, key: str, *, bubble: bool = True) -> bool:
        key = str(key)

        explicit = self._permissions.get(key) is not None

        if explicit:
            return True
        elif bubble:
            return next((True for role in self._bases if role.is_explicit(key)), False)
        else:
            return False

    def has(self, key: str, default: Any = False, *, bubble: bool = True) -> bool:
        key = str(key)

        if key in self._permissions:
            return self._permissions[key]

        elif bubble:
            for role in self._bases:
                perm = role.has(key, default=None)
                if perm is not None:
                    return perm

        return default

    def _add_base(self, base: "LoadedRole") -> None:
        self._bases.append(base)

    def has_base(self, role_id: str) -> bool:
        for role in self._bases:
            if role.role_id == role_id:
                return True

        return False

    def to_dict(self) -> Dict[str, Any]:
        data = dict(_id=self.role_id, name=self.role_name, inherits_from=self._base_ids)
        data["global"] = self._is_global
        return data


class PermLoader:

    def __init__(self, roles: List[LoadedRole]) -> None:
        self.roles = roles

        self._resolve_inheritance()

    def _resolve_inheritance(self):
        for role in self.roles:
            for base in role._base_ids:
                base_role = self.roles[base]
                role._add_base(base_role)

    @classmethod
    async def load(cls, fp: Union[TextIO, Path]) -> "PermLoader":
        if isinstance(fp, Path):
            _data = fp.read_text()
        else:
            _data = fp

        data = yaml.safe_load(_data)

        roles = LoadedRole.load_roles(data["roles"])

        return cls(roles)

    @classmethod
    async def load_db(cls, role_collection: AsyncIOMotorCollection) -> Optional["PermLoader"]:
        cursor = await role_collection.find()

        roles = []
        async for raw_role in cursor:
            roles.append(LoadedRole.load(raw_role))

        if not roles:
            return None

        return cls(roles)

    def flatten(self) -> List[Tuple[str, bool]]:
        pass

    async def dump(self, redis: Redis):
        flattened = self.flatten()

        pairs = [(key, int(value)) for key, value in flattened]
        await redis.mset(*pairs)
