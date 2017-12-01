"""Test."""


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
        pass

    def to_dict(self):
        pass

    def save(self):
        pass


class PLaylistEntry:
    """A entry in a playlist."""

    def __init__(self, playlist, adder, entry, changelog, timestamp, statistics):
        self.playlist = playlist
        self.adder = adder
        self.entry = entry

        self.changelogs = changelog
        self.timestamp = timestamp
        self.statistics = statistics

    @classmethod
    def from_dict(cls, data):
        pass

    def to_dict(self):
        pass
