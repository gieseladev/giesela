import logging
import math
from asyncio import AbstractEventLoop
from collections import deque
from typing import Dict, Iterable, List, Union

from discord import VoiceRegion

from giesela.config.app import LavalinkNodeRegion
from .models import LavalinkStats
from .node import LavalinkNode
from .rest_client import LavalinkREST

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

    for node in nodes:
        stats = node.statistics
        if not stats:
            log.debug("{node} doesn't have any statistics, not picking!")
            continue

        penalty = calculate_penalty(node.statistics)
        if penalty < lowest_penalty:
            lowest_penalty = penalty
            best_node = node

    return best_node


class LavalinkNodeBalancer:

    def __init__(self, loop: AbstractEventLoop, nodes: Dict[LavalinkNodeRegion, LavalinkNode]):
        self.loop = loop
        self._nodes = nodes
        self._node_pool = deque(nodes.values(), maxlen=len(nodes))

    def __enter__(self):
        return self.get_rest_node()

    def get_nodes_for_region(self, voice_region: VoiceRegion) -> List[LavalinkNode]:
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

    def pick_node(self, voice_region: VoiceRegion):
        return choose_best_node(self.get_nodes_for_region(voice_region))

    def get_rest_node(self) -> LavalinkREST:
        node = self._node_pool[0]
        self._node_pool.rotate(1)
        return node
