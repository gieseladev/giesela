"""Playlist."""


class Playlist:
    """A playlist."""

    def __init__(self, gpl_id, entries, title, description, cover, creator, contributors, changelog, timestamp):
        """Doc."""
        self.gpl_id = gpl_id
        self.entries = entries

        self.title = title
        self.description = description
        self.cover = cover

        self.creator = creator
        self._contributors = contributors

        self.changelog = changelog
        self.timestamp = timestamp

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        return cls(**data)

    def to_dict(self):
        """Serialise to dict."""
        pass

    def save(self):
        """Save the playlist to disk."""
        pass
