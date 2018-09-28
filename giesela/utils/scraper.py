import logging
from typing import Any, Dict, List, Optional, Union

from aiohttp import ClientSession
from bs4 import BeautifulSoup
from bs4.element import Tag

__all__ = ["Resolver", "Scraper"]

log = logging.getLogger(__name__)


class Resolver:
    selector: str
    attribute: Optional[str]

    def __init__(self, selector: str, attribute: str = None) -> None:
        self.selector = selector
        self.attribute = attribute

    @classmethod
    def from_config(cls, config: Union[str, Dict[str, Any]]) -> "Resolver":
        if isinstance(config, str):
            selector = config
            attribute = None
        else:
            selector = config.pop("selector")
            attribute = config.pop("attribute", None)
        return cls(selector, attribute)

    @classmethod
    def process_value(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    def resolve_one(self, bs: Tag) -> str:
        target = bs.select_one(self.selector)

        if self.attribute:
            value = target[self.attribute]
            if value and isinstance(value, list):
                value = " ".join(value)
            value = str(value)
        else:
            value = str(target.text)

        return self.process_value(value)


class Scraper:
    url: str
    targets: Dict[str, Resolver]

    def __init__(self, url: str, targets: Dict[str, Resolver]) -> None:
        self.url = url
        self.targets = targets

    @property
    def keys(self) -> List[str]:
        return list(self.targets.keys())

    @classmethod
    def from_config(cls, config: Dict[str, Union[str, Dict[str, Any]]]) -> "Scraper":
        url: str = config.pop("url")
        targets = {key: Resolver.from_config(value) for key, value in config.items()}
        return cls(url, targets)

    def absolute_url(self, url: str, *, https: bool = True) -> str:
        if url.startswith("//"):
            pre = "https" if https else "http"
            return f"{pre}:{url}"
        elif url.startswith("/") or not url.startswith(("http://", "https://")):
            base_url = self.url.rstrip("/")
            url = url.lstrip("/")
            return f"{base_url}/{url}"
        return url

    async def get_soup(self, session: ClientSession) -> BeautifulSoup:
        async with session.get(self.url) as resp:
            text = await resp.text()
        return BeautifulSoup(text, "lxml")

    async def scrape(self, session: ClientSession, *, silent: bool = True) -> Dict[str, Any]:
        bs = await self.get_soup(session)
        data = {}
        for key, resolver in self.targets.items():
            try:
                value: Optional[str] = resolver.resolve_one(bs)
            except Exception:
                if not silent:
                    raise
                log.exception(f"Couldn't fetch {key} with {resolver}")
                value = None

            data[key] = value

        return data
