import asyncio
import functools
import itertools
import logging
import math
from asyncio import AbstractEventLoop
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Union

from discord import VoiceRegion
from websockets import ConnectionClosed

from giesela.config.app import LavalinkNodeRegion
from .models import LavalinkEvent, LavalinkPlayerState, LavalinkStats, TrackEventDataType
from .node import LavalinkNode
from .rest_client import LavalinkREST
from ..event_emitter import EventEmitter, has_events

log = logging.getLogger(__name__)

VOICE_REGION_MAP = {
    LavalinkNodeRegion.ASIA: ["sydney", "singapore", "japan", "hongkong"],
    LavalinkNodeRegion.EU: ["london", "frankfurt", "amsterdam", "russia", "eu-central", "eu-west"],
    LavalinkNodeRegion.US: ["us-central", "us-west", "us-east", "us-south", "brazil"]
}


def find_region_for_voice_region(voice_region: Union[str, VoiceRegion]) -> LavalinkNodeRegion:
    if isinstance(voice_region, VoiceRegion):
        voice_region = voice_region.value

    return next((region for region, voice_regions in VOICE_REGION_MAP.items() if voice_region in voice_regions), LavalinkNodeRegion.GLOBAL)


def calculate_penalty(stats: LavalinkStats):
    player_penalty = stats.playing_players
    # just blatantly stealing Lavalink's formula
    cpu_penalty = math.pow(1.05, 100 * stats.cpu.system_load) * 10 - 10

    if stats.frame_stats:
        deficit_frame_penalty = math.pow(1.03, 500 * stats.frame_stats.deficit / 3000) * 600 - 600
        null_frame_penalty = math.pow(1.03, 500 * stats.frame_stats.nulled / 3000) * 300 - 300
        null_frame_penalty *= 2
    else:
        deficit_frame_penalty = null_frame_penalty = 0

    return sum((player_penalty, cpu_penalty, deficit_frame_penalty, null_frame_penalty))


def choose_best_node(nodes: Iterable[LavalinkNode]) -> LavalinkNode:
    if not nodes:
        raise ValueError("No nodes to pick from!")

    best_node = lowest_penalty = None

    no_stats = []
    not_connected = []

    for node in nodes:
        if not node.connected:
            log.debug(f"{node} isn't connected")
            not_connected.append(node)
            continue

        stats = node.statistics
        if not stats:
            log.debug(f"{node} doesn't have any statistics, not picking!")
            no_stats.append(node)
            continue

        penalty = calculate_penalty(node.statistics)
        if lowest_penalty is None or penalty < lowest_penalty:
            lowest_penalty = penalty
            best_node = node

    if not best_node:
        log.warning("Couldn't find a single valid node")
        if no_stats:
            log.info("using node without stats")
            return no_stats[0]
        if not_connected:
            log.warning("using node that isn't connected...")
            return not_connected[0]

        raise ValueError("Couldn't pick a node. This shouldn't even be possible...")

    return best_node


def _create_nodes(node_list: List[LavalinkNode]) -> Dict[LavalinkNodeRegion, LavalinkNode]:
    node_dict = {}
    for node in node_list:
        nodes = node_dict.get(node.region, [])
        nodes.append(node)
        node_dict[node.region] = nodes
    return node_dict


@has_events("event", "unknown_event", "player_update", "disconnect", "voice_channel_update")
class LavalinkNodeBalancer(EventEmitter):

    def __init__(self, loop: AbstractEventLoop, nodes: Union[List[LavalinkNode], Dict[LavalinkNodeRegion, List[LavalinkNode]]]):
        super().__init__(loop=loop)
        self.loop = loop

        if isinstance(nodes, list):
            nodes = _create_nodes(nodes)

        self._nodes = nodes
        # noinspection PyTypeChecker
        self._node_pool = deque(itertools.chain.from_iterable(nodes.values()), maxlen=len(nodes))

        map(self._add_listeners, self._nodes.values())

    def __enter__(self):
        return self.get_rest_node()

    def _add_listeners(self, node: LavalinkNode):
        node \
            .on("event", functools.partial(self.on_event, node=node)) \
            .on("unknown_event", functools.partial(self.on_unknown_event, node=node)) \
            .on("player_update", functools.partial(self.on_player_update, node=node)) \
            .on("disconnect", functools.partial(self.on_disconnect, node=node)) \
            .on("voice_channel_update", functools.partial(self.on_voice_channel_update, node=node))

    def get_nodes_for_region(self, voice_region: Union[str, VoiceRegion]) -> List[LavalinkNode]:
        region = find_region_for_voice_region(voice_region)
        nodes = self._nodes.get(region)

        if not nodes:
            log.warning(f"no nodes found for {region}")
            global_nodes = self._nodes.get(LavalinkNodeRegion.GLOBAL)
            if global_nodes:
                nodes = global_nodes
            else:
                log.info("no global nodes, using all of them")
                nodes = list(self._nodes.values())

        return nodes

    def pick_node(self, voice_region: Union[str, VoiceRegion]):
        return choose_best_node(self.get_nodes_for_region(voice_region))

    def get_rest_node(self) -> LavalinkREST:
        node = self._node_pool[0]
        self._node_pool.rotate(1)
        return node

    async def shutdown(self):
        coros = []
        for node in self._nodes.values():
            coros.append(node.shutdown())

        await asyncio.gather(*coros, loop=self.loop)

    async def on_event(self, node: LavalinkNode, guild_id: int, event: LavalinkEvent, data: TrackEventDataType):
        pass

    async def on_unknown_event(self, node: LavalinkNode, event_type: str, raw_data: Dict[str, Any]):
        pass

    async def on_player_update(self, node: LavalinkNode, guild_id: int, state: LavalinkPlayerState):
        pass

    async def on_disconnect(self, node: LavalinkNode, error: ConnectionClosed):
        pass

    async def on_voice_channel_update(self, node: LavalinkNode, guild_id: int, channel_id: Optional[int]):
        pass
