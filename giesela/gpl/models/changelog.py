"""Changelog model for a playlist."""
import enum
from datetime import datetime

from giesela.models import GieselaUser


class ChangelogChange(enum.IntEnum):
    """Enumeration of possible changes."""

    CREATION = 1
    RENAME = 2

    ENTRY_ADDED = 100
    ENTRY_REMOVED = 101
    ENTRY_CHANGED = 102

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        return cls(data["value"])

    def to_dict(self):
        """Convert to dict."""
        return {
            "name": self.name,
            "value": self.value
        }


class ChangelogEntry:
    """Class representing a change to a playlist."""

    def __init__(self, user, change, data, timestamp):
        """Create new change."""
        self.user = user
        self.change = change
        self.data = data
        self.timestamp = timestamp

    def __str__(self):
        """Return string rep."""
        return "<{} by {} at {}>".format(self.change.name, self.user, datetime.fromtimestamp(self.timestamp))

    @classmethod
    def rename(cls, user, from_name, to_name, timestamp):
        """When a playlist is renamed."""
        data = {
            "from": from_name,
            "to": to_name
        }
        return cls(user, ChangelogChange.RENAME, data, timestamp)

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        user = GieselaUser.from_dict(data["user"])
        change = ChangelogChange.from_dict(data["change"])
        d = data["data"]
        timestamp = data["timestamp"]

        return cls(user, change, d, timestamp)

    def to_dict(self):
        """Convert to dict."""
        return {
            "user": self.user.to_dict(),
            "change": self.change.to_dict(),
            "data": self.data,
            "timestamp": self.timestamp
        }


class Changelog:
    """The complete changelog for a playlist."""

    def __init__(self, changelogs):
        """Initialise."""
        self.changelogs = changelogs

    def __str__(self):
        """Get string rep."""
        return "<Changelog | {} entries>".format(self.changelogs)

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        return cls([ChangelogEntry.from_dict(change) for change in data])

    def to_dict(self):
        """Convert to dict."""
        return [change.to_dict() for change in self.changelogs]
