import asyncio
import logging
from typing import List

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import IndexModel
from pymongo.errors import OperationFailure

__all__ = ["ensure_index", "ensure_indexes"]

log = logging.getLogger(__name__)


async def ensure_index(collection: AsyncIOMotorCollection, index: IndexModel) -> None:
    kwargs = index.document
    kwargs["keys"] = [(key, value) for key, value in kwargs.pop("key").items()]

    try:
        await collection.create_index(**kwargs)
    except OperationFailure:
        log.debug(f"Index \"{index.document['name']}\" already exists in {collection.full_name}")


async def ensure_indexes(collection: AsyncIOMotorCollection, indexes: List[IndexModel]) -> None:
    await asyncio.gather(*(ensure_index(collection, index) for index in indexes))
