"""Changelog model for a playlist."""
import enum


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
        # TODO user!
        change = ChangelogChange.from_dict(data["change"])
        data = data["data"]
        timestamp = data["timestamp"]

        return cls(change, data, timestamp)

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

    @classmethod
    def from_dict(cls, data):
        """Load from dict."""
        return cls([ChangelogEntry.from_dict(change) for change in data])

    def to_dict(self):
        """Convert to dict."""
        return [change.to_dict() for change in self.changelogs]
