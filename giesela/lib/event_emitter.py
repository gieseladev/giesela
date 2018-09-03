import asyncio
import collections
import logging
from typing import Awaitable, Callable, Dict, List, Optional, Set, Type, TypeVar

log = logging.getLogger(__name__)

AT = TypeVar("AT")


async def safe_await(cb: Awaitable[AT]) -> AT:
    try:
        result = await cb
    except Exception:
        log.exception(f"Exception while waiting for {cb}")
    else:
        return result


def has_events(*events: str) -> Callable[[Type["EventEmitter"]], Type["EventEmitter"]]:
    def decorator(cls: Type[EventEmitter]):
        _events = list(events)
        for _cls in cls.__mro__:
            _events.extend(getattr(_cls, "_emitted_events", []))
        _events = set(_events)
        setattr(cls, "_emitted_events", _events)

        return cls

    return decorator


class EventEmitter:
    _emitted_events: Set[str]

    _events: Dict[str, List[Callable]]
    registered_events: Optional[Set[str]]
    loop: asyncio.AbstractEventLoop

    def __init__(self, *, loop: asyncio.AbstractEventLoop = None):
        self._events = collections.defaultdict(list)

        self.registered_events = tuple(getattr(self, "_emitted_events", ()))

        self.loop = loop or asyncio.get_event_loop()

    def emit(self, event: str, *args, **kwargs):
        if not self._can_emit_event(event):
            raise ValueError(f"{self} can't emit {event}")

        method_name = f"on_{event}"
        method = getattr(self, method_name, None)
        if method and asyncio.iscoroutinefunction(method):
            asyncio.ensure_future(safe_await(method(*args, **kwargs)), loop=self.loop)

        if event not in self._events:
            return

        for cb in self._events[event]:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.ensure_future(safe_await(cb(*args, **kwargs)), loop=self.loop)
                else:
                    cb(*args, **kwargs)

            except Exception:
                log.exception(f"Couldn't call {cb}:")

    def _can_emit_event(self, event: str) -> bool:
        return self.registered_events is None or event in self.registered_events

    def on(self, event: str, cb: Callable, *, ignore_multiple: bool = True):
        if not self._can_emit_event(event):
            raise ValueError(f"{self} doesn't emit {event}")

        listeners = self._events[event]
        if cb not in listeners or not ignore_multiple:
            listeners.append(cb)
        return self

    def off(self, event: str, cb: Callable):
        listeners = self._events[event]
        if cb in listeners:
            listeners.remove(cb)

        return self
