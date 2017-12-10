"""Start Giesela."""
import asyncio
import gc
import json
import logging
import logging.config
import time

from giesela import constants
from giesela.models import signals
from giesela.reporting import raven_client

log = logging.getLogger("giesela")


def setup_logging():
    """Load the logging configuration and apply it."""
    with open(constants.FileLocations.LOGGING) as f:
        config = json.load(f)

    logging.config.dictConfig(config)


def main():
    """Do everything."""
    setup_logging()

    restart = True

    loops = 0
    max_wait_time = 60

    while restart:
        try:
            from giesela.bot import Giesela

            g = Giesela()
            g.run()

        except SyntaxError:
            raven_client.captureException()
            log.exception("Syntax Error!")
            break

        except ImportError as e:
            raven_client.captureException()
            log.exception("Import Error!")
            break
        except signals.StopSignal:
            break
        except Exception as e:
            raven_client.captureException()
            log.exception("Something is broken!")

        finally:
            asyncio.set_event_loop(asyncio.new_event_loop())
            loops += 1

        log.info("Cleaning!")
        gc.collect()
        log.debug("Done.")

        sleeptime = min(loops * 2, max_wait_time)

        if sleeptime:
            log.info("Restarting in {} seconds...".format(loops * 2))
            time.sleep(sleeptime)


if __name__ == "__main__":
    main()
