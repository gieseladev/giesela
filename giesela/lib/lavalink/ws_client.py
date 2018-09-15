import asyncio
import logging
import rapidjson
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import websockets
from websockets import ConnectionClosed, WebSocketClientProtocol

from giesela.lib import EventEmitter, has_events
from . import utils
from .abstract import AbstractLavalinkClient
from .models import LavalinkEvent, LavalinkEventData, LavalinkPlayerState, LavalinkStats

log = logging.getLogger(__name__)

__all__ = ["LavalinkWebSocket"]


@has_events("event", "unknown_event", "player_update", "disconnect", "voice_channel_update")
class LavalinkWebSocket(AbstractLavalinkClient, EventEmitter):
    _ws: Optional[WebSocketClientProtocol]
    _send_queue: Deque[Dict[str, Any]]

    _stats = Deque[LavalinkStats]

    _shutdown_signal: bool

    def __init__(self, *, shard_count: int = None, retry_attempts: Optional[int] = 10, max_stats: int = 5, **kwargs):
        super().__init__(**kwargs)

        self._ws = None
        self._send_queue = deque()

        self._stats = deque(maxlen=max_stats)

        self._ws_retry_attempts = retry_attempts
        self._shard_count = shard_count

        self._shutdown_signal = False

        self.loop.create_task(self._try_connect())

        self._voice_state = {}
        self.bot.add_listener(self.on_socket_response)

    @property
    def connected(self):
        return self._ws is not None and self._ws.open

    @property
    def statistics(self) -> Optional[LavalinkStats]:
        if self._stats:
            return self._stats[0]

    @property
    def all_statistics(self) -> List[LavalinkStats]:
        return list(self._stats)

    async def shutdown(self):
        self._shutdown_signal = True
        self.bot.remove_listener(self.on_socket_response)
        if self._ws:
            await self._ws.close(reason="Shutdown")

    async def _try_connect(self):
        try:
            await self.connect()
        except asyncio.CancelledError:
            log.warning("connecting cancelled!")
        except Exception:
            log.exception("Couldn't connect")

    async def connect(self):
        await self.bot.wait_until_ready()

        if self.connected:
            log.debug("WebSocket still open, closing...")
            await self._ws.close()

        user_id = self.bot.user.id
        shard_count = self.bot.shard_count or self._shard_count
        if shard_count is None:
            raise ValueError("Couldn't determine number of shards")

        headers = {
            "Authorization": self._password,
            "Num-Shards": shard_count,
            "User-Id": str(user_id)
        }
        log.debug(f"Connecting to Lavalink {self._ws_url} with {headers}...")

        self._shutdown_signal = False

        try:
            self._ws = await websockets.connect(self._ws_url, loop=self.loop, extra_headers=headers)
        except OSError:
            log.exception(f"Couldn't Connect to {self._ws_url}")
        else:
            log.info(f"Connected to Lavalink {self}!")
            self.loop.create_task(self.listen())
            if self._send_queue:
                log.info(f"Sending {len(self._send_queue)} queued messages")
                for msg in self._send_queue:
                    await self.send_raw(msg)
                self._send_queue.clear()

    async def _attempt_reconnect(self) -> bool:
        attempt = 0
        log.info(f"Connection closed ({self}); Trying to reconnect")

        while True:
            delay = 2 ** attempt
            log.debug(f"waiting for {delay} seconds")
            await asyncio.sleep(delay)
            log.info(f"Reconnecting... (Attempt {attempt + 1})")
            await self.connect()

            if self._ws.open:
                return True
            else:
                attempt += 1

            if self._ws_retry_attempts and attempt >= self._ws_retry_attempts:
                log.info("exceeded max retry attempts!")
                break

        return False

    async def handle_data(self, data: Dict[str, Any]):
        op = data.get("op", None)
        log.debug(f"Received websocket data {data} {self}")

        if not op:
            log.warning(f"No op!")
            return

        if op == "event":
            event_type = data["type"]

            try:
                event = LavalinkEvent(event_type)
            except ValueError:
                log.exception(f"Received unknown event {event_type}")
                self.emit("unknown_event", event_type=event_type, raw_data=data)
            else:
                log.debug(f"Received event of type {event}")
                guild_id = int(data["guildId"])
                event_data = LavalinkEventData.from_data(event, data)
                self.emit("event", guild_id=guild_id, event=event, data=event_data)

        elif op == "playerUpdate":
            guild_id = int(data["guildId"])
            state = data["state"]
            if "position" in state:
                state = LavalinkPlayerState(state["time"], state["position"])
                self.emit("player_update", guild_id=guild_id, state=state)
            else:
                log.warning("player update didn't contain a position value...")
        elif op == "stats":
            kwargs = data.copy()
            kwargs.pop("op")
            stats = LavalinkStats.from_data(kwargs)
            self._stats.appendleft(stats)

    async def listen(self):
        while not self._shutdown_signal:
            try:
                data = rapidjson.loads(await self._ws.recv())
            except ConnectionClosed as e:
                log.warning(f"Disconnected {e}")

                self.emit("disconnect", error=e)

                if self._shutdown_signal:
                    break

                if await self._attempt_reconnect():
                    return
                else:
                    log.error("Unable to reconnect to Lavalink!")
                    break

            try:
                await self.handle_data(data)
            except Exception:
                log.exception(f"Couldn't handle message {data}")

        log.debug("Closing WebSocket...")
        await self._ws.close()

    async def on_socket_response(self, data: Dict[str, Any]):
        if not data or data.get("t") not in {"VOICE_STATE_UPDATE", "VOICE_SERVER_UPDATE"}:
            return

        # TODO don't add the listener here, just do it in the balancer or w/e

        if data["t"] == "VOICE_SERVER_UPDATE":
            event_data = data["d"]
            self._voice_state.update({
                "op": "voiceUpdate",
                "guildId": event_data["guild_id"],
                "event": event_data
            })
        else:
            event_data = data["d"]
            if int(event_data["user_id"]) != self.bot.user.id:
                return

            self._voice_state.update({"sessionId": event_data["session_id"]})

            guild_id = int(event_data["guild_id"])
            channel_id = event_data.get("channel_id")
            channel_id = int(channel_id) if channel_id else None

            self.emit("voice_channel_update", guild_id=guild_id, channel_id=channel_id)

        if self._voice_state.keys() == {"op", "guildId", "sessionId", "event"}:
            await self.send_voice_state()

    async def send_voice_state(self):
        guild_id = self._voice_state.get("guildId", "unknown")
        log.debug(f"sending voice_state for guild {guild_id}")
        await self.send_raw(self._voice_state)

    async def send_raw(self, data: Dict[str, Any]):
        if self.connected:
            log.debug(f"sending: {data}")
            await self._ws.send(rapidjson.dumps(data))
        else:
            log.debug(f"not connected, adding message to queue ({data})")
            self._send_queue.append(data)

    async def send(self, op: str, guild_id: int, **kwargs):
        kwargs.update(op=op, guildId=str(guild_id))
        return await self.send_raw(kwargs)

    async def send_play(self, guild_id: int, track: str, start_time: float = None, end_time: float = None):
        times = {}
        if start_time:
            times["startTime"] = utils.to_milli(start_time)
        if end_time:
            times["endTime"] = utils.to_milli(end_time)

        return await self.send("play", guild_id, track=track, **times)

    async def send_stop(self, guild_id: int):
        return await self.send("stop", guild_id)

    async def send_pause(self, guild_id: int, pause: bool = True):
        return await self.send("pause", guild_id, pause=pause)

    async def send_resume(self, guild_id: int, pause: bool = False):
        return await self.send("pause", guild_id, pause=pause)

    async def send_seek(self, guild_id: int, position: float):
        return await self.send("seek", guild_id, position=utils.to_milli(position))

    async def send_volume(self, guild_id: int, volume: float):
        return await self.send("volume", guild_id, volume=round(100 * volume))

    async def send_destroy(self, guild_id: int):
        return await self.send("destroy", guild_id)
