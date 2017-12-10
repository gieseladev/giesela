import asyncio
import re
from datetime import date

import requests
from discord import Embed

from giesela.nine_gag import ContentType, get_post
from giesela.utils import Response, block_user, command_info, owner_only
from moviepy import editor, video


class MiscCommands:
    async def cmd_9gag(self, channel, author, post_id):
        """
        ///|Usage
        `{command_prefix}9gag <id>`
        ///|Explanation
        Display the 9gag post with the specified id
        """

        post = get_post(post_id)
        if not post:
            return Response("couldn't find that 9gag post, sorreyyyy!")

        if post.content_type == ContentType.IMAGE:
            em = Embed(title=post.title, url=post.hyperlink, colour=9316352)
            em.set_author(name=author.display_name, icon_url=author.avatar_url)
            em.set_image(url=post.content_url)
            em.set_footer(text="{} upvotes | {} comments".format(
                post.upvotes, post.comment_count))

            await self.send_message(channel, embed=em)
        else:
            saveloc = "cache/pictures/9gag.gif"
            resp = requests.get(post.content_url)
            with open(saveloc, "wb+") as f:
                f.write(resp.content)
            clip = editor.VideoFileClip(saveloc)
            # clip.resize(.5)
            clip = video.fx.all.resize(clip, newsize=.55)
            clip.write_gif("cache/pictures/9gag.gif", fps=10)
            saveloc = "cache/pictures/9gag.gif"

            em = Embed(title=post.title, url=post.hyperlink, colour=9316352)
            em.set_author(name=author.display_name, icon_url=author.avatar_url)
            em.set_footer(text="{} upvotes | {} comments".format(
                post.upvotes, post.comment_count))

            await self.send_message(channel, embed=em)
            await self.send_file(channel, saveloc)

        for comment in post.comments[:3]:
            em = Embed(
                timestamp=comment.timestamp,
                colour=11946278,
                url=comment.permalink)
            em.set_author(
                name=comment.name,
                icon_url=comment.avatar,
                url=comment.profile_url)
            em.set_footer(text="{} upvotes | {} replies".format(
                comment.score, comment.reply_count))
            if comment.content_type == ContentType.TEXT:
                em.description = comment.content
            elif comment.content_type in (ContentType.IMAGE, ContentType.GIF):
                em.set_image(url=comment.content)

            await self.send_message(channel, embed=em)

    @command_info("3.8.1", 1499116644)
    async def cmd_register(self, server, author, token):
        """
        ///|Usage
        `{command_prefix}register <token>`
        ///|Explanation
        Use this command in order to use the [Giesela-Website](http://giesela.org).
        """

        # if GieselaServer.register_information(server.id, author.id, token.lower()):
        #     return Response("You've successfully registered yourself. Go back to your browser and check it out")
        # else:
        #     return Response("Something went wrong while registering. It could be that your code `{}` is wrong. Please make sure that you've entered it correctly.".format(token.upper()))

    @command_info("3.5.7", 1497823283, {
        "3.8.9": (1499645741, "`Giesenesis` rewrite was here")
    })
    async def cmd_interact(self, channel, message):
        """
        ///|Usage
        `{command_prefix}interact <query>`
        ///|Explanation
        Use everyday language to control Giesela
        ///|Disclaimer
        **Help out with the development of a "smarter" Giesela by testing out this new feature!**
        """

        await self.send_typing(channel)

        matcher = "^\{}?interact".format(self.config.command_prefix)
        query = re.sub(matcher, "", message.content,
                       flags=re.MULTILINE).strip()
        if not query:
            return Response("Please provide a query for me to work with")

        print("[INTERACT] \"{}\"".format(query))

        params = {
            "v": date.today().strftime("%d/%m/%y"),
            "q": query
        }
        headers = {"Authorization": "Bearer HVSTOLU3UQLR7YOYXCONQCCIQNHXZYDM"}
        resp = requests.get("https://api.wit.ai/message",
                            params=params, headers=headers)
        data = resp.json()
        entities = data["entities"]

        msg = ""

        for entity, data in entities.items():
            d = data[0]
            msg += "**{}** [{}] ({}% sure)\n".format(entity,
                                                     d["value"], round(d["confidence"] * 100, 1))

        return Response("This what I think you coulda meant (wip)\n{}".format(msg))

    async def cmd_getvideolink(self, player, message, channel, author, leftover_args):
        """
        Usage:
            {command_prefix}getvideolink ["pause video"]

        Sends the video link that gets you to the current location of the bot. Use "pause video" as argument to help you sync up the video.
        """

        if not player.current_entry:
            await self.safe_send_message(
                channel,
                "Can't give you a link for DUCKING NOTHING")
            return

        if "pause video" in " ".join(leftover_args).lower():
            player.pause()
            minutes, seconds = divmod(player.progress, 60)
            await self.safe_send_message(
                channel, player.current_entry.url + "#t={0}m{1}s".format(
                    minutes, seconds))
            msg = await self.safe_send_message(
                channel, "Resuming video in a few seconds!")
            await asyncio.sleep(1.5)

            for i in range(5, 0, -1):
                newMsg = "** %s **" if i <= 3 else "%s"
                newMsg %= str(i)

                msg = await self.safe_edit_message(
                    msg, newMsg, send_if_fail=True)
                await asyncio.sleep(1)

            msg = await self.safe_edit_message(
                msg, "Let's continue!", send_if_fail=True)
            player.resume()

        else:
            minutes, seconds = divmod(player.progress + 3, 60)
            await self.safe_send_message(
                channel, player.current_entry.url + "#t={0}m{1}s".format(
                    minutes, seconds))

    @command_info("3.7.3", 1498306682, {
        "3.7.4": (1498312423, "Fixed severe bug and added musixmatch as a source"),
        "3.9.2": (1499709472, "Fixed typo"),
        "4.5.6": (1502185982, "In order to properly make lyrics work with Webiesela, the source is seperated from the lyrics"),
        "4.5.7": (1502186654, "Lyrics are now temporarily cached within the entry")
    })
    async def cmd_lyrics(self, player, channel):
        """
        ///|Usage
        `{command_prefix}lyrics`
        ///|Explanation
        Try to find lyrics for the current entry and display 'em
        """

        await self.send_typing(channel)

        if not player.current_entry:
            return Response("There's no way for me to find lyrics for something that doesn't even exist!")

        title = player.current_entry.title
        lyrics = player.current_entry.lyrics

        if not lyrics:
            return Response("Couldn't find any lyrics for **{}**".format(title))
        else:
            return Response("**{title}**\n\n{lyrics}\n**Lyrics from \"{source}\"**".format(**lyrics))
