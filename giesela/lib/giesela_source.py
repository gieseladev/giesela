"""Giesela's reader and streamer and what have you.
This player combines Discord.py's FFmpeg & VolumeTransformer players with seeking and progress tracking.
Another fancy thing is the possibility to wait for the player to reach a certain timestamp.
"""

import asyncio
import logging
from typing import Any, Callable, List, TypeVar, Union

from discord import FFmpegPCMAudio, PCMVolumeTransformer

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
BIT_DEPTH = 16
CHANNEL_COUNT = 2

BYTES_PER_SECOND = SAMPLE_RATE * (BIT_DEPTH / 8) * CHANNEL_COUNT


class PlayerTimestamp:
    timestamp: float
    bytestamp: float
    only_when_latest: bool
    future: asyncio.Future

    _triggered: bool

    def __init__(self, timestamp: float, only_when_latest: bool, future: asyncio.Future):
        self.timestamp = timestamp
        self.bytestamp = timestamp * BYTES_PER_SECOND
        self.only_when_latest = only_when_latest
        self.future = future
        self._triggered = False

    @property
    def triggered(self) -> bool:
        return self._triggered

    def trigger(self):
        setattr(self, "_triggered", True)
        self.future.set_result(True)

    def cancel(self):
        self.future.set_result(False)


RT = TypeVar("RT")


async def callback_after_future(future: asyncio.Future, callback: Callable[[], RT]) -> RT:
    """Wait for a future to return and then call a function"""
    await future
    res = callback()
    if asyncio.iscoroutine(res):
        res = await res
    return res


class GieselaSource(PCMVolumeTransformer):
    """The player."""
    source: str
    bytes_read: int
    waiters: List[PlayerTimestamp]

    def __init__(self, source: str, volume: float):
        """Initialise."""
        ffmpeg_source = self.get_ffmpeg(source)
        super().__init__(ffmpeg_source, volume)
        self.source = source
        self.bytes_read = 0
        self.waiters = []

    def __str__(self) -> str:
        """Return string rep."""
        return "<GieselaPlayer {}s at {}%>".format(self.progress, round(self.volume * 100))

    @property
    def progress(self) -> float:
        """Get progress into song in seconds."""
        return self.bytes_read / BYTES_PER_SECOND

    @classmethod
    def get_ffmpeg(cls, source: str, start: float = None) -> FFmpegPCMAudio:
        """Return a FFmpeg audio instance."""
        kwargs = {
            "pipe": False,
            "stderr": None,
            "before_options": "",
            "options": ""
        }
        if start:
            kwargs["before_options"] += f"-ss {start}"
        return FFmpegPCMAudio(source, **kwargs)

    def _update_waiters(self):
        only_latest = []

        for waiter in self.waiters.copy():
            if self.bytes_read >= waiter.bytestamp:
                if waiter.only_when_latest:
                    only_latest.append(waiter)
                else:
                    waiter.trigger()
                self.waiters.remove(waiter)
            else:
                # Because we're making sure that the waiters are in ascending (bytestamp) order we know that this is the last one.
                break

        if only_latest:
            only_latest.pop().trigger()
            for waiter in only_latest:
                waiter.cancel()

    def wait_for_timestamp(self, timestamp: float, *, only_when_latest: bool = False,
                           target: Union[asyncio.Future, Callable[[], Any]] = None) -> asyncio.Future:
        return_val = None

        if isinstance(target, asyncio.Future):
            future = target
        elif target:
            # create future which will be used in PlayerTimestamp
            future = asyncio.Future()
            # call the target after the future returns
            wrapped = callback_after_future(future, target)
            return_val = asyncio.ensure_future(wrapped)
        else:
            future = asyncio.Future()

        bytestamp = timestamp * BYTES_PER_SECOND
        ind = 0
        for ind, waiter in enumerate(self.waiters):
            if bytestamp < waiter.bytestamp:
                break

        self.waiters.insert(ind, PlayerTimestamp(timestamp, only_when_latest, future))
        return return_val or future

    def seek(self, s: float):
        """Seek to s in the stream."""
        self.bytes_read = BYTES_PER_SECOND * s
        self.original = self.get_ffmpeg(self.source, start=s)
        self._update_waiters()

    def read(self):
        """Read and increase frame count."""
        ret = super().read()
        self.bytes_read += len(ret)

        if self.waiters:
            self._update_waiters()
        return ret

    def cleanup(self):
        """Clean up and make sure to tell the waiters that it's over."""
        for waiter in self.waiters:
            waiter.cancel()
        super().cleanup()
