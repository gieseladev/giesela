from typing import Union

from discord import Embed, Emoji

EmojiType = Union[Emoji, str]


class EmbedLimits:
    TITLE_LIMIT = 256
    DESCRIPTION_LIMIT = 2048
    FIELDS_LIMIT = 25
    FIELD_NAME_LIMIT = 256
    FIELD_VALUE_LIMIT = 1024
    FOOTER_TEXT_LIMIT = 2048
    AUTHOR_NAME_LIMIT = 256

    CHAR_LIMIT = 6000


def copy_embed(embed: Embed) -> Embed:
    return Embed.from_data(embed.to_dict())


def format_embed(embed: Embed, _copy=True, **fmt) -> Embed:
    if _copy:
        embed = copy_embed(embed)

    if embed.title:
        embed.title = embed.title.format(**fmt)

    if embed.description:
        embed.description = embed.description.format(**fmt)

    if embed.author.name:
        embed.set_author(name=embed.author.name.format(**fmt), url=embed.author.url, icon_url=embed.author.icon_url)

    if embed.footer.text:
        embed.set_footer(text=embed.footer.text.format(**fmt), icon_url=embed.footer.icon_url)

    for i, field in enumerate(embed.fields):
        embed.set_field_at(i, name=field.name.format(**fmt), value=field.value.format(**fmt), inline=field.inline)

    return embed


def count_embed_chars(embed: Embed) -> int:
    count = 0

    if embed.title:
        count += len(embed.title)

    if embed.description:
        count += len(embed.description)

    if embed.author.name:
        count += len(embed.author.name)

    if embed.footer.text:
        count += len(embed.footer.text)

    count += sum(len(field.name) + len(field.value) for field in embed.fields)

    return count
