import copy
import random

from discord import User

import asyncio


class ConnectFourException(Exception):
    pass


class WrongPlayerCount(ConnectFourException):
    pass


class WrongUserType(ConnectFourException):
    pass


class ConnectFourPlayer:

    def __init__(self, colour):
        self.colour = colour

    @property
    def name(self):
        raise NotImplementedError

    async def play(self, game):
        raise NotImplementedError


class HumanPlayer(ConnectFourPlayer):

    def __init__(self, colour, user):
        super().__init__(colour)
        self.user = user

    @property
    def name(self):
        return self.user.display_name

    async def play(self, game):
        while True:
            msg = await game.bot.wait_for_message(timeout=None, author=self.user, channel=game.channel)
            content = msg.content.lower().strip()

            if content in ("abort", "exit"):
                game.log("***REMOVED******REMOVED*** stopped the game".format(self.name))
                game.abort()
                break

            if content.isnumeric():
                column = int(content) - 1

                if 0 <= column < len(game.grid):
                    success = game.can_place(column)

                    if success:
                        success = game.place_stone(self, column)

                    if not success:
                        await game.bot.safe_send_message(game.channel, "Can't place your stone there", expire_in=5)
                    else:
                        break
                else:
                    await game.bot.safe_send_message(game.channel, "Your number should be between 1 and ***REMOVED******REMOVED***".format(len(game.grid)), expire_in=5)
            else:
                await game.bot.safe_send_message(game.channel, "Please send a number", expire_in=5)


class AIPlayer(ConnectFourPlayer):

    def __init__(self, colour, level):
        super().__init__(colour)
        self.level = level

        self.opponent = None

    @property
    def name(self):
        return "Giesela (lvl ***REMOVED******REMOVED***)".format(self.level)

    def count_stones(self, grid):
        stone_amount = 0

        for column in grid:
            for stone in column:
                if not stone.is_empty:
                    stone_amount += 1

        return stone_amount

    def search_for_n(self, grid, amount=4, opponent=False):
        def check_horizontal(grid, amount, me, opponent):
            for i in range(len(grid[0])):
                current_player = None
                current_amount = 0

                for column in grid:
                    stone = column[i]

                    if not stone.is_empty:
                        if not current_player:
                            current_player = stone.player
                            current_amount = 1
                        elif stone.player == current_player:
                            current_amount += 1

                            if (not (isinstance(current_player, AIPlayer) and opponent)) and current_amount >= amount:
                                print("horizontal", amount, opponent, "TRUE")
                                self._debug_log_grid(grid)
                                return current_player
                        else:
                            current_amount = 0
                            current_player = None

            # print("horizontal", amount, opponent, "FALSE")
            return None

        def check_vertical(grid, amount, me, opponent):
            for column in grid:
                current_player = None
                current_amount = 0

                for stone in column:
                    if not stone.is_empty:
                        if not current_player:
                            current_player = stone.player
                            current_amount = 1
                        elif stone.player == current_player:
                            current_amount += 1

                            if (not (isinstance(current_player, AIPlayer) and opponent)) and current_amount >= amount:
                                print("vertical", amount, opponent, "TRUE")
                                self._debug_log_grid(grid)
                                return current_player
                        else:
                            current_amount = 0
                            current_player = None

            # print("vertical", amount, opponent, "FALSE")
            return None

        def check_diagonal(grid, amount, me, opponent):
            for i in range(len(grid) - amount):
                for j in range(len(grid[0]) - amount):
                    first_stone = grid[i][j]
                    if first_stone.is_empty:
                        continue

                    current_player = first_stone.player
                    if isinstance(current_player, AIPlayer) and opponent:
                        continue

                    for k in range(1, amount - 1):
                        if grid[i + k][j + k].player != current_player:
                            break
                    else:
                        print("diagonal", amount, opponent, "TRUE")
                        self._debug_log_grid(grid)
                        return current_player

            # print("diagonal", amount, opponent, "FALSE")

        return check_horizontal(grid, amount, self, opponent) or check_vertical(grid, amount, self, opponent) or check_diagonal(grid, amount, self, opponent)

    def what_if_move(self, grid, move, opponent=False):
        grid_copy = copy.deepcopy(grid)

        if opponent:
            # print("playing for opponent", str(self.opponent))
            player = self.opponent
        else:
            player = self

        for i, stone in enumerate(grid_copy[move]):
            if not stone.is_empty:
                i -= 1
                break

        grid_copy[move][i].possess(player)

        return grid_copy

    def _debug_log_grid(self, grid):
        lines = []

        for i in range(len(grid[0])):
            line = []

            for column in grid:
                stone = column[i]
                line.append(str(stone))

            lines.append(line)

        print("-----------------\n" + "\n".join("".join(val) for val in lines) + "\n--------------------------")

    def evaluate(self, grid):
        # self._debug_log_grid(grid)
        if self.search_for_n(grid, 4, True):
            # print("this caused a game over:")
            # self._debug_log_grid(grid)
            return -99999999999
        else:
            return int(bool(self.search_for_n(grid, 4))) * 100000 + int(bool(self.search_for_n(grid, 3))) * 100 + int(bool(self.search_for_n(grid, 2)))

    def check_gameover(self, grid):
        if self.search_for_n(grid, 4) or self.search_for_n(grid, 4, True):
            return True

        for column in grid:
            if column[0].is_empty:
                return False

        return True

    def possible_moves(self, grid):
        return [index for index, column in enumerate(grid) if column[0].is_empty]

    def minimax(self, grid):
        return max(map(lambda move: (move, self.min_play(self.what_if_move(grid, move))), self.possible_moves(grid)), key=lambda x: x[1])

    def min_play(self, grid, iteration=0):
        # print(iteration)
        if self.check_gameover(grid) or iteration >= self.level:
            return self.evaluate(grid)

        return min(map(lambda move: self.max_play(self.what_if_move(grid, move), iteration + 1), self.possible_moves(grid)))

    def max_play(self, grid, iteration):
        if self.check_gameover(grid) or iteration >= self.level:
            return self.evaluate(grid)

        return max(map(lambda move: self.min_play(self.what_if_move(grid, move, True), iteration + 1), self.possible_moves(grid)))

    async def play(self, game):
        # self.opponent = game.other_player
        # column, state = self.minimax(game.grid)
        # print(state)

        column = random.randrange(len(game.grid))

        game.log("bot placing at ***REMOVED******REMOVED***".format(column))
        game.place_stone(self, column)


class GameStone:

    def __init__(self, player):
        self.player = player

    @classmethod
    def empty(cls):
        return cls(None)

    @property
    def is_empty(self):
        return not bool(self.player)

    def draw(self):
        if self.is_empty:
            return ":white_circle:"
        else:
            return self.player.colour

    def belongs_to(self, player):
        return self.player == player

    def possess(self, player):
        self.player = player

    def __repr__(self):
        if self.player:
            if self.player.colour == ":large_blue_circle:":
                return "X"
            else:
                return "M"
        else:
            return "O"


class GameConnectFour:

    def __init__(self, bot, channel, future, players, size=None):
        self.win_amount = 4

        self.bot = bot
        self.channel = channel
        self.future = future

        self.loop = self.bot.loop

        self.players = players
        self.size = size or (7, 8)

        self.grid = self.create_grid(*self.size)

        self.current_player = random.choice(self.players)
        self.current_turn = 0

        self.round_interface_message = None

        self.log("setup complete, starting game")
        self.next_turn()

    @property
    def other_player(self):
        next_player_index = (self.players.index(self.current_player) + 1) % len(self.players)
        return self.players[next_player_index]

    @classmethod
    def start(cls, bot, channel, future, users, ai_level=3, size=None):
        colours = [":red_circle:", ":large_blue_circle:"]
        random.shuffle(colours)

        if isinstance(users, User):
            players = [HumanPlayer(colours.pop(), users), AIPlayer(colours.pop(), ai_level)]
        elif isinstance(users, (list, tuple)):
            if len(users) == 2:
                players = [HumanPlayer(colours.pop(), user) for user in users]
            elif len(users) == 1:
                players = [HumanPlayer(colours.pop(), users[0]), AIPlayer(colours.pop(), ai_level)]
            else:
                raise WrongPlayerCount("Can only play Connect Four with 1 or 2 players, not " + str(len(users)))
        else:
            raise WrongUserType("No ide what to do with \"***REMOVED******REMOVED***\"...".format(type(users)))

        return cls(bot, channel, future, players, size=size)

    @staticmethod
    def create_grid(width, height):
        grid = []

        for _ in range(width):
            column = []
            for _ in range(height):
                column.append(GameStone.empty())

            grid.append(column)

        return grid

    def log(self, *msgs):
        print("[Connect Four]", *msgs)

    def abort(self):
        self.log("aborted")
        asyncio.ensure_future(self.display_end("***REMOVED******REMOVED*** ABORTED".format(self.current_player.name)), loop=self.loop)
        self.future.set_result(None)

    def draw_grid(self):
        lines = []

        for i in range(self.size[1]):
            line = []

            for column in self.grid:
                stone = column[i]
                line.append(stone.draw())

            lines.append(line)

        return lines

    def check_win(self):
        def check_horizontal(game):
            for i in range(game.size[1]):
                current_player = None
                current_amount = 0

                for column in game.grid:
                    stone = column[i]

                    if not stone.is_empty:
                        if not current_player:
                            current_player = stone.player
                            current_amount = 1
                        elif stone.player == current_player:
                            current_amount += 1

                            if current_amount >= game.win_amount:
                                game.log("***REMOVED******REMOVED*** wins horizontally".format(current_player.name))
                                return current_player
                        else:
                            current_amount = 0
                            current_player = None

            return None

        def check_vertical(game):
            for column in game.grid:
                current_player = None
                current_amount = 0

                for stone in column:
                    if not stone.is_empty:
                        if not current_player:
                            current_player = stone.player
                            current_amount = 1
                        elif stone.player == current_player:
                            current_amount += 1

                            if current_amount >= game.win_amount:
                                game.log("***REMOVED******REMOVED*** wins vertically".format(current_player.name))
                                return current_player
                        else:
                            current_amount = 0
                            current_player = None

            return None

        def check_diagonal(game):
            for i in range(len(game.grid) - game.win_amount):
                for j in range(game.size[1] - game.win_amount):
                    first_stone = game.grid[i][j]
                    if first_stone.is_empty:
                        continue

                    current_player = first_stone.player

                    for k in range(1, game.win_amount - 1):
                        if game.grid[i + k][j + k].player != current_player:
                            break
                    else:
                        game.log("***REMOVED******REMOVED*** wins diagonally".format(current_player.name))
                        return current_player

        return check_horizontal(self) or check_vertical(self) or check_diagonal(self)

    def check_end(self):
        for column in self.grid:
            if column[0].is_empty:
                return False

        return True

    def next_turn(self):
        winner = self.check_win()

        if winner:
            asyncio.ensure_future(self.display_end("***REMOVED******REMOVED*** WINS".format(self.current_player.name)), loop=self.loop)

            self.log("***REMOVED******REMOVED*** won".format(self.current_player.name))
            self.future.set_result(winner)
        else:
            if self.check_end():
                asyncio.ensure_future(self.display_end("Game Over"), loop=self.loop)

                self.log("No fields left. Game Over")
                self.future.set_result(None)
                return

            self.current_turn += 1
            self.current_player = self.other_player

            asyncio.ensure_future(self.play_turn(), loop=self.loop)

    async def display_end(self, text):
        drawn_grid = "\n".join("".join(val) for val in self.draw_grid())
        end_message = "***REMOVED******REMOVED***\n\n*****REMOVED******REMOVED*****".format(drawn_grid, text)

        if self.round_interface_message:
            self.round_interface_message = await self.bot.safe_edit_message(self.round_interface_message, end_message, keep_at_bottom=True)
        else:
            self.round_interface_message = await self.bot.safe_send_message(self.channel, end_message)

        asyncio.ensure_future(self.bot._wait_delete_msg(self.round_interface_message, 10), loop=self.loop)

    async def play_turn(self):
        self.log("playing turn ***REMOVED******REMOVED***".format(self.current_turn))

        drawn_grid = "\n".join("".join(val) for val in self.draw_grid())
        round_message = "*****REMOVED******REMOVED***'s Turn**\n\n***REMOVED******REMOVED***\n\n".format(self.current_player.name, drawn_grid)

        if not isinstance(self.current_player, AIPlayer):
            round_message += "What column would you like to play next?"

        if self.round_interface_message:
            self.round_interface_message = await self.bot.safe_edit_message(self.round_interface_message, round_message, keep_at_bottom=True)
        else:
            self.round_interface_message = await self.bot.safe_send_message(self.channel, round_message)

        await self.current_player.play(self)

    def can_place(self, column):
        if not 0 <= column < len(self.grid):
            return False

        grid_column = self.grid[column]

        return grid_column[0].is_empty

    def place_stone(self, player, column):
        if self.current_player != player:
            return False

        if not self.can_place(column):
            return False

        for i, stone in enumerate(self.grid[column]):
            if not stone.is_empty:
                i -= 1  # the last one was still empty so choose that one
                break

        self.grid[column][i].possess(player)
        self.log("***REMOVED******REMOVED*** placed stone in column ***REMOVED******REMOVED***, row ***REMOVED******REMOVED***".format(player.name, column, i))

        self.next_turn()
        return True
