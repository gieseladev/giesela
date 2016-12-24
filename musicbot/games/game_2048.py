import colorsys
import random
from math import pow, sqrt, log2

from PIL import Image, ImageDraw, ImageSequence


class Game2048:

    def __init__(self, size=None, save_string=None):
        if save_string is None:
            self.grid = [[Tile() for i in range(size)] for j in range(size)]
            self.addRandomTile()
            self.addRandomTile()
        else:
            self.grid, size = self.from_save(save_string)

        self.size = size
        self.new_game = True

    def __str__(self):
        ret = ''
        iS = ***REMOVED******REMOVED***
        for j in self.grid:
            for i in range(len(j)):
                iS[i] = max((iS.get(i) if iS.get(
                    i) is not None else -1), len(str(j[i])))
        for j in self.grid:
            for i in range(len(j)):
                ret = ret + str(j[i]) + ' ' + ' ' * (iS[i] - len(str(j[i])))
            ret = ret + '\n'
        return ret.replace(' 0', '  ').replace('0 ', '  ')
        return '\n'.join([' '.join([str(i) for i in j]) for j in self.grid]).replace(' 0', '  ').replace('0 ', '  ')

    def getImage(self, loc="cache/pictures/g2048_img"):
        fieldSize = 50
        img = Image.new('RGBA', (self.size * fieldSize, self.size * fieldSize))
        draw = ImageDraw.Draw(img)
        for i in range(len(self.grid)):
            for j in range(len(self.grid[i])):
                number = self.grid[i][j].value if self.grid[
                    i][j].value is not None else 0
                rec_top = (j * fieldSize, i * fieldSize)
                rec = [rec_top, (rec_top[0] + fieldSize,
                                 rec_top[1] + fieldSize)]
                draw.rectangle(rec, fill=self.findColors(number)[0])

                if number == 0:
                    continue

                textsize = draw.textsize(str(number))
                textrec = (rec_top[0] + fieldSize / 2 - textsize[0] / 2,
                           rec_top[1] + fieldSize / 2 - textsize[1] / 2)
                draw.text(textrec, str(number), self.findColors(number)[1])

        img.save(loc + ".png", "PNG")

        if self.new_game:
            gif = img
            self.new_game = False
        else:
            gif = Image.open(loc + ".gif")

        frames = [frame.copy() for frame in ImageSequence.Iterator(gif)]

        frames.append(img)

        gif.save(loc + ".gif", "GIF", save_all=True,
                 append_images=frames, duration=700)

        return loc

    def findColors(self, num):
        if (num != 0 and ((num & (num - 1)) == 0)):
            bi = bin(num)
            po = len(bi)
            hue = 30.0 * po - 100
            rgb = colorsys.hls_to_rgb(hue / 256.0, 0.5, 0.5)
            rgb = [str(hex(int(256 * x)))[2:3] for x in rgb]
            return "#" + str(rgb[0]) + str(rgb[1]) + str(rgb[2]), "#FFFFFF"
        else:
            return "#cdc1b5", "#000000"

    def get_save(self):
        encoded = []
        empty = 0
        for row in self.grid:
            for tile in row:
                if tile.value <= 0:
                    empty += 1
                    continue
                else:
                    if empty > 0:
                        encoded.append("_" + encode52(empty))
                        empty = 0

                v = log2(tile.value)
                encoded.append(encode52(int(v)))

        if empty > 0:
            encoded.append("_" + encode52(empty))

        return "-".join(encoded)

    def from_save(self, save_code):
        elements = save_code.split("-")
        n_grid = []
        for el in elements:
            if el.startswith("_"):
                empties = decode52(el[1:])
                n_grid.extend([0 for x in range(empties)])
            else:
                n_grid.append(int(pow(2, decode52(el))))

        new_size = int(sqrt(len(n_grid)))
        r_grid = []
        for row in range(new_size):
            r = []
            for column in range(new_size):
                r.append(Tile(n_grid[row * new_size + column]))
            r_grid.append(r)

        return r_grid, new_size

    def addRandomTile(self):
        availableTiles = self.getAvailableTiles()
        findTile = self.findTile(random.choice(availableTiles))
        self.grid[findTile[0]][findTile[1]] = Tile(2)

    def getAvailableTiles(self):
        ret = []
        for i in self.grid:
            for j in i:
                if j.value == 0:
                    ret.append(j)
        return ret

    def findTile(self, tile):
        for i in range(len(self.grid)):
            for j in range(len(self.grid[i])):
                if self.grid[i][j] == tile:
                    return i, j

    def move(self, direction):
        merged = []
        moved = False
        lines = rotate(self.grid, direction + 1)
        for line in lines:
            while len(line) and line[-1].value == 0:
                line.pop(-1)
            i = len(line) - 1
            while i >= 0:
                if line[i].value == 0:
                    moved = True
                    line.pop(i)
                i -= 1
            i = 0
            while i < len(line) - 1:
                if line[i].value == line[i + 1].value and not (line[i] in merged or line[i + 1] in merged):
                    moved = True
                    line[i] = Tile(line[i].value * 2)
                    merged.append(line[i])
                    line.pop(i + 1)
                else:
                    i += 1
            while len(line) < len(self.grid):
                line.append(Tile())
        for line in lines:
            if not len(lines):
                line = [Tile() for i in self.grid]
        self.grid = rotate(lines, 0 - (direction + 1))
        if moved:
            self.addRandomTile()

    def playGame(self):
        done = False
        while not done:
            print(self)
            inp = raw_input()
            if inp == 'q':
                break
            elif inp in ['0', '1', '2', '3']:
                self.move(int(inp))
            if self.lost():
                print("You have lost")
                break
            if self.won():
                print("You have won")
                break

    def lost(self):
        s = len(self.grid) - 1
        b = True
        for i in range(len(self.grid)):
            for j in range(len(self.grid[i])):
                val = self.grid[i][j].value
                if val == 0:
                    b = False
                if i > 0 and self.grid[i - 1][j].value == val:
                    b = False
                if j > 0 and self.grid[i][j - 1].value == val:
                    b = False
                if i < s and self.grid[i + 1][j].value == val:
                    b = False
                if j < s and self.grid[i][j + 1].value == val:
                    b = False
        return b

    def won(self):
        for i in range(len(self.grid)):
            for j in range(len(self.grid[i])):
                if self.grid[i][j].value >= 2048:
                    return True
        return False

    def getValues(self):
        ret = []
        for i in self.grid:
            for j in i:
                ret.append(j)
        return ret


class Tile:

    def __init__(self, value=0):
        self.value = value

    def __str__(self):
        return str(self.value)


def rotate(l, num):
    num = num % 4
    s = len(l) - 1
    l2 = []
    if num == 0:
        l2 = l
    elif num == 1:
        l2 = [[None for i in j] for j in l]
        for y in range(len(l)):
            for x in range(len(l[y])):
                l2[x][s - y] = l[y][x]
    elif num == 2:
        l2 = l
        l2.reverse()
        for i in l:
            i.reverse()
    elif num == 3:
        l2 = [[None for i in j] for j in l]
        for y in range(len(l)):
            for x in range(len(l[y])):
                l2[y][x] = l[x][s - y]
    return l2


def encode52(n):
    n -= 1
    r_str = ""
    e_table = list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    a, b = divmod(n, 52)
    for i in range(a + 1):
        r_str += str(e_table[b if i >= a else 51])

    return r_str


def decode52(s):
    e_table = list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    num = 0
    for c in s:
        num += e_table.index(c) + 1

    return num
