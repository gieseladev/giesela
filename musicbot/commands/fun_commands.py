import re
from random import shuffle

import asyncio
from musicbot.cleverbot import CleverWrap
from musicbot.config import ConfigDefaults
from musicbot.games.game_2048 import Game2048
from musicbot.games.game_cah import GameCAH
from musicbot.games.game_connect_four import GameConnectFour
from musicbot.games.game_hangman import GameHangman
from musicbot.utils import (Response, block_user, command_info, owner_only,
                            random_line)


class FunCommands:
    async def cmd_c(self, author, channel, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***c <message>

        have a chat
        """
        if len(leftover_args) < 1:
            return Response("You need to actually say something...")

        cb, nick = self.chatters.get(author.id, (None, None))
        if cb is None:
            cb = CleverWrap("CCC8n_IXK43aOV38rcWUILmYUBQ")
            nick = random_line(ConfigDefaults.name_list).strip().title()
            self.chatters[author.id] = (cb, nick)

        await self.send_typing(channel)
        msgContent = " ".join(leftover_args)

        while True:
            answer = cb.say(msgContent)
            answer = re.sub(r"\b[C|c]leverbot\b", "you", answer)
            answer = re.sub(r"\b[C|c][B|b]\b", "you", answer)
            base_answer = re.sub("[^a-z| ]+|\s***REMOVED***2,***REMOVED***", "", answer.lower())
            if base_answer not in "whats your name;what is your name;tell me your name".split(
                    ";") and not any(
                        q in base_answer
                        for q in
                        "whats your name; what is your name;tell me your name".
                        split(";")):
                break

        await asyncio.sleep(len(answer) / 5.5)
        print("<" + str(author.name) + "> " + msgContent + "\n<Bot> " +
              answer + "\n")
        return Response(answer)

    @block_user
    async def cmd_cah(self, message, channel, author, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***cah create
            ***REMOVED***command_prefix***REMOVED***cah join <token>
            ***REMOVED***command_prefix***REMOVED***cah leave <token>

            ***REMOVED***command_prefix***REMOVED***cah start <token>
            ***REMOVED***command_prefix***REMOVED***cah stop <token>

        Play a cards against humanity game

        References:
            ***REMOVED***command_prefix***REMOVED***help cards
                -learn how to create/edit cards
            ***REMOVED***command_prefix***REMOVED***help qcards
                -learn about how to create/edit question cards
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else None

        if argument == "create":
            if self.cah.is_user_in_game(author.id):
                g = self.cah.get_game(author.id)
                return Response(
                    "You can't host a game if you're already in one\nUse `***REMOVED******REMOVED***cah leave ***REMOVED******REMOVED***` to leave your current game".
                    format(self.config.command_prefix, g.token),
                    delete_after=15)

            token = self.cah.new_game(author.id)
            return Response(
                "Created a new game.\nUse `***REMOVED***0***REMOVED***cah join ***REMOVED***1***REMOVED***` to join this game and\nwhen everyone's in use `***REMOVED***0***REMOVED***cah start ***REMOVED***1***REMOVED***`".
                format(self.config.command_prefix, token),
                delete_after=1000)
        elif argument == "join":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token")

            if self.cah.is_user_in_game(author.id):
                g = self.cah.get_game_from_user_id(author.id)
                return Response(
                    "You can only be part of one game at a time!\nUse `***REMOVED******REMOVED***cah leave ***REMOVED******REMOVED***` to leave your current game".
                    format(self.config.command_prefix, g.token),
                    delete_after=15)

            g = self.cah.get_game(token)

            if g is None:
                return Response(
                    "This game does not exist *shrugs*")

            if g.in_game(author.id):
                return Response(
                    "You're already in this game!")

            if self.cah.user_join_game(author.id, token):
                return Response("Successfully joined the game *****REMOVED******REMOVED*****".format(
                    token.upper()))
            else:
                return Response(
                    "Failed to join game *****REMOVED******REMOVED*****".format(token.upper()))
        elif argument == "leave":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token")

            g = self.cah.get_game(token)

            if g is None:
                return Response(
                    "This game does not exist *shrugs*")

            if not g.in_game(author.id):
                return Response(
                    "You're not part of this game!")

            if self.cah.player_leave_game(author.id, token):
                return Response(
                    "Successfully left the game *****REMOVED******REMOVED*****".format(token.upper()))
            else:
                return Response(
                    "Failed to leave game *****REMOVED******REMOVED*****".format(token.upper()))
        elif argument == "start":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            if token is None:
                return Response("You need to provide a token")

            g = self.cah.get_game(token)
            if g is None:
                return Response("This game does not exist!")

            if not g.is_owner(author.id):
                return Response(
                    "Only the owner may start a game!")

            if not g.enough_players():
                return Response(
                    "There are not enough players to start this game.\nUse `***REMOVED******REMOVED***cah join ***REMOVED******REMOVED***` to join a game".
                    format(self.config.command_prefix, g.token),
                    delete_after=15)

            if not g.start_game():
                return Response(
                    "This game has already started!")
        elif argument == "stop":
            token = leftover_args[
                1].lower() if len(leftover_args) > 1 else None
            g = self.cah.get_game(token)
            if g is None:
                return Response("This game does not exist!")

            if not g.is_owner(author.id):
                return Response(
                    "Only the owner may stop a game!")

            self.cah.stop_game(g.token)
            return Response(
                "Stopped the game *****REMOVED******REMOVED*****".format(token))

    @block_user
    async def cmd_cards(self, server, channel, author, message, leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***cards list [@mention] [text | likes | occurences | date | random | id | author | none]
                -list all the available cards
            ***REMOVED***command_prefix***REMOVED***cards create <text>
                -create a new card with text
            ***REMOVED***command_prefix***REMOVED***cards edit <id> <new_text>
                -edit a card by its id
            ***REMOVED***command_prefix***REMOVED***cards info <id>
                -Get more detailed information about a card
            ***REMOVED***command_prefix***REMOVED***cards search <query>
                -Search for a card
            ***REMOVED***command_prefix***REMOVED***cards delete <id>
                -Delete a question card

        Here you manage the non question cards
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else None

        if argument == "list":
            sort_modes = ***REMOVED***"text": (lambda entry: entry.text, False, lambda entry: None), "random": None, "occurences": (lambda entry: entry.occurences, True, lambda entry: entry.occurences), "date": (
                lambda entry: entry.creation_date, True, lambda entry: prettydate(entry.creation_date)), "author": (lambda entry: entry.creator_id, False, lambda entry: self.get_global_user(entry.creator_id).name), "id": (lambda entry: entry.id, False, lambda entry: None), "likes": (lambda entry: entry.like_dislike_ratio, True, lambda entry: "***REMOVED******REMOVED***%".format(int(entry.like_dislike_ratio * 100)))***REMOVED***

            cards = self.cah.cards.cards.copy(
            ) if message.mentions is None or len(message.mentions) < 1 else [
                x for x in self.cah.cards.cards.copy()
                if x.creator_id in [u.id for u in message.mentions]
            ]
            sort_mode = leftover_args[1].lower(
            ) if len(leftover_args) > 1 and leftover_args[1].lower(
            ) in sort_modes.keys() else "none"

            display_info = None

            if sort_mode == "random":
                shuffle(cards)
            elif sort_mode != "none":
                cards = sorted(
                    cards,
                    key=sort_modes[sort_mode][0],
                    reverse=sort_modes[sort_mode][1])
                display_info = sort_modes[sort_mode][2]

            await self.card_viewer(channel, author, cards, display_info)
        elif argument == "search":
            search_query = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None

            if search_query is None:
                return Response(
                    "You need to provide a query to search for!",
                    delete_after=15)

            results = self.cah.cards.search_card(search_query, 3)

            if len(results) < 1:
                return Response("**Didn't find any cards!**")

            card_string = "***REMOVED***0.id***REMOVED***. \"***REMOVED***1***REMOVED***\""
            cards = []
            for card in results:
                cards.append(
                    card_string.format(card, card.text.replace("$", "_____")))

            return Response(
                "**I found the following cards:**\n\n" + "\n".join(cards),
                delete_after=40)
        elif argument == "info":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            card = self.cah.cards.get_card(card_id)
            if card is not None:
                info = "Card *****REMOVED***0.id***REMOVED***** by ***REMOVED***1***REMOVED***\n```\n\"***REMOVED***0.text***REMOVED***\"\nused ***REMOVED***0.occurences***REMOVED*** time***REMOVED***2***REMOVED***\ndrawn ***REMOVED***0.picked_up_count***REMOVED*** time***REMOVED***5***REMOVED***\nliked by ***REMOVED***6***REMOVED***% of players\ncreated ***REMOVED***3***REMOVED***```\nUse `***REMOVED***4***REMOVED***cards edit ***REMOVED***0.id***REMOVED***` to edit this card"
                return Response(
                    info.format(card,
                                self.get_global_user(card.creator_id).mention,
                                "s" if card.occurences != 1 else "",
                                prettydate(card.creation_date), self.config.
                                command_prefix, "s" if card.picked_up_count !=
                                1 else "", int(card.like_dislike_ratio * 100)))

            return Response(
                "There's no card with that id. Use `***REMOVED******REMOVED***cards list` to list all the possible cards".
                format(self.config.command_prefix))
        elif argument == "create":
            text = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...")
            if len(text) > 140:
                return Response("Maybe a bit too long?")

            already_has_card, card = self.cah.cards.card_with_text(text)
            if already_has_card:
                return Response(
                    "There's already a card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***cards info ***REMOVED***0***REMOVED***` to find out more about this card".
                    format(card.id, self.config.command_prefix))

            card_id = self.cah.cards.add_card(text, author.id)
            return Response("Successfully created card *****REMOVED******REMOVED*****".format(card_id))
        elif argument == "edit":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            try:
                card_id_value = int(card_id)
            except:
                return Response("An id must be a number")

            if card_id is None:
                return Response(
                    "You need to provide the card's id!")

            text = " ".join(
                leftover_args[2:]) if len(leftover_args) > 1 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...")
            if len(text) > 140:
                return Response("Maybe a bit too long?")

            already_has_card, card = self.cah.cards.card_with_text(text)
            if already_has_card and card.id != card_id_value:
                return Response(
                    "There's already a card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***cards info ***REMOVED***0***REMOVED***` to find out more about this card".
                    format(card.id, self.config.command_prefix))

            if self.cah.cards.edit_card(card_id, text):
                return Response(
                    "Edited card <*****REMOVED******REMOVED*****>".format(card_id))
            else:
                return Response(
                    "There's no card with that id")
        elif argument == "delete":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            if card_id is None:
                return Response(
                    "You must specify the card id")

            if self.cah.cards.remove_card(card_id):
                return Response(
                    "Deleted card <*****REMOVED******REMOVED*****>".format(card_id))
            else:
                return Response(
                    "Could not remove card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
        else:
            return await self.cmd_help(channel, ["cards"])

    async def card_viewer(self,
                          channel,
                          author,
                          cards,
                          display_additional=None):
        cmds = ("n", "p", "exit")
        site_interface = "**Cards | Page ***REMOVED***0***REMOVED*** of ***REMOVED***1***REMOVED*****\n```\n***REMOVED***2***REMOVED***\n```\nShit you can do:\n`n`: Switch to the next page\n`p`: Switch to the previous page\n`exit`: Exit the viewer"
        card_string = "<***REMOVED******REMOVED***> [***REMOVED******REMOVED***]***REMOVED******REMOVED***"

        items_per_page = 20
        timeout = 60
        current_page = 0

        total_pages, items_on_last_page = divmod(
            len(cards) - 1, items_per_page)

        def msg_check(msg):
            return msg.content.lower().strip().startswith(cmds)

        while True:
            start_index = current_page * items_per_page
            end_index = start_index + \
                (items_per_page - 1 if current_page <
                 total_pages else items_on_last_page)
            page_cards = cards[start_index:end_index]

            page_cards_texts = []
            for p_c in page_cards:
                page_cards_texts.append(
                    card_string.format(
                        p_c.id, p_c.text, "" if display_additional is None or
                        display_additional(p_c) is None else " | ***REMOVED******REMOVED***".format(
                            display_additional(p_c))))

            interface_msg = await self.safe_send_message(
                channel,
                site_interface.format(current_page + 1, total_pages + 1,
                                      "\n".join(page_cards_texts)))
            user_msg = await self.wait_for_message(
                timeout, author=author, channel=channel, check=msg_check)

            if not user_msg:
                await self.safe_delete_message(interface_msg)
                break

            content = user_msg.content.lower().strip()

            if content.startswith("n"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page + 1) % (total_pages + 1)
            elif content.startswith("p"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page - 1) % (total_pages + 1)
            elif content.startswith("exit"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                break

        await self.safe_send_message(
            channel, "Closed the card viewer!", expire_in=20)

    @block_user
    async def cmd_qcards(self, server, channel, author, message,
                         leftover_args):
        """
        Usage:
            ***REMOVED***command_prefix***REMOVED***qcards list [@mention] [text | likes | occurences | date | author | id | blanks | random | none]
                -list all the available question cards
            ***REMOVED***command_prefix***REMOVED***qcards create <text (use $ for blanks)>
                -create a new question card with text and if you want the number of cards to draw
            ***REMOVED***command_prefix***REMOVED***qcards edit <id> <new_text>
                -edit a question card by its id
            ***REMOVED***command_prefix***REMOVED***qcards info <id>
                -Get more detailed information about a question card
            ***REMOVED***command_prefix***REMOVED***qcards search <query>
                -Search for a question card
            ***REMOVED***command_prefix***REMOVED***qcards delete <id>
                -Delete a question card

        Here you manage the question cards
        """

        argument = leftover_args[0].lower() if len(leftover_args) > 0 else None

        if argument == "list":
            sort_modes = ***REMOVED***"text": (lambda entry: entry.text, False, lambda entry: None), "random": None, "occurences": (lambda entry: entry.occurences, True, lambda entry: entry.occurences), "date": (lambda entry: entry.creation_date, True, lambda entry: prettydate(entry.creation_date)), "author": (lambda entry: entry.creator_id, False, lambda entry: self.get_global_user(
                entry.creator_id).name), "id": (lambda entry: entry.id, False, lambda entry: None), "blanks": (lambda entry: entry.number_of_blanks, True, lambda entry: entry.number_of_blanks), "likes": (lambda entry: entry.like_dislike_ratio, True, lambda entry: "***REMOVED******REMOVED***%".format(int(entry.like_dislike_ratio * 100)))***REMOVED***

            cards = self.cah.cards.question_cards.copy(
            ) if message.mentions is None or len(message.mentions) < 1 else [
                x for x in self.cah.cards.question_cards.copy()
                if x.creator_id in [u.id for u in message.mentions]
            ]
            sort_mode = leftover_args[1].lower(
            ) if len(leftover_args) > 1 and leftover_args[1].lower(
            ) in sort_modes.keys() else "none"

            display_info = None

            if sort_mode == "random":
                shuffle(cards)
            elif sort_mode != "none":
                cards = sorted(
                    cards,
                    key=sort_modes[sort_mode][0],
                    reverse=sort_modes[sort_mode][1])
                display_info = sort_modes[sort_mode][2]

            await self.qcard_viewer(channel, author, cards, display_info)
        elif argument == "search":
            search_query = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None

            if search_query is None:
                return Response(
                    "You need to provide a query to search for!",
                    delete_after=15)

            results = self.cah.cards.search_question_card(search_query, 3)

            if len(results) < 1:
                return Response(
                    "**Didn't find any question cards!**")

            card_string = "***REMOVED***0.id***REMOVED***. \"***REMOVED***1***REMOVED***\""
            cards = []
            for card in results:
                cards.append(
                    card_string.format(card,
                                       card.text.replace("$", "\_\_\_\_\_")))

            return Response(
                "**I found the following question cards:**\n\n" +
                "\n".join(cards),
                delete_after=40)
        elif argument == "info":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            card = self.cah.cards.get_question_card(card_id)
            if card is not None:
                info = "Question Card *****REMOVED***0.id***REMOVED***** by ***REMOVED***1***REMOVED***\n```\n\"***REMOVED***0.text***REMOVED***\"\nused ***REMOVED***0.occurences***REMOVED*** time***REMOVED***2***REMOVED***\ncreated ***REMOVED***3***REMOVED***```\nUse `***REMOVED***4***REMOVED***cards edit ***REMOVED***0.id***REMOVED***` to edit this card`"
                return Response(
                    info.format(card,
                                self.get_global_user(card.creator_id).mention,
                                "s" if card.occurences != 1 else "",
                                prettydate(card.creation_date),
                                self.config.command_prefix))
        elif argument == "create":
            text = " ".join(
                leftover_args[1:]) if len(leftover_args) > 1 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...")
            if len(text) > 500:
                return Response("Maybe a bit too long?")

            if text.count("$") < 1:
                return Response(
                    "You need to have at least one blank ($) space",
                    delete_after=20)

            already_has_card, card = self.cah.cards.question_card_with_text(
                text)
            if already_has_card:
                return Response(
                    "There's already a question card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***qcards info ***REMOVED***0***REMOVED***` to find out more about this card".
                    format(card.id, self.config.command_prefix))

            card_id = self.cah.cards.add_question_card(text, author.id)
            return Response(
                "Successfully created question card *****REMOVED******REMOVED*****".format(card_id))
        elif argument == "edit":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            try:
                card_id_value = int(card_id)
            except:
                return Response("An id must be a number")

            if card_id is None:
                return Response(
                    "You need to provide the question card's id!",
                    delete_after=20)

            text = " ".join(
                leftover_args[2:]) if len(leftover_args) > 2 else None
            if text is None:
                return Response(
                    "You might want to actually add some text to your question card",
                    delete_after=20)
            if len(text) < 3:
                return Response(
                    "I think that's a bit too short...")
            if len(text) > 500:
                return Response("Maybe a bit too long?")

            if text.count("$") < 1:
                return Response(
                    "You need to have at least one blank ($) space",
                    delete_after=20)

            already_has_card, card = self.cah.cards.question_card_with_text(
                text)
            if already_has_card and card.id != card_id_value:
                return Response(
                    "There's already a question card with a fairly similar content. <***REMOVED***0***REMOVED***>\nUse `***REMOVED***1***REMOVED***qcards info ***REMOVED***0***REMOVED***` to find out more about this question card".
                    format(card.id, self.config.command_prefix))

            if self.cah.cards.edit_question_card(card_id, text):
                return Response(
                    "Edited question card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
            else:
                return Response(
                    "There's no question card with that id")
        elif argument == "delete":
            card_id = leftover_args[
                1].lower().strip() if len(leftover_args) > 1 else None

            if card_id is None:
                return Response(
                    "You must specify the question card id")

            if self.cah.cards.remove_question_card(card_id):
                return Response(
                    "Deleted question card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
            else:
                return Response(
                    "Could not remove question card <*****REMOVED******REMOVED*****>".format(card_id),
                    delete_after=15)
        else:
            return await self.cmd_help(channel, ["qcards"])

    async def qcard_viewer(self,
                           channel,
                           author,
                           cards,
                           display_additional=None):
        cmds = ("n", "p", "exit")
        site_interface = "**Question Cards | Page ***REMOVED***0***REMOVED*** of ***REMOVED***1***REMOVED*****\n```\n***REMOVED***2***REMOVED***\n```\nShit you can do:\n`n`: Switch to the next page\n`p`: Switch to the previous page\n`exit`: Exit the viewer"
        card_string = "<***REMOVED******REMOVED***> \"***REMOVED******REMOVED***\"***REMOVED******REMOVED***"

        items_per_page = 20
        timeout = 60
        current_page = 0

        total_pages, items_on_last_page = divmod(
            len(cards) - 1, items_per_page)

        def msg_check(msg):
            return msg.content.lower().strip().startswith(cmds)

        while True:
            start_index = current_page * items_per_page
            end_index = start_index + \
                (items_per_page - 1 if current_page <
                 total_pages else items_on_last_page)
            page_cards = cards[start_index:end_index]

            page_cards_texts = []
            for p_c in page_cards:
                page_cards_texts.append(
                    card_string.format(
                        p_c.id,
                        p_c.text.replace("$", "_____"), "" if
                        display_additional is None or display_additional(p_c)
                        is None else " | ***REMOVED******REMOVED***".format(display_additional(p_c))))

            interface_msg = await self.safe_send_message(
                channel,
                site_interface.format(current_page + 1, total_pages + 1,
                                      "\n".join(page_cards_texts)))
            user_msg = await self.wait_for_message(
                timeout, author=author, channel=channel, check=msg_check)

            if not user_msg:
                await self.safe_delete_message(interface_msg)
                break

            content = user_msg.content.lower().strip()

            if content.startswith("n"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page + 1) % (total_pages + 1)
            elif content.startswith("p"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                current_page = (current_page - 1) % (total_pages + 1)
            elif content.startswith("exit"):
                await self.safe_delete_message(interface_msg)
                await self.safe_delete_message(user_msg)
                break

        await self.safe_send_message(
            channel, "Closed the question card viewer!", expire_in=20)

    @block_user
    @command_info("1.9.5", 1478998740, ***REMOVED***
        "2.0.2": (1481387640, "Added Hangman game and generalised game hub command"),
        "3.5.2": (1497712233, "Updated documentaion for this command"),
        "4.6.3": (1503158773, "Added Connect Four")
    ***REMOVED***)
    async def cmd_game(self, message, channel, author, leftover_args, game=None):
        """
        ///|Usage
        `***REMOVED***command_prefix***REMOVED***game [name]`
        ///|Explanation
        Play a game
        ///|References
        Cards against humanity can be played with the `cah` command.
        Use `***REMOVED***command_prefix***REMOVED***help cah` to learn more
        """

        all_funcs = dir(self)
        all_games = list(filter(lambda x: re.search("^g_\w+", x), all_funcs))
        all_game_names = [x[2:] for x in all_games]
        game_list = [***REMOVED***
            "name": x[2:],
            "handler": getattr(self, x, None),
            "description": getattr(self, x, None).__doc__.strip(" \t\n\r")
        ***REMOVED*** for x in all_games]

        if message.mentions is not None and len(message.mentions) > 0:
            author = message.mentions[0]

        if game is None:
            shuffle(game_list)

            def check(m):
                return (m.content.lower() in ["y", "n", "exit"])

            for current_game in game_list:
                msg = await self.safe_send_message(
                    channel,
                    "How about this game:\n\n*****REMOVED******REMOVED*****\n***REMOVED******REMOVED***\n\nType `y`, `n` or `exit`".
                    format(current_game["name"], current_game["description"]))
                response = await self.wait_for_message(
                    100, author=author, channel=channel, check=check)

                if not response or response.content.startswith(
                        self.config.command_prefix) or response.content.lower(
                ).startswith("exit"):
                    await self.safe_delete_message(msg)
                    await self.safe_delete_message(response)
                    await self.safe_send_message(channel, "Nevermind then.")
                    return

                if response.content.lower() == "y":
                    await self.safe_delete_message(msg)
                    await self.safe_delete_message(response)
                    game = current_game["name"]
                    break

                await self.safe_delete_message(msg)
                await self.safe_delete_message(response)

            if game is None:
                await self.safe_send_message(
                    channel, "That was all of them.", expire_in=20)
                return

        # game = game.lower().replace(" ", "_")
        handler = getattr(self, "g_" + game, None)
        if handler is None:
            return Response("There's no game like that...")

        await handler(author, channel, leftover_args)

    async def g_2048(self, author, channel, additional_args):
        """
        Join the same numbers and get to the 2048 tile!
        """

        save_code = additional_args[0] if len(additional_args) > 0 else None
        size = additional_args[1] if len(additional_args) > 1 else 5

        game = Game2048(size, save_code)
        game_running = True
        turn_index = 1
        cache_location = "cache/pictures/g2048_img" + str(author.id)

        def check(reaction, user):
            if reaction.custom_emoji:
                # self.log (str (reaction.emoji) + " is a custom emoji")
                # print("Ignoring my own reaction")
                return False

            if (str(reaction.emoji) in ("⬇", "➡", "⬆", "⬅") or
                        str(reaction.emoji).startswith("📽") or
                        str(reaction.emoji).startswith("💾")
                    ) and reaction.count > 1 and user == author:
                return True

            # self.log (str (reaction.emoji) + " was the wrong type of
            # emoji")
            return False

        while game_running:
            direction = None
            turn_information = ""
            # self.log (str (game))

            await self.send_typing(channel)

            while direction is None:
                msg = await self.send_file(
                    channel,
                    game.getImage(cache_location) + ".png",
                    content="**2048**\n***REMOVED******REMOVED*** turn ***REMOVED******REMOVED***".format(
                        str(turn_index) +
                        ("th" if 4 <= turn_index % 100 <= 20 else ***REMOVED***
                            1: "st",
                            2: "nd",
                            3: "rd"
                        ***REMOVED***.get(turn_index % 10, "th")), turn_information))
                turn_information = ""
                await self.add_reaction(msg, "⬅")
                await self.add_reaction(msg, "⬆")
                await self.add_reaction(msg, "➡")
                await self.add_reaction(msg, "⬇")
                await self.add_reaction(msg, "📽")
                await self.add_reaction(msg, "💾")

                reaction, user = await self.wait_for_reaction(
                    check=check, message=msg)
                msg = reaction.message  # for some reason this has to be like this
                # self.log ("User accepted. There are " + str (len
                # (msg.reactions)) + " reactions. [" + ", ".join ([str
                # (r.count) for r in msg.reactions]) + "]")

                for reaction in msg.reactions:
                    if str(reaction.emoji) == "📽" and reaction.count > 1:
                        await self.send_file(
                            user,
                            game.getImage(cache_location) + ".gif",
                            content="**2048**\nYour replay:")
                        turn_information = "| *replay has been sent*"

                    if str(reaction.emoji) == "💾" and reaction.count > 1:
                        await self.safe_send_message(
                            user,
                            "The save code is: *****REMOVED***0***REMOVED*****\nUse `***REMOVED***1***REMOVED***game 2048 ***REMOVED***2***REMOVED***` to continue your current game".
                            format(
                                escape_dis(game.get_save()),
                                self.config.command_prefix, game.get_save()))
                        turn_information = "| *save code has been sent*"

                    if str(reaction.emoji) in ("⬇", "➡", "⬆",
                                               "⬅") and reaction.count > 1:
                        direction = ("⬇", "➡", "⬆",
                                     "⬅").index(str(reaction.emoji))

                    # self.log ("This did not match a direction: " + str
                    # (reaction.emoji))

                if direction is None:
                    await self.safe_delete_message(msg)
                    turn_information = "| You didn't specifiy the direction" if turn_information is not "" else turn_information

            # self.log ("Chose the direction " + str (direction))
            game.move(direction)
            turn_index += 1
            await self.safe_delete_message(msg)

            if game.won():
                await self.safe_send_message(
                    channel,
                    "**2048**\nCongratulations, you won after ***REMOVED******REMOVED*** turns".format(
                        str(turn_index)))
                game_running = False

            if game.lost():
                await self.safe_send_message(
                    channel, "**2048**\nYou lost after ***REMOVED******REMOVED*** turns".format(
                        str(turn_index)))
                game_running = False

        await self.send_file(
            channel,
            game.getImage(cache_location) + ".gif",
            content="**2048**\nYour replay:")
        await self.safe_delete_message(msg)

    async def g_Hangman(self, author, channel, additional_args):
        """
        Guess a word by guessing each and every letter
        """

        tries = additional_args[0] if len(additional_args) > 0 else 10

        word = additional_args[1] if len(additional_args) > 1 else re.sub(
            "[^a-zA-Z]", "", random_line(ConfigDefaults.hangman_wordlist))

        alphabet = list("abcdefghijklmnopqrstuvwxyz")
        print("Started a Hangman game with \"" + word + "\"")

        game = GameHangman(word, tries)
        running = True

        def check(m):
            return (m.content.lower() in alphabet or
                    m.content.lower() == word or m.content.lower() == "exit")

        while running:
            current_status = game.get_beautified_string()
            msg = await self.safe_send_message(
                channel,
                "**Hangman**\n***REMOVED******REMOVED*** tr***REMOVED******REMOVED*** left\n\n***REMOVED******REMOVED***\n\n`Send the letter you want to guess or type \"exit\" to exit.`".
                format(game.tries_left, "ies"
                       if game.tries_left != 1 else "y", current_status))
            response = await self.wait_for_message(
                300, author=author, channel=channel, check=check)

            if not response or response.content.lower().startswith(
                    self.config.command_prefix) or response.content.lower(
            ).startswith("exit"):
                await self.safe_delete_message(msg)
                await self.safe_send_message(
                    channel, "Aborting this Hangman game. Thanks for playing!")
                running = False

            if response.content.lower() == word:
                await self.safe_send_message(
                    channel,
                    "Congratulations, you got it!\nThe word is: ****REMOVED******REMOVED****".format(
                        word))
                return

            letter = response.content[0]
            game.guess(letter)

            if game.won:
                await self.safe_send_message(
                    channel,
                    "Congratulations, you got it!\nThe word is: ****REMOVED******REMOVED****".format(
                        word))
                running = False

            if game.lost:
                await self.safe_send_message(channel, "You lost!")
                running = False

            await self.safe_delete_message(msg)
            await self.safe_delete_message(response)

    async def g_ConnectFour(self, author, channel, additional_args):
        """
        I hope you already know how this one works...
        """

        to_delete = []

        to_delete.append(await self.safe_send_message(channel, "Whom would you like to play against? You can **@mention** someone to challange them or you can play against Giesela by sending \"ai\" or **@mention**ing her"))

        players = None

        while True:
            msg = await self.wait_for_message(timeout=None, author=author, channel=channel)
            to_delete.append(msg)

            if msg.mentions:
                challanged_user = msg.mentions[0]

                if challanged_user == self.user:
                    players = author
                    break

                if challanged_user.bot:
                    to_delete.append(await self.safe_send_message(channel, "You can't challange a bot"))

                await self.safe_send_message(challanged_user, "*****REMOVED******REMOVED***** challanded you to a game of **Connect 4**. Do you accept?".format(author.display_name))
                resp = await self.wait_for_message(timeout=60, author=challanged_user)

                if resp:
                    to_delete.append(resp)

                if resp and resp.content.lower().strip() in ("yes", "sure", "of course", "bring it", "y", "ye", "yeah", "yea", "yup", "k", "okay", "let's go"):
                    players = [author, challanged_user]
                    break
                else:
                    to_delete.append(await self.safe_send_message(channel, "*****REMOVED******REMOVED***** declined!".format(author.display_name)))

            elif msg.content.lower().strip() in ("ai", "computer", "giesela", "you"):
                players = author
                break

        for msg in to_delete:
            asyncio.ensure_future(self.safe_delete_message(msg))

        game_done = asyncio.Future()

        game = GameConnectFour.start(self, channel, game_done, players)

        await game_done
