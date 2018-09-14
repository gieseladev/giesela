import inspect
import typing


class PermNodeMeta(type):
    __namespace__: str

    def __str__(self):
        return self.__namespace__


class Node(metaclass=PermNodeMeta):
    pass


def prepare_tree(tree: type, namespace: str = None):
    if namespace:
        qualified_name = f"{namespace}.{tree.__name__}"
    else:
        qualified_name = tree.__name__

    tree.__namespace__ = qualified_name

    for name, value in inspect.getmembers(tree):
        if name.startswith("_"):
            continue

        if isinstance(value, PermNodeMeta):
            prepare_tree(value, qualified_name)
        else:
            raise ValueError(f"{value} ({qualified_name}.{name}) shouldn't be in the tree??")

    for name, value in typing.get_type_hints(tree).items():
        if value is str:
            setattr(tree, name, f"{qualified_name}.{name}")
