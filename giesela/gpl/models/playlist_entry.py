"""Single playlist entry."""


class PlaylistEntry:
    """An entry in a playlist."""

    __slots__ = ["playlist", "adder", "entry", "changelogs", "timestamp", "statistics"]

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
        return {
            "adder": self.adder.to_dict(),
            "entry": self.entry.to_dict(),
            "changelog": self.changelog.to_dict(),
            "timestamp": self.timestamp,
            "statistics": self.statistics.to_dict()
        }
