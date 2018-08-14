from discord import TextChannel, User

from giesela import Giesela, Playlist
from giesela.cogs.player import Player
from ..interactive import EmbedViewer


class PlaylistViewer(EmbedViewer):
    bot: Giesela
    player_cog = Player
    playlist: Playlist

    def __init__(self, bot: Giesela, channel: TextChannel, user: User, playlist: Playlist, **kwargs):
        super().__init__(channel, user, **kwargs)

        self.bot = bot
        self.player_cog = bot.cogs["Player"]
        self.playlist = playlist

    # @emoji_handler("▶", pos=999)
    # async def play_playlist(self, **_):
    #     player = await self.player_cog.get_player(self.channel.guild, member=self.user)
    #     await self.playlist.play(player.queue, channel=self.channel, author=self.user)
