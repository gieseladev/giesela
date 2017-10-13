import logging

import raven
from raven.handlers.logging import SentryHandler

from musicbot.constants import VERSION

log = logging.getLogger("Giesela")

raven_client = raven.Client(
    dsn="https://24b803ec11c74aabb0d77fc8cd29b756:4237b717a00c4a0ca4220ea333273fcd@sentry.io/229530",
    release=VERSION
)


def setup_logging():
    log.info("setting up Raven logging")

    handler = SentryHandler(raven_client)

    handler.setLevel(logging.ERROR)

    raven.conf.setup_logging(handler)

    log.info("Raven logging set-up!")


setup_logging()
