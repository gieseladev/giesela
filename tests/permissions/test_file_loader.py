import pytest

from giesela.permission import PermissionFileError
from giesela.permission.file_loader import _ensure_type, _get_synonym, _make_list, check_permissions, load_role


def test__ensure_type():
    with pytest.raises(PermissionFileError):
        _ensure_type("please raise", int)

    assert _ensure_type(True, bool) is True

    try:
        _ensure_type("hello", int, "test string {obj_type}")
    except PermissionFileError as e:
        assert str(e) == "test string str"
    else:
        pytest.fail("Didn't raise an error!")


def test__make_list():
    assert _make_list(None) == []
    assert _make_list("hello") == ["hello"]
    l = ["a", "b"]
    assert _make_list(l) is l


def test__get_synonym():
    data = {
        "key": "hello",
        "k": "world",
        "a": None
    }

    assert _get_synonym(data, "keys", "key", "test") is data["key"]
    assert _get_synonym(data, "a", "k") is data["a"]
    assert _get_synonym(data, "b", "c") is None

    assert _get_synonym(data, "k", "key", "a") is data["k"]


def test_check_permissions():
    correct_perms = [
        "admin.control",
        {"match": "queue.*"}
    ]

    check_permissions(correct_perms)

    with pytest.raises(PermissionFileError):
        check_permissions([{"select": 3}])

    with pytest.raises(PermissionFileError):
        check_permissions([{"match": 3}])

    with pytest.raises(PermissionFileError):
        check_permissions(["admin.control.execute.order.66"])

    with pytest.raises(PermissionFileError):
        check_permissions(["perm_tree"])


def test_load_roles():
    with pytest.raises(PermissionFileError, match="Role needs to have a name"):
        load_role({}, False)
