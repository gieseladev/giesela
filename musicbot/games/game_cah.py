import random

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


class GameCAH:

    def __init__(self, musicbot):
        self.musicbot = musicbot
        self.running_games = {}

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

    def get_all_question_cards(self):
        return []


class Game:

    def __init__(self, manager, token, operator_id):
        self.token = token
        self.manager = manager
        self.players = []
        self.operator_id = operator_id
        self.players.append(Player(operator_id))
        self.question_cards = manager.get_all_question_cards()

    def start_game(self):
        pass

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
