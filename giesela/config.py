"""The configuration of Giesela."""

import json
import logging

from giesela import constants
from giesela.models import exceptions

log = logging.getLogger(__name__)


REQUIRED_KEYS = {"token"}


class Config:
    """The configuration holder."""

    def __init__(self, config):
        """Setup."""
        self._config = config

        for key, value in config.items():
            if key not in REQUIRED_KEYS:
                log.warn("{} in config shouldn't be there!".format(key))

            setattr(self, key, value)

    @classmethod
    def load(cls):
        """Load config from location."""
        try:
            with open(constants.FileLocations.CONFIG, "r") as f:
                config = json.load(f)
        except json.JSONDecodeError:
            log.exception("Couldn't decode config file")
            config = {}

        return cls(config)

    def check(self):
        """Check whether the config is proper."""
        missing = REQUIRED_KEYS - set(self._config.keys())

        if missing:
            raise exceptions.ConfigKeysMissing(missing)
