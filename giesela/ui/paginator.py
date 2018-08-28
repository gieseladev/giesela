from typing import Iterable, List, Optional

from discord import Embed

from . import utils
from .utils import EmbedLimits


class EmbedPaginator:
    """
    Keyword Args:
        template: Embed to use as a template
        special_template: Embed or Dict[int, Embed]. Former will be used for the first embed and the latter
            will be used for a given index
        fields_per_embed: Amount of fields before using a new embed
    """
    template: Embed
    fields_per_page: int

    _embed: Embed
    _embeds: List[Embed]

    def __init__(self, **kwargs):
        self.template = kwargs.pop("template", Embed())
        _special_template = kwargs.pop("special_template", None)
        if isinstance(_special_template, Embed):
            self._first_embed = _special_template
        elif isinstance(_special_template, dict):
            self._special_template_map = _special_template

        self.fields_per_page = kwargs.get("fields_per_page", EmbedLimits.FIELDS_LIMIT)
        if not 0 < self.fields_per_page <= EmbedLimits.FIELDS_LIMIT:
            raise ValueError(f"Fields per page must be between 1 and {EmbedLimits.FIELDS_LIMIT}")

        self._embeds = []

    def __str__(self) -> str:
        return f"<EmbedPaginator>"

    def __len__(self) -> int:
        return len(self._embeds)

    def __iter__(self) -> Iterable[Embed]:
        return iter(self._embeds)

    def __getitem__(self, item: int) -> Embed:
        return self._embeds[item]

    @property
    def embeds(self) -> List[Embed]:
        return self._embeds

    @property
    def current_embed(self) -> Optional[Embed]:
        if self._embeds:
            return self._embeds[-1]

    def _add_embed(self) -> Embed:
        number = len(self)

        template = None
        if number == 0:
            template = getattr(self, "_first_embed", None)

        if not template and hasattr(self, "_special_template_map"):
            template = self._special_template_map.get(number)

        template = template or self.template
        embed = utils.copy_embed(template)
        self._embeds.append(embed)
        return embed

    def add_field(self, name: str, value: str, inline: bool = False):
        embed = self.current_embed
        if not embed:
            embed = self._add_embed()

        if len(name) > EmbedLimits.FIELD_NAME_LIMIT:
            raise ValueError(f"Field name mustn't be longer than {EmbedLimits.FIELD_NAME_LIMIT} characters")
        if len(value) > EmbedLimits.FIELD_VALUE_LIMIT:
            raise ValueError(f"Field value mustn't be longer than {EmbedLimits.FIELD_VALUE_LIMIT} characters")

        count = utils.count_embed_chars(embed) + len(name) + len(value)

        if len(embed.fields) >= self.fields_per_page or count > EmbedLimits.CHAR_LIMIT:
            embed = self._add_embed()

        embed.add_field(name=name, value=value, inline=inline)
