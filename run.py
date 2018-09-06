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
            "format": "{asctime} {module} ({name}) {levelname} >> {message}",
            "style": "{"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "brief",
            "level": "DEBUG",
            "stream": "ext://sys.stdout"
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
    from raven import Client
    from raven.handlers.logging import SentryHandler

    if any(isinstance(handler, SentryHandler) for handler in logging.root.handlers):
        logging.info("sentry already setup")
        return

    sentry_client = Client(release=release)
    sentry_handler = SentryHandler(sentry_client)
    sentry_handler.setLevel(logging.ERROR)

    def record_filter(record: logging.LogRecord) -> bool:
        return getattr(record, "report", True)

    sentry_handler.addFilter(record_filter)

    logging.root.addHandler(sentry_handler)
    logging.getLogger("giesela").addHandler(sentry_handler)


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
            log.info("shut down")
            break


if __name__ == "__main__":
    main()
