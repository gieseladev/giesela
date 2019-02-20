#! /usr/bin/env bash

import asyncio
import logging.config
import logging.handlers
import sys
from pathlib import Path

LOGGING = {
    "version": 1,
    "formatters": {
        "brief": {
            "()": "colorlog.ColoredFormatter",
            "format": "{black}{asctime}{reset} {blue}{module}{reset} {log_color}{levelname}{reset}: {message}",
            "style": "{"
        },
        "detailed": {
            "format": "{asctime} {name} {levelname} >> {message}",
            "style": "{"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "brief",
            "level": "DEBUG",
            "stream": "ext://sys.__stdout__"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "detailed",
            "filename": "logs/giesela.log",
            "backupCount": 3
        }
    },
    "loggers": {
        "giesela": {
            "level": "DEBUG",
            "propagate": False,
            "handlers": ["console", "file"]
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"]
    }
}


def setup_sentry(*, release: str = None):
    import sentry_sdk

    sentry_sdk.init(release=release)


def setup_logging():
    Path("logs").mkdir(exist_ok=True)

    logging.config.dictConfig(LOGGING)
    # noinspection PyProtectedMember
    handler = logging._handlers.get("file")  # type: logging.handlers.RotatingFileHandler
    handler.doRollover()


def setup_uvloop():
    import asyncio
    try:
        import uvloop
    except ImportError:
        logging.info("Not using uvloop")
    else:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        logging.info("using uvloop")


def unload_package(name: str):
    for module in sys.modules.copy():
        package = module.split(".")[0]
        if package == name:
            sys.modules.pop(module)


def main():
    setup_logging()
    setup_uvloop()

    log = logging.getLogger("giesela")

    while True:
        log.debug("loading Giesela code...")

        from giesela import Giesela, RestartSignal, TerminateSignal, constants
        setup_sentry(release=constants.VERSION)

        log.info("creating Giesela")
        bot = Giesela()
        log.info(f"Giesela runtime #id: {id(bot)}")
        log.info("running...")
        try:
            bot.run()
        except RestartSignal:
            log.info("restarting")
            asyncio.set_event_loop(asyncio.new_event_loop())
            unload_package("giesela")
        except TerminateSignal:
            break
        else:
            break

    log.info("shut down")


if __name__ == "__main__":
    main()
