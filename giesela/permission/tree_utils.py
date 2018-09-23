import inspect
import typing


class PermNodeMeta(type):
    __namespace__: str

    def __str__(self):
        return self.__namespace__ or "root"


class Node(metaclass=PermNodeMeta):
    pass


def prepare_tree(tree: type, namespace: str = None):
    tree.__namespace__ = namespace

    for name, value in inspect.getmembers(tree):
        if name.startswith("_"):
            continue

        qualified_namespace = f"{namespace}.{value.__name__}" if namespace else value.__name__

        if isinstance(value, PermNodeMeta):
            prepare_tree(value, qualified_namespace)
        else:
            raise ValueError(f"{value} ({qualified_namespace}.{name}) shouldn't be in the tree??")

    if namespace:
        for name, value in typing.get_type_hints(tree).items():
            if value is str:
                setattr(tree, name, f"{namespace}.{name}")
