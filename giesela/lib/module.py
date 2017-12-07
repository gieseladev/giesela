"""Module stuff."""
import logging

log = logging.getLogger(__name__)


class GieselaModuleMount(type):
    """The metaclass for a module which, when deriving from the inherited class, adds said class to a list."""

    def __init__(cls, name, bases, attrs):
        """Add class to list."""
        if not hasattr(cls, "modules"):
            cls.modules = []
            log.debug("created base Module class")
        else:
            cls.modules.append(cls)
            log.debug("registered module \"{}\"".format(name))


class GieselaModule(metaclass=GieselaModuleMount):
    """A module."""

    singleton = None

    def __init__(self):
        """Initialise module."""
        pass

    async def init(self):
        """Call when module loaded."""
        pass

    async def on_ready(self):
        """Call when bot ready."""
        pass

    async def _on_message(self, message):
        # TODO
        pass

    async def on_message(self, message):
        """Call when message received."""
        pass

    async def on_message_edit(self, before, after):
        """Call when message edited."""
        pass

    async def on_message_delete(self, message):
        """Call when message deleted."""
        pass

    async def on_channel_create(self, channel):
        """Call when channel created."""
        pass

    async def on_channel_update(self, before, after):
        """Call when channel updated."""
        pass

    async def on_channel_delete(self, channel):
        """Call when channel deleted."""
        pass

    async def on_member_join(self, member):
        """Call when member joined."""
        pass

    async def on_member_remove(self, member):
        """Call when member removed (left)."""
        pass

    async def on_member_update(self, before, after):
        """Call when member updated."""
        pass

    async def on_server_join(self, server):
        """Call after joining a server."""
        pass

    async def on_server_update(self, before, after):
        """Call when server updated."""
        pass

    async def on_server_role_create(self, server, role):
        """Call when role created."""
        pass

    async def on_server_role_delete(self, server, role):
        """Call when role deleted."""
        pass

    async def on_server_role_update(self, server, role):
        """Call when role updated."""
        pass

    async def on_voice_state_update(self, before, after):
        """Call when voice state updated."""
        pass

    async def on_member_ban(self, member):
        """Call when member banned."""
        pass

    async def on_member_unban(self, member):
        """Call when member unbanned."""
        pass

    async def on_typing(self, channel, user, when):
        """Call when user starts typing."""
        pass
