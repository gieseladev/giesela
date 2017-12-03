"""Playlist."""

from giesela.models import GieselaUser

from .changelog import Changelog
from .playlist_entry import PlaylistEntry


class Playlist:
    """A playlist."""

    __slots__ = ["gpl_id", "entries", "title", "description", "cover", "creator", "changelog"]

    manager = None

    def __init__(self, gpl_id, entries, title, description, cover, creator, changelog, *args, **kwargs):
        """Doc."""
        self.gpl_id = gpl_id
        self.entries = entries

        for entry in self.entries:
            entry.playlist = self

        self.title = title
        self.description = description
        self.cover = cover

        self.creator = creator

        self.changelog = changelog

    def __str__(self):
        """Return simple string rep."""
        return "<Playlist {}>".format(self.title)

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        data.update({
            "entries": [PlaylistEntry.from_dict(entry) for entry in data["entries"]],
            "creator": GieselaUser.from_dict(data["creator"]),
            "changelog": Changelog.from_dict(data["changelog"])
        })

        return cls(**data)

    def to_dict(self):
        """Serialise to dict."""
        return {
            "gpl_id": self.gpl_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "title": self.title,
            "description": self.description,
            "cover": self.cover,
            "creator": self.creator.to_dict(),
            "changelog": self.changelog.to_dict()
        }

    def save(self):
        """Save the playlist to disk."""
        pass
