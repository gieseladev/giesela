from pathlib import Path

EXTENSIONS = []

here = Path(__file__)
files = here.parent.glob("*")

for file in files:
    if file == here or file.name.startswith("_"):
        continue

    EXTENSIONS.append(f"{__package__}.{file.stem}")
