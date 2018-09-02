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


def setup_logging():
    Path("logs").mkdir(exist_ok=True)

    logging.config.dictConfig(LOGGING)
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
        from giesela import Giesela, RestartSignal, TerminateSignal

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
