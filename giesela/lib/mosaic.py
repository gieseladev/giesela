import asyncio
import logging
import math
import random
from contextlib import suppress
from io import BytesIO
from typing import Iterable, List, Optional, TYPE_CHECKING, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from aiohttp import ClientSession

from giesela.lib.api.imgur import upload_playlist_cover

if TYPE_CHECKING:
    from giesela.playlist import Playlist

log = logging.getLogger(__name__)


def _create_diamond_square_collage(*images: Image.Image, size: int = 1024) -> Image.Image:
    if len(images) not in {1, 5, 9, 13}:
        raise ValueError("Need 1, 5, 9, or 13 images!")

    images = list(images)

    canvas: Image.Image = Image.new("RGBA", (size, size), color=None)

    inner_size: int = int(.9925 * size)
    diamond_len: int = int(3 * math.sqrt(2) * inner_size / (13 + math.sqrt(2)))

    diamond_mask = Image.new("1", (diamond_len, diamond_len), color=1).rotate(45, expand=True)

    # place center image
    img = images.pop().resize(diamond_mask.size)
    canvas.paste(img, box=get_center_pos(img, canvas), mask=diamond_mask)

    x_center: float = canvas.height / 2
    y_center: float = canvas.height / 2

    if len(images) >= 4:
        # place adjacent images
        for i_y in range(2):
            y_pos: int = int(y_center - i_y * diamond_mask.height)

            for i_x in range(2):
                x_pos: int = int(x_center - i_x * diamond_mask.width)

                img = images.pop().resize(diamond_mask.size)
                canvas.paste(img, box=(x_pos, y_pos), mask=diamond_mask)

    if len(images) >= 4:
        small_dia_width: int = int(2 / 3 * diamond_mask.width)
        small_dia_mask = diamond_mask.resize((small_dia_width, small_dia_width))

        tr_s: float = small_dia_mask.width / 2
        touching_radius: float = diamond_mask.width / 2

        # place in-between small images
        for rot in range(4):
            angle: float = rot * math.pi / 2
            touching_x_pos: float = x_center + math.cos(angle) * touching_radius
            touching_y_pos: float = y_center + math.sin(angle) * touching_radius

            fac_x: int = (0, 1, 2, 1)[rot]
            x_pos: int = int(touching_x_pos - fac_x * tr_s)

            fac_y: int = (1, 0, 1, 2)[rot]
            y_pos: int = int(touching_y_pos - fac_y * tr_s)

            img = images.pop().resize(small_dia_mask.size)
            canvas.paste(img, box=(x_pos, y_pos), mask=small_dia_mask)

        if len(images) >= 4:
            dangle_offset: float = math.sqrt(2) * 1 / 4 * small_dia_width
            touching_radius: float = 1.5 * diamond_len - dangle_offset

            # place tip small images
            for rot in range(4):
                angle: float = math.pi / 4 + rot * math.pi / 2
                touching_x_pos: float = x_center + math.cos(angle) * touching_radius
                touching_y_pos: float = y_center + math.sin(angle) * touching_radius

                x_pos: int = int(touching_x_pos - (rot == 1 or rot == 2) * small_dia_width)
                y_pos: int = int(touching_y_pos - (rot >= 2) * small_dia_width)

                img = images.pop().resize(small_dia_mask.size)
                canvas.paste(img, box=(x_pos, y_pos), mask=small_dia_mask)

    return canvas


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


def _create_striped_collage(*images: Image, size: int = 1024) -> Image.Image:
    if len(images) < 2:
        raise ValueError("Need at least 2 images")

    if len(images) > 5:
        images = random.sample(images, 5)

    stripe_width = size // len(images)
    canvas = Image.new("RGB", (size, size))

    for i, image in enumerate(images):
        box = (i * stripe_width, 0, (i + 1) * stripe_width, size)
        image = image.crop(box=box)
        canvas.paste(image, box=box)

    return canvas


def _create_partitioned_striped_collage(*images: Image, size: int = 1024) -> Image.Image:
    if len(images) < 3:
        raise ValueError("Need at least 3 images")

    min_pick = 1
    max_pick = max(round(len(images) / 3), 3)

    if len(images) == 3:
        max_pick = 2

    images = list(images)
    stripes = []
    while images:
        im_count = random.randint(min(len(images), min_pick), min(len(images), max_pick))
        stripe = [images.pop() for _ in range(im_count)]
        stripes.append(stripe)

    stripe_width = size // len(stripes)
    canvas = Image.new("RGB", (size, size), color="white")

    min_height = size // 6

    for i, stripe in enumerate(stripes):
        image_count = len(stripe)
        max_height = size - image_count * min_height
        heights = []
        start = 0
        for _ in range(image_count - 1):
            height = random.randint(min_height, max_height)
            new_start = start + height
            heights.append((start, new_start))
            start = new_start
        heights.append((start, size))

        for j, image in enumerate(stripe):
            start, stop = heights[j]
            box = (i * stripe_width, start, (i + 1) * stripe_width, stop)
            image = ImageOps.fit(image, (stripe_width, stop - start))
            canvas.paste(image, box=box)

    return canvas


def _create_pie_chart(*images: Image.Image, size: int = 1024) -> Image.Image:
    if len(images) > 5:
        images = random.sample(images, 5)

    final = Image.new("RGBA", (size, size))

    angle = 360 / len(images)

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


def get_center_pos(im: Image.Image, canvas: Image.Image) -> Tuple[int, int]:
    x = (canvas.width - im.width) // 2
    y = (canvas.height - im.height) // 2
    return x, y


def _create_octagonal_focused_collage(*images: Image.Image, size: int = 1024) -> Image.Image:
    if len(images) < 5:
        raise ValueError("Need at least 5 images")

    if len(images) > 6:
        images = random.sample(images, 6)
    else:
        images = list(images)

    if len(images) > 5:
        background: Image.Image = images.pop()
        background = background.filter(ImageFilter.GaussianBlur(5))
    else:
        hue = random.randrange(0, 360)
        colour = f"hsv({hue}, 60%, 15%)"
        background = Image.new("RGB", (size, size), color=colour)

    half_size = 2 * (size // 2,)

    half_mask = Image.new("1", half_size, color=1).rotate(45)

    center_image: Image.Image = images.pop()
    center_image = center_image.resize(half_size)

    background.paste(center_image, box=get_center_pos(center_image, background), mask=half_mask)

    for i in range(4):
        corner_image: Image.Image = images.pop()
        corner_image = corner_image.resize(half_size)

        top = i < 2
        left = i % 2 == 0

        x = -corner_image.width // 4 if left else size - 3 * corner_image.width // 4
        y = -corner_image.height // 4 if top else size - 3 * corner_image.height // 4

        corner_image = ImageEnhance.Color(corner_image).enhance(.5)
        background.paste(corner_image, box=(x, y), mask=half_mask)

    return background


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

    if len(images) in {1, 5, 9, 13}:
        possible.extend((_create_diamond_square_collage,))

    if len(images) >= 2:
        possible.extend((_create_striped_collage,))

    if len(images) >= 3:
        possible.extend((_create_partitioned_striped_collage,))

    if len(images) >= 4:
        possible.extend((_create_focused_collage, _create_normal_collage))

    if len(images) >= 5:
        possible.extend((_create_stacked_collage, _create_octagonal_focused_collage))

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

    images = await asyncio.gather(*tasks)
    return list(filter(None, images))


async def generate_playlist_cover(playlist: "Playlist", size: int = 1024) -> Optional[str]:
    covers = {pl_entry.entry.cover for pl_entry in playlist.entries if pl_entry.entry.cover}
    log.debug(f"generating cover for {playlist}, found ({len(covers)} cover(s))")
    if not covers:
        return None

    if len(covers) > 13:
        covers = random.sample(covers, 13)

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
