#! /usr/bin/env bash

import asyncio
import logging.config
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
            "class": "logging.FileHandler",
            "level": "DEBUG",
            "formatter": "detailed",
            "filename": "logs/giesela.txt",
            "mode": "w"
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


def unload_package(name: str):
    for module in sys.modules.copy():
        package = module.split(".")[0]
        if package == name:
            sys.modules.pop(module)


def main():
    setup_logging()

    log = logging.getLogger("giesela")

    while True:
        from giesela import Giesela, RestartSignal, TerminateSignal

        log.info("creating Giesela")
        bot = Giesela()
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
