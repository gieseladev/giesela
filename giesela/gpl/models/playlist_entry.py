"""Single playlist entry."""


class PlaylistEntry:
    """An entry in a playlist."""

    manager = None

    def __init__(self, adder, entry, changelog, timestamp, statistics):
        """Initialise playlist entry."""
        self.playlist = None

        self.adder = adder
        self.entry = entry

        self.changelogs = changelog
        self.timestamp = timestamp
        self.statistics = statistics

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        return cls(**data)

    def to_dict(self):
        """Serialise to dict."""
        pass
