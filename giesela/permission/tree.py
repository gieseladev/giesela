class perms:
    class admin:
        class control:
            execute: str
            shutdown: str
            impersonate: str

        class config:
            runtime: str

        class appearance:
            name: str
            avatar: str

    class music:
        class queue:
            class manipulate:
                class enqueue:
                    add: str
                    replay: str
                    stream: str

                remove: str
                move: str

            class inspect:
                history: str
                queue: str

        class player:
            class manipulate:
                class seek:
                    skip: str
                    seek: str

                pause: str
                volume: str

        class summon:
            summon: str
            steal: str

    class playlist:
        class owned:
            create: str
            export: str

        class all(owned):
            edit: str
            remove: str

    webiesela: str
