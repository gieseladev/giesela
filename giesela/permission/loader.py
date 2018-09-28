from pathlib import Path
from typing import Any, Dict, List, TextIO, Tuple, Union

import yaml
from aioredis import Redis
from motor.motor_asyncio import AsyncIOMotorCollection

__all__ = ["LoadedRole", "PermLoader"]


class LoadedRole:
    _permissions: Dict[str, bool]
    _bases: List["LoadedRole"]

    def __init__(self, *, role_id: str, role_name: str, is_global: bool, bases: List[str] = None, permissions: Dict[str, bool] = None):
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

    @classmethod
    def load(cls, data: Dict[str, Any]) -> "LoadedRole":
        bases = data.get("inherits_from")

        if bases and not isinstance(bases, list):
            bases = [bases]

        grants = data.get("grant") or []
        denies = data.get("deny") or []

        permissions = {}
        for grant in grants:
            permissions[grant] = True

        for deny in denies:
            permissions[deny] = False

        role_name = data["name"]
        role_id = data.get("_id") or data.get("id")

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

    def _add_base(self, base: "LoadedRole"):
        self._bases.append(base)

    def has_base(self, role_id: str) -> bool:
        for role in self._bases:
            if role.role_id == role_id:
                return True

        return False


class PermLoader:

    def __init__(self, roles: List[LoadedRole]):
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
            fp = fp.read_text()

        data = yaml.safe_load(fp)

        roles = LoadedRole.load_roles(data["roles"])

        return cls(roles)

    @classmethod
    async def load_db(cls, collection: AsyncIOMotorCollection) -> "PermLoader":
        pass

    def flatten(self) -> List[Tuple[str, bool]]:
        pass

    async def dump(self, redis: Redis):
        flattened = self.flatten()

        pairs = [(key, int(value)) for key, value in flattened]
        await redis.mset(*pairs)
