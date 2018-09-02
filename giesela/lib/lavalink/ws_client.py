import asyncio
import json
import logging
from collections import deque
from typing import Any, Deque, Dict, Optional

import websockets
from websockets import ConnectionClosed, WebSocketClientProtocol

from giesela.lib import EventEmitter, has_events
from .abstract import AbstractLavalinkClient
from .models import LavalinkEvent, LavalinkPlayerState

log = logging.getLogger(__name__)

__all__ = ["LavalinkWebSocket"]


@has_events("event", "unknown_event", "player_update", "disconnect")
class LavalinkWebSocket(AbstractLavalinkClient, EventEmitter):
    _ws: Optional[WebSocketClientProtocol]
    _send_queue: Deque[Dict[str, Any]]

    _shutdown_signal: bool

    def __init__(self, *, ws_uri: str, shard_count: int = None, retry_attempts: int = 3, **kwargs):
        super().__init__(**kwargs)

        self._ws = None
        self._send_queue = deque()

        self._ws_retry_attempts = retry_attempts
        self._uri = ws_uri
        self._shard_count = shard_count

        self._shutdown_signal = False

        self.loop.create_task(self.connect())

    @property
    def connected(self):
        return self._ws is not None and self._ws.open

    def shutdown(self):
        self._shutdown_signal = True

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
        log.debug(f"Connecting to Lavalink {self._uri} with {headers}...")

        self._shutdown_signal = False

        try:
            self._ws = await websockets.connect(self._uri, loop=self.loop, extra_headers=headers)
        except Exception:
            log.exception(f"Couldn't Connect to {self._uri}")
        else:
            log.info("Connected to Lavalink!")
            self.loop.create_task(self.listen())
            if self._send_queue:
                log.info(f"Sending {len(self._send_queue)} queued messages")
                for msg in self._send_queue:
                    await self.send(msg)
                self._send_queue.clear()

    async def _attempt_reconnect(self) -> bool:
        log.info("Connection closed; Trying to reconnect in 30 seconds")
        for i in range(0, self._ws_retry_attempts):
            await asyncio.sleep(30)
            log.info(f"Reconnecting... (Attempt {i + 1})")
            await self.connect()

            if self._ws.open:
                return True
        return False

    async def listen(self):
        while not self._shutdown_signal:
            try:
                data = json.loads(await self._ws.recv())
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

            op = data.get("op", None)
            log.debug(f"Received websocket data {data}")

            if not op:
                log.warning(f"No op!")
                continue

            if op == "event":
                event_type = data["type"]

                try:
                    event = LavalinkEvent(event_type)
                except ValueError:
                    log.exception(f"Received unknown event {event_type}")
                    self.emit("unknown_event", event_type=event_type, data=data)
                else:
                    log.debug(f"Received event of type {event}")
                    guild_id = int(data["guildId"])
                    track = data["track"]
                    self.emit("event", guild_id=guild_id, event=event, track=track, data=data)

            elif op == "playerUpdate":
                guild_id = int(data["guildId"])
                state = data["state"]
                state = LavalinkPlayerState(state["time"], state["position"])
                self.emit("player_update", guild_id=guild_id, state=state)

        log.debug("Closing WebSocket...")
        await self._ws.close()

    async def send(self, data: Dict[str, Any]):
        if self.connected:
            await self._ws.send(json.dumps(data))
        else:
            log.debug("not connected, adding to queue")
            self._send_queue.append(data)
