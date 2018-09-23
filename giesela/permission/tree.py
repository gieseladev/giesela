from .tree_utils import Node, prepare_tree

__all__ = ["perms"]


class Admin:
    pass


class Player:
    pass


class Playlist:
    pass


class perms(Node):
    class admin(Node):
        class control(Node):
            execute: str
            shutdown: str
            impersonate: str

        class config(Node):
            class runtime(Node):
                view: str

            class guild(Node):
                view: str

        class permissions(Node):
            class runtime(Node):
                edit_roles: str
                assign_roles: str

            class guild(runtime):
                pass

        class appearance(Node):
            name: str
            avatar: str

    class music(Node):
        class queue(Node):
            class manipulate(Node):
                class enqueue(Node):
                    replay: str
                    stream: str
                    playlist: str

                remove: str
                move: str
                edit: str

            class inspect(Node):
                current: str
                history: str
                queue: str

        class player(Node):
            class manipulate(Node):
                class skip(Node):
                    seek: str

                pause: str
                volume: str

        class summon(Node):
            steal: str

    class playlist(Node):
        class all(Node):
            edit: str
            remove: str

        create: str
        export: str

    class webiesela(Node):
        pass


prepare_tree(perms)
