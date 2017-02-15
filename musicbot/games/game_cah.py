import json
import random
from datetime import datetime

import asyncio
import configparser
from musicbot.config import ConfigDefaults

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

    def __init__(self, card_id, text, occurences, creator_id, creation_date=datetime.now()):
        self.id = card_id
        self.text = text
        self.occurences = occurences
        self.creator_id = creator_id
        self.creation_date = creation_date

    def bump_occurences(self):
        self.occurences += 1

    def __repr__(self):
        return "<{0.id}> \"{0.text}\" [{0.cards_to_draw} | {0.creator_id} | {0.creation_date} | {0.occurences}]".format(self)

    @property
    def number_of_blanks(self):
        return self.text.count("$")


class Card:

    def __init__(self, card_id, text, occurences, creator_id, creation_date=datetime.now()):
        self.id = card_id
        self.text = text
        self.occurences = occurences
        self.creator_id = creator_id
        self.creation_date = creation_date

    def bump_occurences(self):
        self.occurences += 1

    def __repr__(self):
        return "<{0.id}> \"{0.text}\" [{0.creator_id} | {0.creation_date} | {0.occurences}]".format(self)


class Cards:

    def __init__(self):
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

            if creation_date_string is None:
                creation_date = datetime.now()
            else:
                m_date = json.loads(creation_date_string)
                creation_date = datetime(m_date["year"], m_date["month"], m_date["day"], m_date[
                                         "hour"], m_date["minute"], m_date["second"])

            self.question_cards.append(QuestionCard(
                card_id, text, occurances, creator_id, creation_date))

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
            creator_id = config_parser.get(
                section, "creator_id", fallback="0")
            creation_date_string = config_parser.get(
                section, "creation_datetime", fallback=None)

            if creation_date_string is None:
                creation_date = datetime.now()
            else:
                m_date = json.loads(creation_date_string)
                creation_date = datetime(m_date["year"], m_date["month"], m_date["day"], m_date[
                                         "hour"], m_date["minute"], m_date["second"])

            self.cards.append(Card(
                card_id, text, occurances, creator_id, creation_date))

    def save_cards(self):
        config_parser = configparser.ConfigParser(interpolation=None)

        for card in self.cards:
            sec = str(card.id)
            config_parser.add_section(sec)
            config_parser.set(sec, "text", card.text)
            config_parser.set(sec, "occurences", str(card.occurences))
            config_parser.set(sec, "creator_id", str(card.creator_id))
            config_parser.set(sec, "creation_datetime", json.dumps({"year": card.creation_date.year, "month": card.creation_date.month,
                                                                    "day": card.creation_date.day, "hour": card.creation_date.hour, "minute": card.creation_date.minute, "second": card.creation_date.second}))

        with open(ConfigDefaults.cards_file, "w+", encoding="utf-8") as cards_file:
            config_parser.write(cards_file)

    def add_question_card(self, text, creator_id):
        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        self.question_cards.append(
            QuestionCard(card_id, text, 0, creator_id))
        self.save_question_cards()
        return card_id

    def add_card(self, text, creator_id):
        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        self.cards.append(Card(card_id, text, 0, creator_id))
        self.save_cards()
        return card_id

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

    def bump_card_occurences(self, card_id):
        c = self.get_card_global(card_id)
        if c is None:
            return False

        c.bump_occurences()
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
        self.cards = Cards()

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
            for x in range(4):
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

    def send_message_to_user(self, user_id, message, callback=None):
        user = self.musicbot.get_global_user(user_id)

        if user is None:
            return None

        task = self.musicbot.loop.create_task(
            self.musicbot.safe_send_message(user, message))
        if callback is not None:
            return task.add_done_callback(callback)

    def wait_for_message(self, callback, timeout=None, check=None):
        task = self.musicbot.loop.create_task(
            self.musicbot.wait_for_message(timeout=timeout, check=check))
        task.add_done_callback(callback)


class Game:

    def __init__(self, manager, token, operator_id):
        self.token = token
        self.manager = manager
        self.players = []
        self.operator_id = operator_id
        self.players.append(Player(operator_id))
        # self.question_cards = manager.get_all_question_cards()
        self.current_round = None
        self.started = False
        self.round_index = 0
        self.number_of_cards = 7

        self.cards = self.manager.cards.cards.copy()
        self.question_cards = self.manager.cards.question_cards.copy()

    def stop_game(self):
        if self.current_round is not None:
            self.current_round.end_round()

        for pl in self.players:
            self.manager.send_message_to_user(
                pl.player_id, "The operator has stopped this game. Thanks for playing!")

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
        pass

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

        self.players.append(Player(user_id))
        self.manager.send_message_to_user(
            user_id, "You've joined the game **{}**".format(self.token.upper()))
        return True

    def remove_user(self, id):
        pl = self.get_player(id)
        if pl is None:
            return False

        self.players.remove(pl)
        return True

    def pick_card(self):
        i = random.randint(0, len(self.cards) - 1)
        card = self.cards.pop(i)

        if len(self.cards) < 1:
            self.cards = self.manager.cards.cards.copy()

        return card

    def pick_question_card(self):
        i = random.randint(0, len(self.question_cards) - 1)
        card = self.question_cards.pop(i)

        if len(self.question_cards) < 1:
            self.question_cards = self.manager.cards.question_cards.copy()

        return card

    def bump_round_index(self):
        self.round_index += 1


class Round:

    def __init__(self, game, round_index):
        self.game = game
        self.master = random.choice(game.players)
        self.question_card = game.pick_question_card()
        self.messages_to_delete = []
        self.round_index = round_index

        self.assign_cards()
        self.master.bump_master()

        players = self.game.players.copy()
        round_text_player = "**Round {0}**\n{1}\n*Pick {2} card{3}*\n\nYou can use the following commands:\n`{4}pick [index]`: Pick one of your cards\n\n**Your cards**\n{5}"
        round_text_master = "**Round {0} || YOU ARE THE MASTER**\n{1}\n*Wait for the players to choose a card*"
        for pl in players:
            pl.bump_played()

            card_texts = []
            for i in range(len(pl.cards)):
                card_texts.append("{}. [{}] *<{}>*".format(i + 1, pl.cards[i].text, pl.cards[i].id))
            text = round_text_player.format(self.round_index, self.question_card.text, self.question_card.number_of_blanks,
                                            "s" if self.question_card.number_of_blanks != 1 else "", self.game.manager.musicbot.config.command_prefix, "\n".join(card_texts))
            if pl == self.master:
                text = round_text_master.format(
                    self.round_index, self.question_card.text)

            self.game.manager.send_message_to_user(pl.player_id, text, callback=(
                lambda x: self.messages_to_delete.append(x.result())))
        players.remove(self.master)

    def player_message(self, player, message):
        pass

    def assign_cards(self):
        for player in self.game.players:
            if len(player.cards) < self.game.number_of_cards:
                for i in range(self.game.number_of_cards - len(player.cards)):
                    player.cards.append(self.game.pick_card())


class Player:

    def __init__(self, player_id, score=0, rounds_played=0, rounds_won=0, rounds_master=0, cards=[]):
        self.player_id = player_id
        self.score = score
        self.rounds_played = rounds_played
        self.rounds_won = rounds_won
        self.rounds_master = rounds_master
        self.cards = cards

    def bump_master(self):
        self.rounds_master += 1

    def bump_played(self):
        self.rounds_played += 1
