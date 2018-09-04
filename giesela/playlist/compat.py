import enum
from typing import Any, Dict, List, Optional, Union


class GPLVersion(enum.IntEnum):
    v1 = 1
    v2 = 2
    v3 = 3


class FixApproach(enum.Flag):
    impossible = 0
    auto = enum.auto()
    input_required = enum.auto()
    extractor_required = enum.auto()

    def has_flag(self, flag: "FixApproach") -> bool:
        return bool(self & flag)


GPLType = Union[Dict[str, Any], List[Dict[str, Any]]]


def get_version(data: GPLType) -> Optional[GPLVersion]:
    # v1 was a list of entries, no metadata
    if isinstance(data, list):
        return GPLVersion.v1
    elif not isinstance(data, dict):
        return None

    entries = data.get("entries")
    if entries:
        entry = entries[0]
        # v2 doesn't use wrappers
        if "entry" not in entry:
            return GPLVersion.v2

    # should be fine
    return GPLVersion.v3


def get_fix_approach(data: GPLType) -> FixApproach:
    version = get_version(data)
    if not version:
        # nothing we can do about this
        return FixApproach.impossible

    if version == GPLVersion.v1:
        return FixApproach.input_required | FixApproach.extractor_required
    elif version == GPLVersion.v2:
        return FixApproach.extractor_required

    return FixApproach.auto
