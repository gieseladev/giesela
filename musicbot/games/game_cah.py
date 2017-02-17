import json
import random
import re
from datetime import datetime
from functools import partial

import asyncio
import configparser
from musicbot.config import ConfigDefaults

vowels = tuple("aeiou")
a_list =\
    ***REMOVED***
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
    ***REMOVED***


class QuestionCard:

    def __init__(self, card_id, text, occurences, creator_id, creation_date):
        self.id = card_id
        self.text = text
        self.occurences = occurences
        self.creator_id = creator_id
        self.creation_date = creation_date

    def bump_occurences(self):
        self.occurences += 1

    def __repr__(self):
        return "<***REMOVED***0.id***REMOVED***> \"***REMOVED***0.text***REMOVED***\" [***REMOVED***0.creator_id***REMOVED*** | ***REMOVED***0.creation_date***REMOVED*** | ***REMOVED***0.occurences***REMOVED***]".format(self)

    @property
    def number_of_blanks(self):
        return self.text.count("$")


class Card:

    def __init__(self, card_id, text, occurences, creator_id, creation_date):
        self.id = card_id
        self.text = text
        self.occurences = occurences
        self.creator_id = creator_id
        self.creation_date = creation_date

    @classmethod
    def blank_card(cls):
        return cls(0, "BLANK", 0, 0, datetime.now())

    def bump_occurences(self):
        self.occurences += 1

    def __repr__(self):
        return "<***REMOVED***0.id***REMOVED***> \"***REMOVED***0.text***REMOVED***\" [***REMOVED***0.creator_id***REMOVED*** | ***REMOVED***0.creation_date***REMOVED*** | ***REMOVED***0.occurences***REMOVED***]".format(self)


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
            config_parser.set(sec, "creation_datetime", json.dumps(***REMOVED***"year": card.creation_date.year, "month": card.creation_date.month,
                                                                    "day": card.creation_date.day, "hour": card.creation_date.hour, "minute": card.creation_date.minute, "second": card.creation_date.second***REMOVED***))

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
            config_parser.set(sec, "creation_datetime", json.dumps(***REMOVED***"year": card.creation_date.year, "month": card.creation_date.month,
                                                                    "day": card.creation_date.day, "hour": card.creation_date.hour, "minute": card.creation_date.minute, "second": card.creation_date.second***REMOVED***))

        with open(ConfigDefaults.cards_file, "w+", encoding="utf-8") as cards_file:
            config_parser.write(cards_file)

    def add_question_card(self, text, creator_id):
        if self.question_card_with_text(text)[0]:
            return False

        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        self.question_cards.append(
            QuestionCard(card_id, text, 0, creator_id, datetime.now()))
        self.save_question_cards()
        return card_id

    def add_card(self, text, creator_id):
        if self.card_with_text(text)[0]:
            return False

        card_id = self.get_unique_id()
        self.ids_used.append(card_id)
        self.cards.append(Card(card_id, text, 0, creator_id, datetime.now()))
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
        return [res[1] for res in search_list][:results]

    def search_card(self, query, results=5):
        items = re.sub("[^\w\s]", "", query.lower().strip()).split()
        search_list = []

        for c in self.cards:
            c_items = re.sub("[^\w\s]", "", c.text.lower().strip()).split()
            overlaps = [part for part in items if part in c_items]
            search_list.append((len(overlaps), c))

        search_list.sort(key=lambda res: res[0], reverse=True)
        return [res[1] for res in search_list if res[0] > 0][:results]

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
        self.running_games = ***REMOVED******REMOVED***
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

    def send_message_to_user(self, user_id, message, callback=None, delete_after=0):
        user = self.musicbot.get_global_user(user_id)

        if user is None:
            return None

        task = self.musicbot.loop.create_task(
            self.musicbot.safe_send_message(user, message, expire_in=delete_after))
        if callback is not None:
            return task.add_done_callback(callback)

    def wait_for_message(self, callback, timeout=None, check=None):
        # print("::::::::::::::::::" + str(check))
        # print(";;;;;;;;;;;;;;;;;;" + str(callback))
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
        # self.question_cards = manager.get_all_question_cards()
        self.current_round = None
        self.started = False
        self.round_index = 0
        self.number_of_cards = 7
        self.number_of_blanks = int(.05 * len(self.manager.cards.cards))

        self.cards = self.manager.cards.cards.copy()
        print(str(self.number_of_blanks) + " blanks out of " +
              str(len(self.cards)) + " total cards in this game!")
        self.cards.extend([Card.blank_card()
                           for _ in range(self.number_of_blanks)])
        self.question_cards = self.manager.cards.question_cards.copy()

        self.manager.send_message_to_user(
            operator_id, "*Created the game ***REMOVED******REMOVED****".format(token.upper()), delete_after=20)

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
        print("round finished-playing")
        self.next_round()

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
            user_id).mention + " has joined the game*", delete_after=15)
        self.players.append(Player(user_id))
        self.manager.send_message_to_user(
            user_id, "You've joined the game *****REMOVED******REMOVED*****".format(self.token.upper()))
        return True

    def remove_user(self, user_id):
        pl = self.get_player(user_id)
        if pl is None:
            return False

        if self.current_round is not None:
            self.current_round.player_left(pl)

        self.players.remove(pl)
        self.broadcast("*" + self.manager.musicbot.get_global_user(
            user_id).mention + " has left the game*", delete_after=15)

        self.manager.send_message_to_user(
            user_id, "You've left the game *****REMOVED******REMOVED*****".format(self.token.upper()))
        return True

    def pick_card(self):
        if len(self.cards) < 1:
            self.cards = self.manager.cards.cards.copy()
            self.cards.extend([Card.blank_card()
                               for _ in range(self.number_of_blanks)])

        i = random.randint(0, len(self.cards) - 1)
        card = self.cards.pop(i)

        return card

    def pick_question_card(self):
        i = random.randint(0, len(self.question_cards) - 1)
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
        pass


class Round:

    def __init__(self, game, round_index):
        self.game = game
        self.master = random.choice(game.players)
        self.question_card = game.pick_question_card()
        self.messages_to_delete = []
        self.round_index = round_index
        self.answers = ***REMOVED******REMOVED***
        self.players_to_answer = self.game.players.copy()
        self.players_to_answer.remove(self.master)

        self.assign_cards()
        self.master.bump_master()

        round_text_master = "**Round ***REMOVED***0***REMOVED*** || YOU ARE THE MASTER**\n\n=====================\n***REMOVED***1***REMOVED*** *<***REMOVED***2***REMOVED***>*\n=====================\n\n*Wait for the players to choose*"
        for pl in self.game.players:
            pl.bump_played()

            if pl == self.master:
                print(str(pl) + " is the master!")
                card_texts = self.get_card_texts(pl)
                self.game.manager.send_message_to_user(pl.player_id, round_text_master.format(
                    self.round_index, self.question_card.text, self.question_card.id), callback=(lambda x: self.messages_to_delete.append(x.result())))
            else:
                self.send_player_information(pl)

                print("about to wait for message from player " + pl.player_id)

                check = lambda msg, pl=pl: msg.author.id == pl.player_id
                self.game.manager.wait_for_message(
                    lambda fut, pl=pl: self.on_player_message(pl, fut.result()), check=check)

    def on_player_message(self, player, message):
        if player.player_id == self.master.player_id:
            print("ignoring master")
            return

        print(str(player.player_id) + " wrote: " + message.content)

        def wait_again():
            self.game.manager.wait_for_message(lambda fut, player=player: self.on_player_message(
                player, fut.result()), check=lambda msg, player=player: msg.author.id == player.player_id)

        content = message.content.strip().lower()
        args = content.split()

        if args[0] == "pick":
            try:
                num = int(args[1]) - 1
            except:
                self.game.manager.send_message_to_user(
                    player.player_id, "This is not a number!".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            if num < 0 or num >= len(player.cards):
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index between 1 and ***REMOVED******REMOVED***".format(len(player.cards)), delete_after=5)
                wait_again()
                return

            card_chosen = player.get_card(num)
            print("player used card " + str(card_chosen))

            if card_chosen.id == 0:
                blank_text = " ".join(args[1:]) if len(args) > 1 else None
                if blank_text is None or len(blank_text) < 3 or len(blank_text) > 140:
                    self.game.manager.send_message_to_user(
                        player.player_id, "This is not a valid text for a blank card!\n".format(len(player.cards)), delete_after=5)
                    wait_again()
                    return

                print("player used a blank card w/ " + blank_text)
                card_chose.text = blank_text

            self.game.manager.cards.bump_card_occurences(card_chosen.id)
            try:
                self.answers[player].append(card_chosen)
            except:
                self.answers[player] = [card_chosen, ]

            if self.number_of_answers_from_player(player) >= self.question_card.number_of_blanks:
                print(str(player) + " player answered all the questions")
                self.player_answered(player)
            else:
                print(str(player) + " ain't done yet")
                self.send_player_information(player)

            if len(self.players_to_answer) < 1:
                self.start_judging()

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
        return True

    def get_card_texts(self, player):
        card_texts = []
        for i in range(len(player.cards)):
            card_texts.append(
                "***REMOVED******REMOVED***. [***REMOVED******REMOVED***] *<***REMOVED******REMOVED***>*".format(i + 1, player.cards[i].text, player.cards[i].id))

        return card_texts

    def number_of_answers_from_player(self, player):
        ans = self.answers.get(player, [])
        return len(ans)

    def send_player_information(self, player):
        cards_given = self.number_of_answers_from_player(player)
        cards_to_assign = self.question_card.number_of_blanks - cards_given

        card_texts = self.get_card_texts(player)

        round_text_player = "**Round ***REMOVED***0***REMOVED*****\n\n=====================\n***REMOVED***1***REMOVED*** *<***REMOVED***5***REMOVED***>*\n=====================\n\n*Pick ***REMOVED***2***REMOVED*** card***REMOVED***3***REMOVED****\n\nYou can use the following commands:\n`pick index [text_for_blanks]`: Pick one of your cards\n\n**Your cards**\n***REMOVED***4***REMOVED***"

        self.game.manager.send_message_to_user(player.player_id, round_text_player.format(self.round_index, self.question_card.text, cards_to_assign,
                                                                                          "s" if cards_to_assign != 1 else "", "\n".join(card_texts), self.question_card.id), callback=(lambda x: self.messages_to_delete.append(x.result())))

    def assign_cards(self):
        for player in self.game.players:
            if len(player.cards) < self.game.number_of_cards:
                for i in range(self.game.number_of_cards - len(player.cards)):
                    player.cards.append(self.game.pick_card())

    def clean_up(self):
        for msg in self.messages_to_delete:
            self.game.manager.delete_message(msg)
            print("deleting msg " + str(msg))

        self.messages_to_delete = []

    def player_left(self, pl):
        if pl == self.master:
            self.game.broadcast(
                "The current master has left the game. Switching to the next round!", 15)
            self.clean_up()
            self.game.round_finished()

        if pl in self.players_to_answer:
            self.players_to_answer.remove(pl)

        self.answers.pop(pl, None)

    def master_picks(self, index):
        print("master chose " + str(index))
        self.clean_up()
        player_key = list(self.answers.keys())[index]
        player_key.bump_won(
            self.question_card.number_of_blanks, len(self.answers))
        answers = self.answers.get(player_key)

        self.game.broadcast("***REMOVED******REMOVED*** won the game with the card***REMOVED******REMOVED*** ***REMOVED******REMOVED***".format(self.game.manager.musicbot.get_global_user(player_key.player_id).mention, "s" if len(
            answers) != 1 else "", ", ".join(["[***REMOVED******REMOVED***] *<***REMOVED******REMOVED***>*".format(ans.text, ans.id) for ans in answers])), delete_after=15)
        self.game.round_finished()

    def start_judging(self):
        self.clean_up()
        print("starting to judge")

        player_judge_text = "**Time to be judged!**\n\n=====================\n***REMOVED***0***REMOVED*** *<***REMOVED***1***REMOVED***>*\n=====================\n\n**The answers are**\n***REMOVED***2***REMOVED***"
        master_judge_text = "**Time to judge \'em**\n\n=====================\n***REMOVED***0***REMOVED*** *<***REMOVED***1***REMOVED***>*\n=====================\n\n*Pick a winner*\n\nYou can use the following commands:\n`pick index`: Pick the winner\n\n**The answers are**\n***REMOVED***2***REMOVED***"

        answer_texts = []
        answer_text = "[***REMOVED***1.text***REMOVED***] *<***REMOVED***1.id***REMOVED***>*"

        i = 1
        for pl_key in self.answers:
            pl_answers = self.answers.get(pl_key, None)
            if pl_answers is None:
                continue

            answer_texts.append(
                "***REMOVED******REMOVED***. ".format(i) + ", ".join([answer_text.format(i, ans) for ans in pl_answers]))
            i += 1

        for pl in self.game.players:
            if pl == self.master:
                self.game.manager.send_message_to_user(pl.player_id, master_judge_text.format(
                    self.question_card.text, self.question_card.id, "\n".join(answer_texts)), callback=lambda x: self.messages_to_delete.append(x.result()))

                check = lambda msg, pl=pl: msg.author.id == pl.player_id and msg.content.lower(
                ).startswith("pick")
                self.game.manager.wait_for_message(
                    lambda fut, pl=pl: self.on_master_message(pl, fut.result()), check=check)
            else:
                self.game.manager.send_message_to_user(pl.player_id, player_judge_text.format(
                    self.question_card.text, self.question_card.id, "\n".join(answer_texts)), callback=lambda x: self.messages_to_delete.append(x.result()))

    def on_master_message(self, player, message):
        print(str(player.player_id) + " wrote (master): " + message.content)

        def wait_again():
            self.game.manager.wait_for_message(lambda fut, player=player: self.on_master_message(
                player, fut.result()), check=lambda msg, player=player: msg.author.id == player.player_id)

        content = message.content.strip().lower()
        args = content.split()

        if args[0] == "pick":
            card_index = args[1].lower().strip() if len(args) > 1 else None

            if card_index is None:
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index!", delete_after=5)
                wait_again()
                return

            try:
                card_index = int(card_index) - 1
            except:
                self.game.manager.send_message_to_user(
                    player.player_id, "Index needs to be a number!", delete_after=5)
                wait_again()
                return

            if card_index < 0 or card_index >= len(self.answers):
                self.game.manager.send_message_to_user(
                    player.player_id, "Please provide an index between 1 and ***REMOVED******REMOVED***".format(len(self.answers)), delete_after=5)
                wait_again()
                return

            self.master_picks(card_index - 1)
            return

        wait_again()


class Player:

    def __init__(self, player_id, score=0, rounds_played=0, rounds_won=0, rounds_master=0, cards=[]):
        self.player_id = player_id
        self.score = score
        self.rounds_played = rounds_played
        self.rounds_won = rounds_won
        self.rounds_master = rounds_master
        self.cards = cards

    def __repr__(self):
        return "<***REMOVED******REMOVED***> ***REMOVED******REMOVED*** points; ***REMOVED******REMOVED*** rounds; ***REMOVED******REMOVED*** won; ***REMOVED******REMOVED*** master".format(self.player_id, self.score, self.rounds_played, self.rounds_won, self.rounds_master)

    def bump_master(self):
        self.rounds_master += 1

    def bump_played(self):
        self.rounds_played += 1

    def bump_won(self, cards_needed, players_facing):
        self.rounds_won += 1
        self.score += cards_needed * players_facing

    def get_card(self, index):
        if index >= 0 and index < len(self.cards):
            return self.cards.pop(index)

        return None
