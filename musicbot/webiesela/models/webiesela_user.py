import discord


class WebieselaUser:
    bot = None

    def __init__(self, discord_id, discriminator, name, avatar_url, server_id, server_name, member):
        self.discord_id = discord_id
        self.name = name
        self.discriminator = discriminator
        self.avatar_url = avatar_url

        self.server_id = server_id
        self.server_name = server_name

        self.member = member

    def __str__(self):
        return "{}@[{}]".format(self.tag, self.server_name)

    @classmethod
    def from_member(cls, member):
        return cls(member.id, member.discriminator, member.name, member.avatar_url, member.server.id, member.server.name, member)

    @classmethod
    def from_dict(cls, data):
        server = cls.bot.get_server(data["server"]["id"])
        member = server.get_member(data["id"])
        return cls.from_member(member)

    @property
    def tag(self):
        return "{}#{}".format(self.name, self.discriminator)

    def to_dict(self):
        return {
            "id": self.discord_id,
            "name": self.name,
            "tag": self.tag,
            "avatar_url": self.avatar_url,
            "server": {
                "id": self.server_id,
                "name": self.server_name,
            }
        }
