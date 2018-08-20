def create_bar(progress: float, length: int = 10, *, full_char: str = "■", half_char: str = None, empty_char: str = "□"):
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


def create_scroll_bar(length: int = 10, *, full_char: str = "■", empty_char: str = "□"):
    pass
