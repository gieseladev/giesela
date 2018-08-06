from typing import Iterable, List

from discord import Embed

from .utils import copy_embed


class EmbedPaginator:
    MAX_FIELDS = 25
    MAX_FIELD_NAME = 256
    MAX_FIELD_VALUE = 1024
    MAX_TOTAL = 2000

    every_embed: Embed
    first_embed: Embed

    _cur_embed: Embed
    _embeds: List[Embed]

    def __init__(self, *, first_embed: Embed = None, every_embed: Embed = None):
        self.every_embed = every_embed or Embed()
        self.first_embed = first_embed or self.every_embed

        self._cur_embed = copy_embed(first_embed) if first_embed else self.create_embed()
        self._embeds = []

    def __str__(self) -> str:
        return f"<EmbedPaginator>"

    def __iter__(self) -> Iterable[Embed]:
        return iter(self.embeds)

    @property
    def predefined_count(self) -> int:
        em = self._cur_embed
        return len(em.title or "") + len(em.description or "") + len(em.author.name or "") + len(em.footer.text or "")

    @property
    def total_count(self) -> int:
        return self.predefined_count + sum(len(field.name) + len(field.value) for field in self._cur_embed.fields)

    @property
    def embeds(self) -> List[Embed]:
        self.close_embed()
        return self._embeds

    def create_embed(self) -> Embed:
        return copy_embed(self.every_embed)

    def close_embed(self):
        self._embeds.append(self._cur_embed)
        self._cur_embed = self.create_embed()

    def add_field(self, name: str, value: str, inline: bool = False):
        if len(name) > self.MAX_FIELD_NAME:
            raise ValueError(f"Field name mustn't be longer than {self.MAX_FIELD_NAME} characters")
        if len(value) > self.MAX_FIELD_VALUE:
            raise ValueError(f"Field value mustn't be longer than {self.MAX_FIELD_VALUE} characters")
        count = len(name) + len(value)
        if self.total_count + count > self.MAX_TOTAL:
            self.close_embed()
        em = self._cur_embed
        em.add_field(name=name, value=value, inline=inline)
        if len(em.fields) >= self.MAX_FIELDS:
            self.close_embed()
