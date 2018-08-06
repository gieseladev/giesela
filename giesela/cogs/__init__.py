import importlib
import operator
from pathlib import Path
from typing import Tuple

here = Path(__file__)
files = here.parent.glob("*")


def get_extensions() -> Tuple[str]:
    _EXTENSIONS = []
    for file in files:
        if file == here or file.name.startswith("_"):
            continue

        extension_name = f"{__package__}.{file.stem}"
        extension = importlib.import_module(extension_name)
        _EXTENSIONS.append((extension_name, getattr(extension, "LOAD_ORDER", 0)))

    return next(zip(*sorted(_EXTENSIONS, key=operator.itemgetter(1))))
