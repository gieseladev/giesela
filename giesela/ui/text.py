import math

ZERO_WIDTH_SPACE = r"​"  # please pay attention to your cursor

DEFAULT_FULL_CHAR = "■"
DEFAULT_EMPTY_CHAR = "□"

LINE_CHAR = "▬"

ESCAPE_CHARS = list(r"<>_*`\\")

CLOSING_MAP = {
    "<": ">"
}


def escape_discord(text: str) -> str:
    for char in ESCAPE_CHARS:
        text = text.replace(char, f"\\{char}")
    return text


def find_closing(char: str) -> str:
    if len(char) > 1:
        s = "".join(find_closing(c) for c in char)
        return s[::-1]

    return CLOSING_MAP.get(char, char)


def wrap(text: str, char: str, closing: str = None) -> str:
    closing = closing or find_closing(char)
    return char + text + closing


def keep_whitespace(text: str) -> str:
    return wrap(text, ZERO_WIDTH_SPACE)


def shorten(text: str, width: int, overflow: str = "...") -> str:
    if len(text) > width:
        over_len = len(overflow)
        text = text[:-over_len] + overflow
    return text


def create_player_bar(progress: float, length: int = 20, handle_char: str = "🔘", bar_char: str = LINE_CHAR) -> str:
    position = round(progress * length)

    if position > 0:
        bar = (position - 1) * bar_char + handle_char
    else:
        bar = handle_char

    return bar.ljust(length, bar_char)


def create_bar(progress: float, length: int = 10, *, full_char: str = DEFAULT_FULL_CHAR, half_char: str = None,
               empty_char: str = DEFAULT_EMPTY_CHAR) -> str:
    fill_to_double = round(2 * length * progress)
    residue = fill_to_double % 2
    fill_to = fill_to_double / 2
    if half_char:
        fill_to = int(fill_to)
    else:
        fill_to = round(fill_to)

    full_bar = fill_to * full_char

    if half_char and residue > 0:
        full_bar += half_char

    bar = full_bar.ljust(length, empty_char)
    return bar


def create_scroll_bar(progress: float, visible: float, length: int = 10, *, full_char: str = DEFAULT_FULL_CHAR,
                      empty_char: str = DEFAULT_EMPTY_CHAR) -> str:
    start_fill = progress
    end_fill = progress + visible
    start_index = math.floor(start_fill * length)
    end_index = math.ceil(end_fill * length)

    fill_length = round(end_index - start_index)
    if fill_length < 1:
        if start_index == length:
            start_index -= 1
        fill_length += 1

    filled = fill_length * full_char
    empty = start_index * empty_char

    return (empty + filled).ljust(length, empty_char)
