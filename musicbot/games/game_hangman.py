class GameHangman:

    def __init__(self, word, total_tries=10):
        self.word = word.lower()
        self.right_letters = []
        self.wrong_letters = []
        self.total_tries = total_tries
        self.tries = 0

    @property
    def tries_left(self):
        return self.total_tries - self.tries

    @property
    def won(self):
        return len(self.right_letters) == len(self.word)

    @property
    def lost(self):
        return self.tries_left < 1

    def guess(self, letter):
        letter = letter.lower()

        if letter in self.word:
            if letter not in self.right_letters:
                self.right_letters.extend(
                    [letter for x in range(self.word.count(letter))])
                return True
        else:
            if letter not in self.wrong_letters:
                self.wrong_letters.append(letter)
                self.tries += 1
                return False

    def get_beautified_string(self):
        return " ".join([letter if letter in self.right_letters else "\_" for letter in list(self.word)])
