import abc


class Stoppable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def stop(self):
        pass


class Startable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def start(self):
        pass
