import asyncio
import copy
import random

from discord import User


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
                game.log("{} stopped the game".format(self.name))
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
                    await game.bot.safe_send_message(game.channel, "Your number should be between 1 and {}".format(len(game.grid)), expire_in=5)
            else:
                await game.bot.safe_send_message(game.channel, "Please send a number", expire_in=5)


class VirtualGameState:
    def __init__(self, grid, current_player, iteration):
        self.grid = grid
        self.current_player = current_player
        self.iteration = iteration

    @classmethod
    def from_game_grid(cls, grid, player):
        simplified_grid = []

        for column in grid:
            simplified_column = []

            for stone in column:
                simplified_column.append(0 if stone.is_empty else 1 if stone.belongs_to(player) else 2)

            simplified_grid.append(simplified_column)

        return cls(simplified_grid, 1, 0)

    def get_available_moves(self):
        available = []

        for index, column in enumerate(self.grid):
            if not column[0]:
                available.append(index)

        return available

    def next_state(self, move):
        grid_copy = copy.deepcopy(self.grid)

        # place stone @ correct place
        for i, stone in enumerate(grid_copy[move]):
            if stone:
                i -= 1  # the last one was still empty so choose that one
                break

        grid_copy[move][i] = self.current_player

        return VirtualGameState(grid_copy, (1 if self.current_player == 2 else 2), self.iteration + 1)

    def _count_n_horizontal(self, n, player=None):
        counted = {}

        for i in range(len(self.grid[0])):
            streak = 1
            streak_holder = self.grid[0][i]

            for column in self.grid[1:]:
                stone = column[i]

                if streak_holder == stone:
                    streak += 1
                else:
                    if streak == n:
                        counted[streak_holder] = counted.get(streak_holder, 0) + 1

                    streak_holder = stone
                    streak = 1

            if streak == n:
                counted[streak_holder] = counted.get(streak_holder, 0) + 1

        # print("horizontal", counted)

        if player is None:
            counted.pop(0, 0)
            return sum(counted.values())
        else:
            return counted.get(player, 0)

    def _count_n_vertical(self, n, player=None):
        counted = {}

        for column in self.grid:
            streak = 1
            streak_holder = column[0]

            for stone in column[1:]:
                if stone == streak_holder:
                    streak += 1
                else:
                    if streak == n:
                        counted[streak_holder] = counted.get(streak_holder, 0) + 1

                    streak_holder = stone
                    streak = 1

            if streak == n:
                counted[streak_holder] = counted.get(streak_holder, 0) + 1

        # print("vertical", counted)

        if player is None:
            counted.pop(0, 0)
            return sum(counted.values())
        else:
            return counted.get(player, 0)

    def count_n(self, n, player=None):
        return self._count_n_horizontal(n, player=player) + self._count_n_vertical(n, player=player)

    def is_gameover(self):
        if not self.get_available_moves():
            return True

        # check if won
        if self.count_n(4) > 0:
            return True

        return False

    def evaluate(self):
        weights = {
            4: 100000,
            3: 10,
            2: 1
        }

        me = sum([self.count_n(streak, player=1) * weight for streak, weight in weights.items()])
        opponent = sum([self.count_n(streak, player=2) * weight for streak, weight in weights.items()])

        return me - opponent


class AIPlayer(ConnectFourPlayer):

    def __init__(self, colour, level):
        super().__init__(colour)
        self.level = level

        self.opponent = None

    @property
    def name(self):
        return "Giesela (lvl {})".format(self.level)

    def _debug_log_grid(self, grid):
        lines = []

        for i in range(len(grid[0])):
            line = []

            for column in grid:
                stone = column[i]
                line.append(str(stone))

            lines.append(line)

        print("-----------------\n" + "\n".join("".join(val) for val in lines) + "\n--------------------------")

    def minimax(self, game_state):
        return max(
            map(
                lambda move: (
                    move,
                    self.min_play(game_state.next_state(move))
                ),
                game_state.get_available_moves()
            ),
            key=lambda x: x[1]
        )

    def min_play(self, game_state):
        if game_state.is_gameover() or game_state.iteration > self.level:
            return game_state.evaluate()

        return min(
            map(
                lambda move: self.max_play(game_state.next_state(move)),
                game_state.get_available_moves()
            )
        )

    def max_play(self, game_state):
        if game_state.is_gameover() or game_state.iteration > self.level:
            return game_state.evaluate()

        return max(
            map(
                lambda move: self.min_play(game_state.next_state(move)),
                game_state.get_available_moves()
            )
        )

    async def play(self, game):
        game_state = VirtualGameState.from_game_grid(game.grid, self)

        column = self.minimax(game_state)

        game.log("bot placing at {}".format(column))
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
            raise WrongUserType("No idea what to do with \"{}\"...".format(type(users)))

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
        asyncio.ensure_future(self.display_end("{} ABORTED".format(self.current_player.name)), loop=self.loop)
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
                                game.log("{} wins horizontally".format(current_player.name))
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
                                game.log("{} wins vertically".format(current_player.name))
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
                        game.log("{} wins diagonally".format(current_player.name))
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
            asyncio.ensure_future(self.display_end("{} WINS".format(self.current_player.name)), loop=self.loop)

            self.log("{} won".format(self.current_player.name))
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
        end_message = "{}\n\n**{}**".format(drawn_grid, text)

        if self.round_interface_message:
            self.round_interface_message = await self.bot.safe_edit_message(self.round_interface_message, end_message, keep_at_bottom=True)
        else:
            self.round_interface_message = await self.bot.safe_send_message(self.channel, end_message)

        asyncio.ensure_future(self.bot._wait_delete_msg(self.round_interface_message, 10), loop=self.loop)

    async def play_turn(self):
        self.log("playing turn {}".format(self.current_turn))

        drawn_grid = "\n".join("".join(val) for val in self.draw_grid())
        round_message = "**{}'s Turn**\n\n{}\n\n".format(self.current_player.name, drawn_grid)

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
        self.log("{} placed stone in column {}, row {}".format(player.name, column, i))

        self.next_turn()
        return True


if __name__ == "__main__":
    grid = [
        [0, 0, 0, 0, 0, 0, 1, 2],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0]
    ]

    print("startig")

    board = VirtualGameState(grid, 1, 0)

    print(AIPlayer(None, 5).minimax(board))

    # print(board.count_n(3))
