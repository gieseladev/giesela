import random

import configparser
from musicbot.config import ConfigDefaults

vowels = tuple("aeiou")
a_list =\
    {
        "a": tuple("bcdefghiklmnoprstuvwxz"),
        "b": tuple("aeiou"),
        "c": tuple("aeiouhk"),
        "d": tuple("aeiou"),
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

    def __init__(self, card_id, text, cards_to_draw, occurences):
        self.id = card_id
        self.text = text
        self.cards_to_draw = cards_to_draw
        self.occurences = occurences

    def __repr__(self):
        return "<{0.id}> \"{0.text}\" [{0.cards_to_draw} | {0.occurences}]".format(self)


class Card:

    def __init__(self, card_id, text, occurences):
        self.id = card_id
        self.text = text
        self.occurences = occurences

    def __repr__(self):
        return "<{0.id}> \"{0.text}\" [{0.occurences}]".format(self)


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
            cards_to_draw = int(config_parser.get(
                section, "number_of_cards", fallback=1))
            occurances = int(config_parser.get(
                section, "occurences", fallback=0))

            self.question_cards.append(QuestionCard(
                card_id, text, cards_to_draw, occurances))

    def save_question_cards(self):
        config_parser = configparser.ConfigParser(interpolation=None)

        for card in self.question_cards:
            sec = str(card.id)
            config_parser.add_section(sec)
            config_parser.set(sec, "text", card.text)
            config_parser.set(sec, "number_of_cards", str(card.cards_to_draw))
            config_parser.set(sec, "occurences", str(card.occurances))

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

            self.cards.append(Card(
                card_id, text, occurances))

    def save_cards(self):
        config_parser = configparser.ConfigParser(interpolation=None)

        for card in self.cards:
            sec = str(card.id)
            config_parser.add_section(sec)
            config_parser.set(sec, "text", card.text)
            config_parser.set(sec, "occurences", str(card.occurances))

        with open(ConfigDefaults.cards_file, "w+", encoding="utf-8") as cards_file:
            config_parser.write(cards_file)

    def add_question_card(self, text, cards_to_draw):
        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        self.question_cards.append(
            QuestionCard(card_id, text, cards_to_draw, 0))
        self.save_question_cards()

    def add_card(self, text):
        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        self.cards.append(Card(card_id, text, 0))
        self.save_cards()

    def get_unique_id(self):
        while True:
            i = random.randint(100, 1000000000)
            if i not in self.ids_used:
                return i


class GameCAH:

    def __init__(self, musicbot):
        self.musicbot = musicbot
        self.running_games = {}
        self.cards = Cards()

    def new_game(self, operator_id):
        token = self.generate_token()
        g = Game(self, token, operator_id)

        if token is None:
            return False

        self.running_games[token] = g
        return token

    def user_join_game(self, user_id, game_token):
        game_token = game_token.lower().strip()

        if game_token not in self.running_games:
            return None
        g = self.running_games[game_token]

        return g.add_user(user_id)

    def generate_token(self):
        max_tries = 5000
        i = 0
        while i < max_tries:
            token = random.choice(list(a_list.keys()))
            w_string = ""
            for x in range(6):
                w_string += token
                token = random.choice(a_list[token])

            if w_string not in self.running_games.keys():
                return w_string
            i += 1

        return None

    def get_game_from_user_id(self, user_id):
        for game in self.running_games:
            if user_id in game.players:
                return game
        return None


class Game:

    def __init__(self, manager, token, operator_id):
        self.token = token
        self.manager = manager
        self.players = []
        self.operator_id = operator_id
        self.players.append(Player(operator_id))
        # self.question_cards = manager.get_all_question_cards()
        self.current_round = None

    def start_game(self):
        self.current_round = Round(self)

    def get_player(self, id):
        for player in self.players:
            if player.player_id == id:
                return player

        return None

    def add_user(self, id):
        if g.get_player(user_id) is not None:
            return False

        self.players.append(Player(id))
        return True

    def remove_user(self, id):
        pl = self.get_player(id)
        if pl is None:
            return False

        self.players.remove(pl)
        return True


class Round:

    def __init__(self, game):
        self.game = game
        self.master = random.choice(game.players)
        self.card = game.question_cards.pop(
            random.randint(0, len(game.question_cards) - 1))

    def start_round(self):
        pass


class Player:

    def __init__(self, player_id, score=0, rounds_played=0, rounds_won=0, cards=[]):
        self.player_id = player_id
        self.score = score
        self.rounds_played = rounds_played
        self.rounds_won = rounds_won
        self.cards = cards
