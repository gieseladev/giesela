"""Doc."""
import enum


class ChangelogChange(enum.IntEnum):
    pass


class ChangelogEntry:
    def __init__(self, change, timestamp):
        self.change = change
        self.timestamp = timestamp


class Changelog:
    def __init__(self, changelogs):
        self.changelogs = changelogs

    @classmethod
    def from_dict(cls, data):
        pass

    def to_dict(self):
        pass
