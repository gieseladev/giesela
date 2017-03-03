import asyncio
import configparser
import json
import random
import re
import threading
from datetime import datetime
from functools import partial

from musicbot.config import ConfigDefaults
from musicbot.utils import prettydate

from .logger import log

vowels = tuple("aeiou")
a_list =\
    {
        "a": tuple("bcdefghiklmnoprstuvwxz"),
        "b": vowels,
        "c": tuple("aeiouhk"),
        "d": vowels,
        "e": tuple("abdfghiklmnprstuvxz"),
        "f": vowels,
        "g": vowels,
        "h": vowels,
        "i": tuple("ouknmpbdfghlrstwz"),
        "k": tuple("aeioul"),
        "l": vowels,
        "m": vowels,
        "n": vowels,
        "o": tuple("bcdfghiklmnprstvwxz"),
        "p": tuple("aeiounlrs"),
        "r": vowels,
        "s": tuple("aeiourltwchn"),
        "t": tuple("aeiourw"),
        "u": tuple("bcdfghiklmnprstvwxz"),
        "v": vowels,
        "w": vowels,
        "x": vowels,
        "z": vowels
    }


class QuestionCard:

    def __init__(self, card_id, text, occurences, creator_id, creation_date, likes, dislikes):
        self.id = card_id
        self.text = text
        self.occurences = occurences
        self.creator_id = creator_id
        self.creation_date = creation_date
        self.likes = likes
        self.dislikes = dislikes

    def bump_occurences(self):
        self.occurences += 1

    def like_card(self):
        self.likes += 1

    def dislike_card(self):
        self.dislikes += 1

    def __repr__(self):
        return "<{0.id}> \"{0.text}\" [{0.creator_id} | {0.creation_date} | {0.occurences}]".format(self)

    @property
    def number_of_blanks(self):
        return self.text.count("$")

    @property
    def like_dislike_ratio(self):
        if self.total_interactions <= 0:
            return 1

        return self.likes / self.total_interactions

    @property
    def total_interactions(self):
        return self.likes + self.dislikes

    def beautified_text(self, answers=None):
        text = self.text
        if answers is not None:
            for a in answers:
                text = text.replace("$", "\"{}\"".format(a.text), 1)

        return text.replace("$", "_____")


class Card:

    def __init__(self, card_id, text, occurences, creator_id, creation_date, picked_up_count, likes, dislikes):
        self.id = card_id
        self.text = text
        self.occurences = occurences
        self.creator_id = creator_id
        self.creation_date = creation_date
        self.picked_up_count = picked_up_count
        self.likes = likes
        self.dislikes = dislikes

    @classmethod
    def blank_card(cls):
        return cls(0, "BLANK", 0, 0, datetime.now(), 1, 0, 0)

    def bump_occurences(self):
        self.occurences += 1

    def like_card(self):
        self.likes += 1

    def dislike_card(self):
        self.dislikes += 1

    def picked_card(self):
        self.picked_up_count += 1

    def __repr__(self):
        return "<{0.id}> \"{0.text}\" [{0.creator_id} | {0.creation_date} | {0.occurences} / {0.picked_up_count}]".format(self)

    @property
    def like_dislike_ratio(self):
        if self.total_interactions <= 0:
            return 0

        return self.likes / self.total_interactions

    @property
    def total_interactions(self):
        return self.likes + self.dislikes


class Cards:

    def __init__(self, cah):
        self.cah = cah
        self.question_cards = []
        self.cards = []
        self.ids_used = []

        self.update_question_cards()
        self.update_cards()

    def update_question_cards(self):
        self.question_cards = []
        config_parser = configparser.ConfigParser(interpolation=None)
        config_parser.read(ConfigDefaults.question_cards, encoding='utf-8')

        for section in config_parser.sections():
            card_id = int(section)
            if card_id not in self.ids_used:
                self.ids_used.append(card_id)
            text = config_parser.get(section, "text")
            occurances = int(config_parser.get(
                section, "occurences", fallback=0))
            creator_id = config_parser.get(
                section, "creator_id", fallback="0")
            creation_date_string = config_parser.get(
                section, "creation_datetime", fallback=None)
            likes = int(config_parser.get(
                section, "likes", fallback=0))
            dislikes = int(config_parser.get(
                section, "dislikes", fallback=0))

            if creation_date_string is None:
                creation_date = datetime.now()
            else:
                m_date = json.loads(creation_date_string)
                creation_date = datetime(m_date["year"], m_date["month"], m_date["day"], m_date[
                                         "hour"], m_date["minute"], m_date["second"])

            self.question_cards.append(QuestionCard(
                card_id, text, occurances, creator_id, creation_date, likes, dislikes))

    def save_question_cards(self):
        config_parser = configparser.ConfigParser(interpolation=None)

        for card in self.question_cards:
            sec = str(card.id)
            config_parser.add_section(sec)
            config_parser.set(sec, "text", card.text)
            config_parser.set(sec, "occurences", str(card.occurences))
            config_parser.set(sec, "creator_id", str(card.creator_id))
            config_parser.set(sec, "creation_datetime", json.dumps({"year": card.creation_date.year, "month": card.creation_date.month,
                                                                    "day": card.creation_date.day, "hour": card.creation_date.hour, "minute": card.creation_date.minute, "second": card.creation_date.second}))
            config_parser.set(sec, "likes", str(card.likes))
            config_parser.set(sec, "dislikes", str(card.dislikes))

        with open(ConfigDefaults.question_cards, "w+", encoding="utf-8") as question_file:
            config_parser.write(question_file)

    def update_cards(self):
        self.cards = []
        config_parser = configparser.ConfigParser(interpolation=None)
        config_parser.read(ConfigDefaults.cards_file, encoding='utf-8')

        for section in config_parser.sections():
            card_id = int(section)
            if card_id not in self.ids_used:
                self.ids_used.append(card_id)
            text = config_parser.get(section, "text")
            occurances = int(config_parser.get(
                section, "occurences", fallback=0))
            picked_up_count = int(config_parser.get(
                section, "picked_up_count", fallback=0))
            creator_id = config_parser.get(
                section, "creator_id", fallback="0")
            creation_date_string = config_parser.get(
                section, "creation_datetime", fallback=None)
            likes = int(config_parser.get(
                section, "likes", fallback=0))
            dislikes = int(config_parser.get(
                section, "dislikes", fallback=0))

            if creation_date_string is None:
                creation_date = datetime.now()
            else:
                m_date = json.loads(creation_date_string)
                creation_date = datetime(m_date["year"], m_date["month"], m_date["day"], m_date[
                                         "hour"], m_date["minute"], m_date["second"])

            self.cards.append(Card(
                card_id, text, occurances, creator_id, creation_date, picked_up_count, likes, dislikes))

    def save_cards(self):
        config_parser = configparser.ConfigParser(interpolation=None)

        for card in self.cards:
            sec = str(card.id)
            config_parser.add_section(sec)
            config_parser.set(sec, "text", card.text)
            config_parser.set(sec, "occurences", str(card.occurences))
            config_parser.set(sec, "picked_up_count",
                              str(card.picked_up_count))
            config_parser.set(sec, "creator_id", str(card.creator_id))
            config_parser.set(sec, "creation_datetime", json.dumps({"year": card.creation_date.year, "month": card.creation_date.month,
                                                                    "day": card.creation_date.day, "hour": card.creation_date.hour, "minute": card.creation_date.minute, "second": card.creation_date.second}))
            config_parser.set(sec, "likes", str(card.likes))
            config_parser.set(sec, "dislikes", str(card.dislikes))

        with open(ConfigDefaults.cards_file, "w+", encoding="utf-8") as cards_file:
            config_parser.write(cards_file)

    def add_question_card(self, text, creator_id):
        if self.question_card_with_text(text)[0]:
            return False

        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        new_card = QuestionCard(
            card_id, text, 0, creator_id, datetime.now(), 0, 0)

        for g in self.cah.running_games:
            g.add_card(new_card)

        self.question_cards.append(new_card)
        self.save_question_cards()
        return card_id

    def add_card(self, text, creator_id):
        if self.card_with_text(text)[0]:
            return False

        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        new_card = Card(card_id, text, 0, creator_id, datetime.now(), 0, 0, 0)

        for g in self.cah.running_games:
            g.add_card(new_card)

        self.cards.append(new_card)
        self.save_cards()
        return card_id

    def remove_question_card(self, card_id):
        c = self.get_question_card(card_id)
        if c is None:
            return False

        self.question_cards.remove(c)
        self.save_question_cards()
        return True

    def remove_card(self, card_id):
        c = self.get_card(card_id)
        if c is None:
            return False

        self.cards.remove(c)
        self.save_cards()
        return True

    def edit_card(self, card_id, new_text):
        c = self.get_card(card_id)
        if c is None:
            return False

        c.text = new_text
        self.save_cards()
        return True

    def edit_question_card(self, card_id, new_text):
        c = self.get_question_card(card_id)
        if c is None:
            return False

        c.text = new_text
        self.save_question_cards()
        return True

    def card_with_text(self, text):
        text = re.sub("[^\w\s]", "", text.lower().strip())
        for c in self.cards:
            if text == re.sub("[^\w\s]", "", c.text.lower().strip()):
                return True, c

        return False, None

    def question_card_with_text(self, text):
        text = re.sub("[^\w\s]", "", text.lower().strip())
        for c in self.question_cards:
            if text == re.sub("[^\w\s]", "", c.text.lower().strip()):
                return True, c

        return False, None

    def get_question_card(self, card_id):
        try:
            card_id = int(card_id)
        except:
            return None

        for card in self.question_cards:
            if card.id == card_id:
                return card

        return None

    def get_card(self, card_id):
        try:
            card_id = int(card_id)
        except:
            return None

        for card in self.cards:
            if card.id == card_id:
                return card

        return None

    def search_question_card(self, query, results=5):
        items = re.sub("[^\w\s]", "", query.lower().strip()).split()
        search_list = []

        for c in self.question_cards:
            c_items = re.sub("[^\w\s]", "", c.text.lower().strip()).split()
            overlaps = [part for part in items if part in c_items]
            search_list.append((len(overlaps), c))

        search_list.sort(key=lambda res: res[0], reverse=True)
        return [res[1] for res in search_list if res[0] > 0][:results]

    def search_card(self, query, results=5):
        items = re.sub("[^\w\s]", "", query.lower().strip()).split()
        search_list = []

        for c in self.cards:
            c_items = re.sub("[^\w\s]", "", c.text.lower().strip()).split()
            overlaps = len([part for part in items if part in c_items])
            search_list.append((overlaps, c))

        search_list.sort(key=lambda res: res[0], reverse=True)
        return [res[1] for res in search_list if res[0] > 0][:results]

    def bump_card_occurences(self, card_id):
        c = self.get_card_global(card_id)
        if c is None:
            return False

        c.bump_occurences()
        self.save_cards()
        self.save_question_cards()
        return True

    def bump_card_pick_count(self, card_id):
        c = self.get_card(card_id)
        if c is None:
            return False

        c.picked_card()
        self.save_cards()
        return True

    def bump_card_likes(self, card_id):
        c = self.get_card(card_id)
        if c is None:
            return False

        c.like_card()
        self.save_cards()
        return True

    def bump_card_dislikes(self, card_id):
        c = self.get_card(card_id)
        if c is None:
            return False

        c.dislike_card()
        self.save_cards()
        return True

    def get_card_global(self, card_id):
        c = self.get_card(card_id)
        if c is not None:
            return c

        qc = self.get_question_card(card_id)
        if qc is not None:
            return qc

        return None

    def get_unique_id(self):
        while True:
            i = random.randint(100, 100000)
            if i not in self.ids_used:
                return i


class GameCAH:

    def __init__(self, musicbot):
        self.musicbot = musicbot
        self.running_games = {}
        self.cards = Cards(self)

    def new_game(self, operator_id):
        if self.is_user_in_game(operator_id):
            return False

        token = self.generate_token()
        g = Game(self, token, operator_id)

        if token is None:
            return False

        self.running_games[token] = g
        return token

    def user_join_game(self, user_id, game_token):
        if self.is_user_in_game(user_id):
            return False

        game_token = game_token.lower().strip()

        if game_token not in self.running_games:
            return None
        g = self.running_games[game_token]

        return g.add_user(user_id)

    def player_leave_game(self, user_id, game_token):
        if not self.is_user_in_game(user_id):
            return False

        game_token = game_token.lower().strip()

        if game_token not in self.running_games:
            return None
        g = self.running_games[game_token]

        return g.remove_user(user_id)

    def stop_game(self, token):
        g = self.get_game(token)
        g.stop_game()
        self.running_games.pop(token, None)

    def get_game(self, token):
        if token is None:
            return None

        token = token.lower().strip()
        if token in self.running_games:
            return self.running_games[token]

        return None

    def generate_token(self):
        max_tries = 5000
        i = 0
        while i < max_tries:
            token = random.choice(list(a_list.keys()))
            w_string = ""
            for x in range(3):
                w_string += token
                token = random.choice(a_list[token])

            if w_string not in self.running_games.keys():
                return w_string
            i += 1

        return None

    def is_user_in_game(self, user_id):
        return self.get_game_from_user_id(user_id) != None

    def get_game_from_user_id(self, user_id):
        for game in self.running_games.values():
            if game.get_player(user_id) is not None:
                return game
        return None

    def send_message_to_user(self, user_id, message, callback=None, delete_after=0):
        user = self.musicbot.get_global_user(user_id)

        if user is None:
            return None

        task = self.musicbot.loop.create_task(
            self.musicbot.safe_send_message(user, message, expire_in=delete_after))
        if callback is not None:
            return task.add_done_callback(callback)

    def wait_for_message(self, callback, timeout=None, check=None):
        # log("::::::::::::::::::" + str(check))
        # log(";;;;;;;;;;;;;;;;;;" + str(callback))
        task = self.musicbot.loop.create_task(
            self.musicbot.wait_for_message(timeout=timeout, check=check))
        task.add_done_callback(callback)

    def delete_message(self, message):
        self.musicbot.loop.create_task(
            self.musicbot.safe_delete_message(message))


class Game:

    def __init__(self, manager, token, operator_id):
        self.token = token
        self.manager = manager
        self.players = []
        self.operator_id = operator_id
        self.players.append(Player(operator_id))
        self.masters = []
        self.current_round = None
        self.started = False
        self.round_index = 0
        self.number_of_cards = 7
        self.number_of_blanks = int(.05 * len(self.manager.cards.cards))
        self.throwing_card_cost = 5

        self.cards = self.manager.cards.cards.copy()
        log(str(self.number_of_blanks) + " blanks out of " +
            str(len(self.cards)) + " total cards in this game!")
        self.cards.extend([Card.blank_card()
                           for _ in range(self.number_of_blanks)])
        self.question_cards = self.manager.cards.question_cards.copy()

        self.manager.send_message_to_user(
            operator_id, "*Created the game {}*".format(token.upper()), delete_after=20)

    def stop_game(self):
        if self.current_round is not None:
            self.current_round.round_stopped = True

        self.broadcast(
            "This game has stopped. Thanks for playing!", delete_after=15)

        for player in self.players:
            self.send_player_stats(player)

        log("[CAH] <{}> Stopped!".format(self.token))

    def start_game(self):
        if self.started or not self.enough_players():
            return False
        else:
            self.bump_round_index()
            self.current_round = Round(self, self.round_index)
            self.started = True
            return True

    def next_round(self):
        self.bump_round_index()
        self.current_round = Round(self, self.round_index)

    def enough_players(self):
        return len(self.players) >= 2

    def round_finished(self):
        log("round finished-playing")
        threading.Timer(1.5, self.next_round).start()

    def get_player(self, id):
        for player in self.players:
            if player.player_id == id:
                return player

        return None

    def is_owner(self, user_id):
        return user_id == self.operator_id

    def in_game(self, user_id):
        return self.get_player(user_id) != None

    def add_user(self, user_id):
        if self.get_player(user_id) is not None:
            return False

        self.broadcast("*" + self.manager.musicbot.get_global_user(
            user_id).name + " has joined the game*", delete_after=15)
        self.players.append(Player(user_id))
        self.manager.send_message_to_user(
            user_id, "You've joined the game **{}**".format(self.token.upper()))
        return True

    def remove_user(self, user_id):
        pl = self.get_player(user_id)
        if pl is None:
            return False

        if pl.player_id == self.operator_id:
            if len(self.players) < 2:
                self.manager.stop_game(self.token)
                return True
            self.operator_id = random.choice(
                [pl.player_id for pl in self.players if pl.player_id != self.operator_id])
            self.manager.send_message_to_user(
                self.operator_id, "You're the new operator of the game **{}**".format(self.token.upper()))

        self.manager.send_message_to_user(
            user_id, "You've left the game **{}**".format(self.token.upper()))

        self.players.remove(pl)
        self.broadcast("*" + self.manager.musicbot.get_global_user(
            user_id).name + " has left the game*", delete_after=15)

        if not self.enough_players():
            self.broadcast(
                "Not enough players to continue...\n**Stopping** the game!", delete_after=15)
            self.manager.stop_game(self.token)
            if self.current_round is not None:
                self.current_round.round_stopped = True
            return True

        if self.current_round is not None:
            self.current_round.player_left(pl)

        self.send_player_stats(pl)

        return True

    def add_card(self, card):
        self.cards.append(card.copy())

    def add_question_card(self, card):
        self.question_cards.append(card.copy())

    def pick_card(self, card_ids=None):
        if len(self.cards) < 1:
            self.cards = self.manager.cards.cards.copy()
            self.cards.extend([Card.blank_card()
                               for _ in range(self.number_of_blanks)])

        while True:
            i = random.randint(0, len(self.cards) - 1)
            if (card_ids is None) or (self.cards[i].id not in card_ids):
                card = self.cards.pop(i)
                break

        self.manager.cards.bump_card_pick_count(card.id)

        return card

    def pick_question_card(self):
        i = random.randint(0, len(self.question_cards) - 1)

        if self.question_cards[i].number_of_blanks > self.number_of_cards:
            log("[CAH] Card ({}) can't be used as it has too many number of blanks ({})".format(
                self.question_cards[i], self.number_of_cards))
            return self.pick_question_card()

        card = self.question_cards.pop(i)
        self.manager.cards.bump_card_occurences(card.id)

        if len(self.question_cards) < 1:
            self.question_cards = self.manager.cards.question_cards.copy()

        return card

    def bump_round_index(self):
        self.round_index += 1

    def broadcast(self, message, delete_after=0):
        for player in self.players:
            self.manager.send_message_to_user(
                player.player_id, message, delete_after=delete_after)

    def pick_master(self):
        if len(self.masters) < 1:
            self.masters = [pl.player_id for pl in self.players]
        i = random.randint(0, len(self.masters) - 1)
        m_id = self.masters.pop(i)
        return self.get_player(m_id)

    def send_player_stats(self, player):
        stats_interface = "**Stats for Game <{}>**\n{}"
        player_stats_interface = "```\nPlayer: {}\n---------------\nRounds played: {}\nRounds master: {}\nRounds won: {}\nScore: {}\n```"

        player_stats = []

        player_stats.append(player_stats_interface.format(self.game.manager.musicbot.get_global_user(
            player.player_id), player.rounds_played, player.rounds_master, player.rounds_won, player.score))

        for pl in self.game.players:
            if pl.player_id == player.player_id:
                continue
            player_stats.append(player_stats_interface.format(self.game.manager.musicbot.get_global_user(
                pl.player_id), pl.rounds_played, pl.rounds_master, pl.rounds_won, pl.score))

        self.game.manager.send_message_to_user(player.player_id, stats_interface.format(
            self.game.token, "\n".join(player_stats)), delete_after=30)


class Round:

    def __init__(self, game, round_index):
        log("[CAH] <{}: {}> Starting!".format(
            game.token, round_index))
        self.game = game
        self.master = game.pick_master()
        self.game.broadcast("***{}** is the master this round*".format(
            self.game.manager.musicbot.get_global_user(self.master.player_id).name), delete_after=60)

        self.question_card = game.pick_question_card()
        self.messages_to_delete = []
        self.round_index = round_index
        self.answers = {}
        self.answers_by_index = []
        self.players_to_answer = self.game.players.copy()
        self.players_to_answer.remove(self.master)

        self.assign_cards()
        self.master.bump_master()
        self.round_stopped = False
        self.judging_phase = False

        round_text_master = "**Round {0} ###YOU ARE THE MASTER###**\n\n```\n{1}```*<{2}>*\n\n*Wait for the players to choose*\n\nYou can use the following commands:\n`info`: learn more about the question card\n`like`: upvote the question card\n`dislike`: downvote the question card\n`stats`: show some stats\n`leave`: leave the game"
        for pl in self.game.players:
            pl.bump_played()

            if pl.player_id == self.master.player_id:
                log("[CAH] <{}: {}> ({}) is the master".format(
                    self.game.token, self.round_index, pl))
                card_texts = self.get_card_texts(pl)
                self.game.manager.send_message_to_user(pl.player_id, round_text_master.format(
                    self.round_index, self.question_card.beautified_text(), self.question_card.id), callback=(lambda x: self.messages_to_delete.append(x.result())))

                check = lambda msg, pl=pl: msg.author.id == pl.player_id
                self.game.manager.wait_for_message(
                    lambda fut, pl=pl, round_index=self.round_index: self.on_master_message(pl, fut.result(), round_index), check=check)
            else:
                self.send_player_information(pl)

                log("[CAH] <{}: {}> Waiting for message from ({})!".format(
                    self.game.token, self.round_index, pl))

                check = lambda msg, pl=pl: msg.author.id == pl.player_id
                self.game.manager.wait_for_message(
                    lambda fut, pl=pl, round_index=self.round_index: self.on_player_message(pl, fut.result(), round_index), check=check)

    def on_player_message(self, player, message, round_index):
        if self.round_stopped:
            return

        if player.player_id == self.master.player_id:
            log("[CAH] <{}: {}> Received message from master!".format(
                self.game.token, self.round_index))
            return

        def wait_again():
            self.game.manager.wait_for_message(lambda fut, player=player, round_index=self.round_index: self.on_player_message(
                player, fut.result(), round_index), check=lambda msg, player=player: msg.author.id == player.player_id)

        if self.round_index != round_index:
            wait_again()
            return

        content = message.content.strip().lower()
        args = content.split()

        log("[CAH] <{}: {}> ({}) sent: \"{}\"".format(
            self.game.token, self.round_index, player, content))

        try:
            num = int(args[0]) - 1
            args.insert(0, "pick")
        except:
            num = None

        if args[0] == "pick" or num is not None:
            if num is None:
                try:
                    num = int(args[1]) - 1
                except:
                    self.game.manager.send_message_to_user(
                        player.player_id, "This is not a number!".format(len(player.cards)), delete_after=5)
                    wait_again()
                    return

            if num < 0 or num >= len(player.cards):
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index between 1 and {}".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            card_chosen = player.get_card(num)
            log("[CAH] <{}: {}> ({}) picked card ({})".format(
                self.game.token, self.round_index, player, card_chosen))

            if card_chosen.id == 0:
                blank_text = " ".join(args[2:]) if len(args) > 2 else None
                if blank_text is None or len(blank_text) < 3 or len(blank_text) > 140:
                    self.game.manager.send_message_to_user(
                        player.player_id, "This is not a valid text for a blank card!\n".format(len(player.cards)), delete_after=5)
                    wait_again()
                    return

                log("[CAH] <{}: {}> ({}) used a blank card with text: \"{}\"".format(
                    self.game.token, self.round_index, player, blank_text))
                card_chosen.text = blank_text

            self.game.manager.cards.bump_card_occurences(card_chosen.id)
            try:
                self.answers[player].append(card_chosen)
            except:
                self.answers[player] = [card_chosen, ]

            if self.number_of_answers_from_player(player) >= self.question_card.number_of_blanks:
                log("[CAH] <{}: {}> ({}) is done!".format(
                    self.game.token, self.round_index, player))
                self.player_answered(player)
                if len(self.players_to_answer) < 1:
                    self.start_judging()

                return
            else:
                self.send_player_information(player)
        elif args[0] == "info":
            try:
                num = int(args[1]) - 1
            except:
                self.game.manager.send_message_to_user(
                    player.player_id, "This is not a number!".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            if num < 0 or num >= len(player.cards):
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index between 1 and {}".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            card_chosen = player.get_card(num, True)

            log("[CAH] <{}: {}> ({}) requests information about card ({})".format(
                self.game.token, self.round_index, player, card_chosen))

            self.game.manager.send_message_to_user(
                player.player_id, "Card **{0.id}** by {1}\n```\n\"{0.text}\"\nused {0.occurences} time{2}\ndrawn {0.picked_up_count} time{5}\nlike ratio: {4}%\ncreated {3}```".format(card_chosen, self.game.manager.musicbot.get_global_user(card_chosen.creator_id).name, "s" if card_chosen.occurences != 1 else "", prettydate(card_chosen.creation_date), int(card_chosen.like_dislike_ratio * 100), "s" if card_chosen.picked_up_count != 1 else ""), delete_after=20)
            wait_again()
            return
        elif args[0] == "like":
            try:
                num = int(args[1]) - 1
            except:
                self.game.manager.send_message_to_user(
                    player.player_id, "This is not a number!".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            if num < 0 or num >= len(player.cards):
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index between 1 and {}".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            card_chosen = player.get_card(num, True)
            self.game.manager.cards.bump_card_likes(card_chosen.id)

            log("[CAH] <{}: {}> ({}) likes card ({})".format(
                self.game.token, self.round_index, player, card_chosen))

            self.game.manager.send_message_to_user(
                player.player_id, "Thanks for voting!", delete_after=5)
            wait_again()
            return
        elif args[0] == "dislike":
            try:
                num = int(args[1]) - 1
            except:
                self.game.manager.send_message_to_user(
                    player.player_id, "This is not a number!".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            if num < 0 or num >= len(player.cards):
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index between 1 and {}".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            card_chosen = player.get_card(num, True)
            self.game.manager.cards.bump_card_dislikes(card_chosen.id)

            log("[CAH] <{}: {}> ({}) dislikes card ({})".format(
                self.game.token, self.round_index, player, card_chosen))

            self.game.manager.send_message_to_user(
                player.player_id, "Thanks for voting!", delete_after=5)
            wait_again()
            return
        elif args[0] == "stats":
            self.game.send_player_stats(player)
            wait_again()
            return
        elif args[0] == "leave":
            self.game.remove_user(player.player_id)

        wait_again()

    def player_answered(self, player):
        to_delete = None

        for pl in self.players_to_answer:
            if pl.player_id == player.player_id:
                to_delete = pl
                break

        if to_delete is None:
            return False

        self.players_to_answer.remove(to_delete)
        self.send_player_information(player)
        return True

    def get_card_texts(self, player):
        card_texts = []
        for i in range(len(player.cards)):
            card_texts.append(
                "{}. [{}]".format(i + 1, player.cards[i].text))

        return card_texts

    def number_of_answers_from_player(self, player):
        ans = self.answers.get(player, [])
        return len(ans)

    def send_player_information(self, player):
        cards_given = self.number_of_answers_from_player(player)
        cards_to_assign = self.question_card.number_of_blanks - cards_given

        card_texts = self.get_card_texts(player)

        if cards_to_assign > 0:
            round_text_player = "**Round {0}**\n\nYou can use the following commands:\n`pick <index> [text_for_blanks]`: Pick one of your cards\n`info <index>`: Get some more info about one of your cards\n`like <index>`: Upvote a card\n`dislike <index>`: Downvote a card\n`stats`: Get some stats about the current game\n`leave`: leave the game\n\n```\n{1}```*<{5}>*\n\n*Pick {2} card{3}*\n\n**Your cards**\n{4}"

            self.game.manager.send_message_to_user(player.player_id, round_text_player.format(self.round_index, self.question_card.beautified_text(self.answers.get(player, None)), cards_to_assign,
                                                                                              "s" if cards_to_assign != 1 else "", "\n".join(card_texts), self.question_card.id), callback=(lambda x: self.messages_to_delete.append(x.result())))
        else:
            finished_round_text_player = "**Round {0}**\n\n```\n{1}```*<{2}>*\n\n*Wait for the others to answer!*\n\n**Your cards**\n{3}"
            self.game.manager.send_message_to_user(player.player_id, round_text_player.format(self.round_index, self.question_card.beautified_text(
                self.answers.get(player, None)), self.question_card.id, "\n".join(card_texts)), callback=(lambda x: self.messages_to_delete.append(x.result())))

    def assign_cards(self):
        for player in self.game.players:
            if len(player.cards) < self.game.number_of_cards:
                for i in range(self.game.number_of_cards - len(player.cards)):
                    player.cards.append(self.game.pick_card(
                        [x.id for x in player.cards]))

    def clean_up(self):
        for msg in self.messages_to_delete:
            self.game.manager.delete_message(msg)

            log("[CAH] <{}: {}> Deleting message \"{}\"".format(
                self.game.token, self.round_index, msg.content[:20]))

        self.messages_to_delete = []

    def player_left(self, pl):
        if pl == self.master:
            self.round_stopped = True
            self.game.broadcast(
                "The current master has left the game. Switching to the next round!", 15)
            self.clean_up()
            self.game.round_finished()

        if pl in self.players_to_answer:
            self.players_to_answer.remove(pl)

        self.answers.pop(pl, None)

    def master_picks(self, index):
        self.round_stopped = True
        self.clean_up()
        player_key, answers = self.answers_by_index[index]
        player_key.bump_won(
            self.question_card.number_of_blanks, len(self.answers.keys()))
        log("[CAH] <{}: {}> Master ({}) has picked ({})\'s answer ({})".format(
            self.game.token, self.round_index, self.master, player_key, answers))

        self.game.broadcast("**{}** won the game with the card{} {}".format(self.game.manager.musicbot.get_global_user(player_key.player_id).name, "s" if len(
            answers) != 1 else "", ", ".join(["[{}] *<{}>*".format(ans.text, ans.id) for ans in answers])), delete_after=15)
        self.game.round_finished()

    def start_judging(self):
        self.clean_up()
        log("[CAH] <{}: {}> Starting the judgement".format(
            self.game.token, self.round_index))

        player_judge_text = "**Time to be judged by *{3}*!**\n\n```\n{0}```*<{1}>*\n\n**The answers are**\n{2}"
        master_judge_text = "**Time to judge \'em**\n\n```\n{0}```*<{1}>*\n\n*Pick a winner*\n\nYou can use the following command:\n`pick index`: Pick the winner\n\n**The answers are**\n{2}"

        answer_texts = []
        answer_text = "[{}] *<{}>*"

        i = 1
        self.answers_by_index = []
        ans_keys = list(self.answers.keys())
        random.shuffle(ans_keys)

        for pl_key in ans_keys:
            pl_answers = self.answers.get(pl_key, None)
            if pl_answers is None:
                continue
            self.answers_by_index.insert(i - 1, (pl_key, pl_answers,))

            answer_texts.append(
                "{}. ".format(i) + ", ".join([answer_text.format(ans.text, ans.id) for ans in pl_answers]))
            i += 1

        self.judging_phase = True

        for pl in self.game.players:
            if pl == self.master:
                self.game.manager.send_message_to_user(pl.player_id, master_judge_text.format(
                    self.question_card.beautified_text(), self.question_card.id, "\n".join(answer_texts)), callback=lambda x: self.messages_to_delete.append(x.result()))

                check = lambda msg, pl=pl: msg.author.id == pl.player_id
                self.game.manager.wait_for_message(
                    lambda fut, pl=pl, round_index=self.round_index: self.on_master_message(pl, fut.result(), round_index), check=check)
            else:
                self.game.manager.send_message_to_user(pl.player_id, player_judge_text.format(
                    self.question_card.beautified_text(), self.question_card.id, "\n".join(answer_texts), self.game.manager.musicbot.get_global_user(self.master.player_id).name), callback=lambda x: self.messages_to_delete.append(x.result()))

    def on_master_message(self, player, message, round_index):
        if self.round_stopped:
            return

        def wait_again():
            self.game.manager.wait_for_message(lambda fut, player=player, round_index=self.round_index: self.on_master_message(
                player, fut.result(), round_index), check=lambda msg, player=player: msg.author.id == player.player_id)

        if self.round_index != round_index:
            wait_again()
            return

        content = message.content.strip().lower()
        args = content.split()

        log("[CAH] <{}: {}> Master ({}) sent message: \"{}\"".format(
            self.game.token, self.round_index, self.master, message.content))

        try:
            card_index = int(args[0]) - 1
        except:
            card_index = None

        if self.judging_phase and (args[0] == "pick" or card_index is not None):
            if card_index is None:
                try:
                    card_index = int(args[1]) - 1
                except:
                    self.game.manager.send_message_to_user(
                        player.player_id, "This is not a number!".format(len(player.cards)), delete_after=5)
                    wait_again()
                    return

            if card_index < 0 or card_index >= len(self.answers):
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index between 1 and {}".format(len(self.answers)), delete_after=5)
                wait_again()
                return

            self.master_picks(card_index)
            return
        elif args[0] == "like":
            qc = self.game.manager.cards.get_question_card(
                self.question_card.id)
            if qc is None:
                self.game.manager.send_message_to_user(
                    player.player_id, "Something went wrong", delete_after=5)
                wait_again()
                return

            qc.like_card()
            self.game.manager.send_message_to_user(
                player.player_id, "Thanks for voting!", delete_after=10)
            wait_again()
            return
        elif args[0] == "dislike":
            qc = self.game.manager.cards.get_question_card(
                self.question_card.id)
            if qc is None:
                self.game.manager.send_message_to_user(
                    player.player_id, "Something went wrong", delete_after=5)
                wait_again()
                return

            qc.dislike_card()
            self.game.manager.send_message_to_user(
                player.player_id, "Thanks for voting!", delete_after=10)
            wait_again()
            return
        elif args[0] == "info":
            log("[CAH] <{}: {}> ({}) requests information about question card".format(
                self.game.token, self.round_index, player, card_chosen))

            self.game.manager.send_message_to_user(
                player.player_id, "Card **{0.id}** by {1}\n```\n\"{0.text}\"\nused {0.occurences} time{2}\ndrawn {0.picked_up_count} time{5}\nlike ratio: {4}%\ncreated {3}```".format(self.question_card, self.game.manager.musicbot.get_global_user(self.question_card.creator_id).name, "s" if self.question_card.occurences != 1 else "", prettydate(self.question_card.creation_date), int(self.question_card.like_dislike_ratio * 100), "s" if self.question_card.picked_up_count != 1 else ""), delete_after=20)
            wait_again()
            return
        elif args[0] == "stats":
            self.game.send_player_stats(player)
            wait_again()
            return
        elif args[0] == "leave":
            self.game.remove_user(player.player_id)

        wait_again()


class Player:

    def __init__(self, player_id, score=0, rounds_played=0, rounds_won=0, rounds_master=0, cards=None):
        if cards == None:
            cards = []

        self.player_id = player_id
        self.score = score
        self.rounds_played = rounds_played
        self.rounds_won = rounds_won
        self.rounds_master = rounds_master
        self.cards = cards

    def __repr__(self):
        return "<{}> {} points; {} rounds; {} won; {} master".format(self.player_id, self.score, self.rounds_played, self.rounds_won, self.rounds_master)

    def bump_master(self):
        self.rounds_master += 1

    def bump_played(self):
        self.rounds_played += 1

    def bump_won(self, cards_needed, players_facing):
        self.rounds_won += 1
        self.score += cards_needed * players_facing

    def get_card(self, index, no_pop=False):
        if index >= 0 and index < len(self.cards):
            return self.cards.pop(index) if not no_pop else self.cards[index]

        return None
