import abc
import asyncio
import logging
from asyncio import CancelledError
from typing import Any, Callable, Dict

from discord import Client, Message, User

from .ui_utils import EmojiType

log = logging.getLogger(__name__)

_DEFAULT = object()


class Stoppable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def stop(self):
        pass


class Startable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def start(self):
        pass


class HasBot(metaclass=abc.ABCMeta):
    def __init__(self, *args, bot: Client, **kwargs):
        super().__init__(*args, **kwargs)

        self.bot = bot


class ReactionHandler(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def on_reaction(self, emojj: EmojiType, user: User):
        pass


class MessageHandler(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def on_message(self, message: Message):
        pass


class CanSignalStop(metaclass=abc.ABCMeta):
    _stop_signal: bool

    def __init__(self, *args, **kwargs):
        self.reset_signal()
        super().__init__(*args, **kwargs)

    @property
    def stop_signal(self) -> bool:
        return self._stop_signal

    def signal_stop(self):
        self._stop_signal = True

    def reset_signal(self):
        self._stop_signal = False


class Listener(CanSignalStop, metaclass=abc.ABCMeta):
    _listener: asyncio.Task
    _result: Any
    _listen_once: Callable[[], Any]

    def __init__(self, *args, **kwargs):
        self._listener = None
        self._result = None
        self._listen_once = kwargs.pop("listen_once", None)
        super().__init__(*args, **kwargs)

    @property
    def result(self) -> Any:
        return self._result

    def cancel(self):
        self.signal_stop()
        if self._listener:
            self._listener.cancel()

    def start(self):
        self.listen()

    async def listen_once(self) -> Any:
        if self._listen_once:
            res = self._listen_once()
            if asyncio.iscoroutine(res):
                res = await res
            return res
        else:
            raise Exception("No listen_once provided!")

    async def _listen(self) -> Any:
        self.reset_signal()

        result = None
        while not self.stop_signal:
            try:
                result = await asyncio.ensure_future(self.listen_once())
            except CancelledError:
                pass
            except Exception as e:
                log.error("Error while listening once", exc_info=e)

        self._result = result
        return result

    def listen(self) -> Any:
        if not self._listener or self._listener.done():
            self._listener = asyncio.ensure_future(self._listen())
        return self._listener


class HasListener(Startable, Stoppable):
    _listeners: Dict[str, Listener]

    def __init__(self, *args, **kwargs):
        self._listeners = {}
        super().__init__(*args, **kwargs)

    def add_listener(self, name: str, listener: Listener):
        if name in self._listeners:
            raise KeyError(f"There's already a listener for \"{name}\"")

        self._listeners[name] = listener

    def create_listener(self, name: str, *args, **kwargs):
        listener = Listener(*args, **kwargs)
        self.add_listener(name, listener)

    def start_listener(self, listener: str = None):
        if listener:
            self._listeners[listener].start()
        else:
            for listener in self._listeners:
                self.start_listener(listener)

    def stop_listener(self, listener: str = None):
        if listener:
            self._listeners[listener].signal_stop()
        else:
            for listener in self._listeners:
                self.stop_listener(listener)

    def cancel_listener(self, listener: str = None):
        if listener:
            self._listeners[listener].cancel()
        else:
            for listener in self._listeners:
                self.cancel_listener(listener)

    def listener_result(self, listener: str, default: Any = _DEFAULT) -> Any:
        try:
            return self._listeners[listener].result
        except KeyError:
            if default is _DEFAULT:
                raise
            else:
                return default

    async def _wait_for_all_listeners(self, return_when):
        listeners = [listener.listen() for listener in self._listeners.values()]
        done, pending = await asyncio.wait(listeners, return_when=return_when)
        if len(done) == 1:
            return next(iter(done)).result()
        else:
            return [task.result() for task in done]

    def wait_for_listener(self, listener: str = None, *, return_when=asyncio.FIRST_COMPLETED) -> asyncio.Task:
        if listener:
            return self._listeners[listener].listen()
        else:
            return asyncio.ensure_future(self._wait_for_all_listeners(return_when))

    async def start(self):
        self.start_listener()
        await super().start()

    async def stop(self):
        self.stop_listener()
        await super().stop()
