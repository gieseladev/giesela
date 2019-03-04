from typing import Any, get_type_hints

__all__ = ["annotation_only", "annotate_slots"]


def annotation_only(*_):
    """Decorating a class with this decorator will render it empty."""
    return object


def annotate_slots(cls: Any):
    slot_set = set()

    try:
        existing_slots = getattr(cls, "__slots__")
    except AttributeError:
        pass
    else:
        slot_set.update(existing_slots)

    hints = get_type_hints(cls)
    slot_set.update(hints.keys())

    setattr(cls, "__slots__", slot_set)

    return cls
