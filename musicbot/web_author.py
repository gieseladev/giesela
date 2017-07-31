class WebAuthor:

    def __init__(self, id, name, display_name, avatar_url, colour):
        self.id = id
        self.name = name
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.colour = colour

    @classmethod
    def from_id(cls, author_id):
        from .web_socket_server import GieselaServer
        user = GieselaServer.bot.get_global_user(author_id)
        return cls(author_id, user.name, user.display_name, user.avatar_url, dec_to_hex(user.colour.value))

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def __str__(self):
        return "[***REMOVED******REMOVED***/***REMOVED******REMOVED***]".format(self.id, self.name)

    def to_dict(self):
        return ***REMOVED***
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url.replace(".webp", ".png"),
            "colour": self.colour
        ***REMOVED***
