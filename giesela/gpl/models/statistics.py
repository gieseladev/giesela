"""Some interesting stuff for playlists."""


class Statistics:
    """Statistics holder."""

    __slots__ = []

    def __init__(self):
        """Create new instance."""
        pass

    @classmethod
    def from_dict(cls, data):
        """Return instance from dict."""
        return cls(**data)

    def to_dict(self):
        """Convert to dict."""
        return {}
