import math
import random
import time
from io import BytesIO

import requests
from PIL import Image, ImageDraw


def grab_images(*urls, size=None):
    images = []

    for img_url in urls:
        resp = requests.get(img_url)
        content = BytesIO(resp.content)
        im = Image.open(content)

        if size:
            im = im.resize((size, size))

        images.append(im)

    return images


def _create_normal_collage(*images, size=1024, crop_images=False):
    if len(images) not in (4, 9, 16):
        raise ValueError("Can only create images with 4, 9 or 16 pictures")

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


def _create_piechart(*images, size=1024):
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


def _create_focused_collage(*images, size=1024):
    if len(images) % 2 != 0:
        raise ValueError("Can only do this with multiples of two")

    if len(images) < 4:
        raise ValueError("Amount of images should be at least 4")

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


def _create_stacked_collage(*images, size=1024, size_ratio=.55):
    if len(images) != 5:
        raise AttributeError("Can only do this for 5 images")

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
    lower_right = center + overlay_center

    circle_mask = Image.new("1", (overlay_size, overlay_size))
    draw = ImageDraw.Draw(circle_mask)

    draw.ellipse((0, 0, overlay_size, overlay_size), fill=1)

    final.paste(overlay, box=(upper_left, upper_left), mask=circle_mask)

    return final


def create_random_cover(*images, size=1024):
    if not 1 <= len(images) <= 10:
        raise AttributeError("Provide between 1 and 10 pictures")

    possible = []

    for test, func in possible_sizes:
        if test(len(images)):
            possible.append(func)

    if not possible:
        possible.append(_create_piechart)

    generator = random.choice(possible)

    return generator(*images, size=size)


possible_sizes = (
    (lambda n: n in (4, 9), _create_normal_collage),
    (lambda n: n % 2 == 0, _create_focused_collage),
    (lambda n: n == 5, _create_stacked_collage)
)


# if __name__ == "__main__":
#     covers = [
#         "http://www.designformusic.com/wp-content/uploads/2015/10/insurgency-digital-album-cover-design.jpg",
#         "http://www.billboard.com/files/styles/900_wide/public/media/Joy-Division-Unknown-Pleasures-album-covers-billboard-1000x1000.jpg",
#         "http://www.billboard.com/files/styles/900_wide/public/media/Funkadelic-Maggot-Brain-album-covers-billboard-1000x1000.jpg",
#         "https://spark.adobe.com/images/landing/examples/design-music-album-cover.jpg",
#         "https://cdn.pastemagazine.com/www/system/images/photo_albums/album-covers/large/album4chanceacidrap.jpg?1384968217",
#         # "http://www.billboard.com/files/styles/900_wide/public/media/Green-Day-American-Idiot-album-covers-billboard-1000x1000.jpg",
#         # "http://www.billboard.com/files/styles/900_wide/public/media/The-Rolling-Stones-Sticky-Fingers-album-covers-billboard-1000x1000.jpg",
#         # "http://www.fuse.tv/image/56fe73a1e05e186b2000009b/768/512/the-boxer-rebellion-ocean-by-ocean-album-cover-full-size.jpg",
#         # "https://cdn.pastemagazine.com/www/system/images/photo_albums/albums-gallery/large/twenty-one-pilots---blurryface.png?1384968217"
#     ]
#
#     start = time.time()
#     images = grab_images(*covers)
#
#     start = time.time()
#     img = _create_stacked_collage(*images)
#     # print(time.time() - start)
#     # img.show()
#
#     image_file = BytesIO()
#     img.save(image_file, format="PNG")
#     image_file.seek(0)
#
#     cover_url = _upload_playlist_cover("stacked_collage", image_file)
#     print(cover_url)
