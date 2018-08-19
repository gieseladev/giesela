import abc

from discord import Message, Reaction, User


class Stoppable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def stop(self):
        pass


class Startable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def start(self):
        pass


class ReactionHandler(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def on_reaction(self, reaction: Reaction, user: User):
        pass


class MessageHandler(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def on_message(self, message: Message):
        pass
