import discord


class WebieselaUser:
    bot = None

    def __init__(self, discord_id, ):
        self.discord_id = discord_id

    @classmethod
    def from_member(cls, member):
        return cls()

    @classmethod
    def from_dict(cls, data):
        return cls.from_member(cls.bot.get_member(data["id"]))

    def to_dict(self):
        return {
            "id": self.discord_id
        }
