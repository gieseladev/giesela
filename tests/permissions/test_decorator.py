from giesela.permission import perm_tree
from giesela.permission.decorators import get_decorated_permissions, has_global_permission, has_permission


def test_decorators():
    @has_global_permission(perm_tree.admin.control.execute)
    @has_permission(perm_tree.admin.control.shutdown)
    def func():
        pass

    assert get_decorated_permissions(func, global_only=False) == [perm_tree.admin.control.shutdown]
    assert get_decorated_permissions(func, global_only=True) == [perm_tree.admin.control.execute]
