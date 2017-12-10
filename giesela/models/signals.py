"""Giesela Signal."""


class GieselaSignal(Exception):
    """A Giesela Signal."""

    pass


class StopSignal(GieselaSignal):
    """Tell her to stop."""

    pass
