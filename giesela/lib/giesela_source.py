"""Giesela's reader and streamer and what have you.
This player combines Discord.py's FFmpeg & VolumeTransformer players with seeking and progress tracking.
Another fancy thing is the possibility to wait for the player to reach a certain timestamp.
"""

import asyncio
import logging
from typing import List, NamedTuple

from discord import FFmpegPCMAudio, PCMVolumeTransformer

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
BIT_DEPTH = 16
CHANNEL_COUNT = 2

BYTES_PER_SECOND = SAMPLE_RATE * (BIT_DEPTH / 8) * CHANNEL_COUNT


class PlayerTimestamp(NamedTuple):
    timestamp: float
    bytestamp: float
    future: asyncio.Future


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

    def wait_for_timestamp(self, timestamp: float, future: asyncio.Future = None) -> asyncio.Future:
        """Return a Future which is  set to True when the player passes timestamp."""
        future = future or asyncio.Future()
        bytestamp = timestamp * BYTES_PER_SECOND
        ind = 0
        for ind, waiter in enumerate(self.waiters):
            if bytestamp < waiter.bytestamp:
                break

        self.waiters.insert(ind, PlayerTimestamp(timestamp, bytestamp, future))
        return future

    def seek(self, s: float):
        """Seek to s in the stream."""
        self.bytes_read = BYTES_PER_SECOND * s
        self.original = self.get_ffmpeg(self.source, start=s)

    def read(self):
        """Read and increase frame count."""
        ret = super().read()
        self.bytes_read += len(ret)

        if self.waiters:
            for waiter in self.waiters.copy():
                if self.bytes_read >= waiter.bytestamp:
                    waiter.future.set_result(True)
                    self.waiters.remove(waiter)
                else:
                    # Because we're making sure that the waiters are in ascending (bytestamp) order we know that this is the last one.
                    break
        return ret

    def cleanup(self):
        """Clean up and make sure to tell the waiters that it's over."""
        for waiter in self.waiters:
            waiter.future.set_result(False)
        super().cleanup()
