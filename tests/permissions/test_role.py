import pytest

from giesela.permission.role import RoleContext, build_role_order_value, get_higher_or_equal_role_contexts, get_higher_role_contexts, \
    get_role_context_from_order_id


def test_role_context():
    assert RoleContext.GUILD.is_guild
    assert RoleContext.GUILD.is_guild_specific


def test_context_from_id():
    assert get_role_context_from_order_id("1515151515").is_guild
    assert get_role_context_from_order_id("superglobal") == RoleContext.SUPERGLOBAL
    with pytest.raises(ValueError):
        get_role_context_from_order_id("nothing of importance")


def test_higher_contexts():
    assert list(get_higher_role_contexts(RoleContext.GUILD)) == [RoleContext.SUPERGLOBAL, RoleContext.GUILD_DEFAULT]
    assert list(get_higher_role_contexts(RoleContext.SUPERGLOBAL)) == []
    assert list(get_higher_role_contexts(RoleContext.GLOBAL)) == [RoleContext.SUPERGLOBAL]


def test_higher_or_equal_contexts():
    assert RoleContext.GLOBAL in set(get_higher_or_equal_role_contexts(RoleContext.GLOBAL))


def test_build_role_order_value():
    assert build_role_order_value(RoleContext.SUPERGLOBAL, 15) == (RoleContext.SUPERGLOBAL.order_value, 15)
    assert build_role_order_value(1, 15) == (1, 15)
