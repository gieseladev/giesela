import asyncio
import logging
import math
import random
from contextlib import suppress
from io import BytesIO
from typing import Iterable, List, Optional, TYPE_CHECKING

from PIL import Image, ImageDraw
from aiohttp import ClientSession

from giesela.lib.api.imgur import upload_playlist_cover

if TYPE_CHECKING:
    from giesela.playlists import Playlist

log = logging.getLogger(__name__)


def _create_normal_collage(*images: Image, size: int = 1024, crop_images: bool = False) -> Image.Image:
    if len(images) < 4:
        raise ValueError("Need at least 4 images!")

    if len(images) not in (4, 9, 16):
        if len(images) > 16:
            target_length = 16
        elif len(images) > 9:
            target_length = 9
        else:
            target_length = 4
        images = random.sample(images, target_length)

    s = round(math.sqrt(len(images)))

    part_size = size // s

    final = Image.new("RGB", (size, size))

    for i in range(s):
        for j in range(s):
            left = i * part_size
            top = j * part_size

            im = images[i * s + j]

            if crop_images:
                right = left + part_size
                bottom = top + part_size

                im = im.resize((size, size)).crop((left, top, right, bottom))
            else:
                im = im.resize((part_size, part_size))

            final.paste(im, box=(left, top))

    return final


def _create_pie_chart(*images: Image.Image, size: int = 1024) -> Image.Image:
    if len(images) > 5:
        images = random.sample(images, 5)

    final = Image.new("RGBA", (size, size))

    angle = 360 / len(images)

    mask = Image.new("1", (size, size))
    draw = ImageDraw.Draw(mask)

    draw.pieslice((0, 0, size, size), -90, -90 + angle, fill=1)

    for ind, image in enumerate(images):
        mask = Image.new("1", (size, size))
        draw = ImageDraw.Draw(mask)

        draw.pieslice((0, 0, size, size), -90 + ind * angle, -90 + (ind + 1) * angle, fill=1)

        image = image.resize((size, size))
        final.paste(image, mask=mask)

    return final


def _create_focused_collage(*images: Image.Image, size: int = 1024) -> Image.Image:
    if len(images) < 4:
        raise ValueError("Amount of images should be at least 4")

    if len(images) % 2 != 0:
        images = random.sample(images, len(images) - 1)

    final = Image.new("RGB", (size, size))

    focus_image_size = size * (len(images) - 2) // len(images)
    other_images_size = size - focus_image_size

    focus_image = images[0].resize((focus_image_size, focus_image_size))
    final.paste(focus_image, box=(0, size - focus_image_size))

    top_right = images[1].resize((other_images_size, other_images_size))
    final.paste(top_right, box=(focus_image_size, 0))

    leftover = images[2:]

    for i in range(len(leftover) // 2):
        left = leftover[i].resize((other_images_size, other_images_size))
        right = leftover[-i - 1].resize((other_images_size, other_images_size))

        final.paste(left, box=(i * other_images_size, 0))
        final.paste(right, box=(focus_image_size, (i + 1) * other_images_size))

    return final


def _create_stacked_collage(*images: Image.Image, size: int = 1024, size_ratio: float = .55) -> Image.Image:
    if len(images) < 5:
        raise AttributeError("Can only do this for 5 images")

    if len(images) != 5:
        images = random.sample(images, 5)

    final = Image.new("RGB", (size, size))

    part_size = size // 2
    overlay_size = round(size * size_ratio)

    overlay = images[0].resize((overlay_size, overlay_size))

    final.paste(images[1].resize((part_size, part_size)), box=(0, 0))
    final.paste(images[2].resize((part_size, part_size)), box=(part_size, 0))
    final.paste(images[3].resize((part_size, part_size)), box=(0, part_size))
    final.paste(images[4].resize((part_size, part_size)), box=(part_size, part_size))

    center = size // 2
    overlay_center = overlay_size // 2

    upper_left = center - overlay_center

    circle_mask = Image.new("1", (overlay_size, overlay_size))
    draw = ImageDraw.Draw(circle_mask)

    draw.ellipse((0, 0, overlay_size, overlay_size), fill=1)

    final.paste(overlay, box=(upper_left, upper_left), mask=circle_mask)

    return final


def create_random_cover(*images: Image.Image, size: int = 1024) -> Image.Image:
    if not images:
        raise AttributeError("Provide at least one picture")

    possible = [_create_pie_chart]

    if len(images) >= 4:
        possible.extend((_create_focused_collage, _create_normal_collage))

    if len(images) >= 5:
        possible.append(_create_stacked_collage)

    generator = random.choice(possible)
    return generator(*images, size=size)


async def _download_image(session: ClientSession, url: str, size: int = None) -> Optional[Image.Image]:
    async with session.get(url) as resp:
        with suppress(Exception):
            content = BytesIO(await resp.read())
            im = Image.open(content)
            if size:
                im = im.resize((size, size))

            return im


async def download_images(session: ClientSession, links: Iterable[str], size: int = None) -> List[Image.Image]:
    tasks = []
    for link in links:
        tasks.append(_download_image(session, link, size))
    return await asyncio.gather(*tasks)


async def generate_playlist_cover(playlist: "Playlist", size: int = 1024) -> Optional[str]:
    covers = [entry.cover for entry in playlist.entries if entry.cover]
    log.debug(f"generating cover for {playlist}, found ({len(covers)} cover(s))")
    if not covers:
        return None

    if len(covers) > 10:
        covers = random.sample(covers, 10)

    async with ClientSession() as session:
        images = await download_images(session, covers, size)

    log.debug(f"extracted {len(images)} image(s)")

    if not images:
        return None

    _cover = create_random_cover(*images, size=size)
    log.debug("generated cover")
    cover = BytesIO()
    _cover.save(cover, format="PNG")
    cover.seek(0)

    log.debug("uploading cover...")
    return await upload_playlist_cover(playlist.name, cover)
