"""Single playlist entry."""


class PlaylistEntry:
    """A entry in a playlist."""

    def __init__(self, playlist, adder, entry, changelog, timestamp, statistics):
        """Initialise playlist entry."""
        self.playlist = playlist
        self.adder = adder
        self.entry = entry

        self.changelogs = changelog
        self.timestamp = timestamp
        self.statistics = statistics

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        pass

    def to_dict(self):
        """Serialise to dict."""
        pass
