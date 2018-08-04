import logging

import raven
from raven.handlers.logging import SentryHandler

from giesela.constants import VERSION

log = logging.getLogger("giesela")

raven_client = raven.Client(release=VERSION)


def setup_logging():
    log.info("setting up Raven logging")

    handler = SentryHandler(raven_client)

    handler.setLevel(logging.ERROR)

    raven.conf.setup_logging(handler)

    log.info("Raven logging set-up!")


setup_logging()
