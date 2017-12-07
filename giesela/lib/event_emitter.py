"""Event emitter."""

import asyncio
import collections
import logging

log = logging.getLogger(__name__)


class EventListener:
    """A listener."""

    def __init__(self, emitter, event, cb, *, once=False):
        """Instantiate."""
        self.emitter = emitter
        self.event = event
        self.cb = cb

        self.once = once

    def __str__(self):
        """Return string."""
        return "<Listener ({})>".format(self.event)

    def emit(self, *args, **kwargs):
        """Emit event."""
        try:
            if asyncio.iscoroutinefunction(self.cb):
                asyncio.ensure_future(self.cb(*args, **kwargs), loop=self.emitter.loop)
            else:
                self.cb(*args, **kwargs)

        except Exception:
            log.exception("Error when emitting {}".format(self))
        finally:
            if self.once:
                self.emitter._off(self)


class EventEmitter:
    """Event emitter base class."""

    def __init__(self):
        """Gotta instantiate, right."""
        self._events = collections.defaultdict(list)
        self.loop = asyncio.get_event_loop()

    def emit(self, event, *args, **kwargs):
        """Emit an event."""
        if event not in self._events:
            return

        for listener in self._events[event]:
            listener.emit(*args, **kwargs)

    def on(self, event, cb):
        """Call cb on event."""
        listener = EventListener(self, cb, event)
        self._events[event].append(listener)

        return self

    def once(self, event, cb):
        """Only listen once."""
        listener = EventListener(self, cb, event, once=True)
        self._events[event].append(listener)

        return self

    def _off(self, listener):
        event = listener.event
        self._events[event].remove(listener)

        if not self._events[event]:
            del self._events[event]

        return self

    def off(self, event, cb):
        """Turn listener off."""
        listeners = self._events[event]

        listener = next(l for l in listeners if l.cb is cb)

        return self._off(listener)
