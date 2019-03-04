import random
from typing import Type, TypeVar, cast

import pytest
from discord import Guild, Member, User
from discord.ext.commands import Bot

from giesela.permission.role_target import RoleTarget, get_role_targets_for, sort_targets_by_specificity


def test_sort():
    owner = RoleTarget("#owner")
    everyone = RoleTarget("#everyone")
    guild_owner = RoleTarget("#guild_owner")
    guild_admin = RoleTarget("#guild_admin")
    user = RoleTarget("1231231")
    member = RoleTarget("9898989:1231231")
    role = RoleTarget("@9898989:656456")

    sorted_order = [owner, user, guild_owner, guild_admin, member, role, everyone]

    for i in range(5):
        unordered = sorted_order.copy()
        random.shuffle(unordered)
        assert sort_targets_by_specificity(unordered) == sorted_order


T = TypeVar("T")


@pytest.mark.asyncio
async def test_get_roles_for():
    owner_id = 1236712376

    class MockBot:
        async def is_owner(self, user: User) -> bool:
            return user.id == owner_id

    def mock_create(cls: Type[T], **attrs) -> T:
        inst = object.__new__(cls)
        for k, v in attrs.items():
            setattr(inst, k, v)

        return inst

    bot = cast(Bot, MockBot())

    owner = mock_create(User, id=owner_id)
    assert await get_role_targets_for(bot, owner) == [RoleTarget("#owner"), RoleTarget(str(owner_id)), RoleTarget("#everyone")]
    assert await get_role_targets_for(bot, owner, guild_only=True) == []

    guild = mock_create(Guild, id=123124, owner_id=56456456)
    user = mock_create(User, id=56456456)
    member = mock_create(Member, _user=user, guild=guild, roles=[])
    setattr(guild, "_members", {member.id: member})
    assert await get_role_targets_for(bot, member) == [RoleTarget("56456456"), RoleTarget("123124:56456456"), RoleTarget("#guild_owner"),
                                                       RoleTarget("#everyone")]

    assert await get_role_targets_for(bot, member, guild_only=True) == [RoleTarget("123124:56456456"), RoleTarget("#guild_owner")]
