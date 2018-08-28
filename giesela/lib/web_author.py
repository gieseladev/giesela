from typing import TYPE_CHECKING

from discord import User

if TYPE_CHECKING:
    from giesela.bot import Giesela


class WebAuthor:
    bot: "Giesela" = None

    def __init__(self, user_id: int, name: str, display_name: str, avatar_url: str):
        self.id = user_id
        self.name = name
        self.display_name = display_name
        self.avatar_url = avatar_url

    def __str__(self) -> str:
        return "[{}/{}]".format(self.id, self.name)

    @classmethod
    def from_id(cls, author_id: int) -> "WebAuthor":
        user = cls.bot.get_user(author_id)

        return cls.from_user(user)

    @classmethod
    def from_user(cls, user: User) -> "WebAuthor":
        return cls(user.id, user.name, user.display_name, user.avatar_url_as(format="png"))

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    @property
    def discord_user(self) -> User:
        return WebAuthor.bot.get_user(self.id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url
        }
