from musicbot.utils import dec_to_hex


class WebAuthor:
    bot = None

    def __init__(self, id, name, display_name, avatar_url, colour):
        self.id = id
        self.name = name
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.colour = colour

    @classmethod
    def from_id(cls, author_id):
        user = WebAuthor.bot.get_global_user(author_id)

        return cls.from_user(user)

    @classmethod
    def from_user(cls, user):
        return cls(user.id, user.name, user.display_name, user.avatar_url, dec_to_hex(user.colour.value))

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    @property
    def discord_user(self):
        return WebAuthor.bot.get_global_user(self.id)

    def __str__(self):
        return "[{}/{}]".format(self.id, self.name)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url.replace(".webp", ".png"),
            "colour": self.colour
        }
