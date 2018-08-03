#! /usr/bin/env bash

import logging.config
from pathlib import Path

LOGGING = {
    "version": 1,
    "formatters": {
        "brief": {
            "format": "{asctime} {module} {levelname} >> {message}",
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
            "filename": "logs/giesela.txt"
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


def main():
    setup_logging()

    from giesela import Giesela
    print("creating Giesela")
    bot = Giesela()
    print("running...")
    bot.run()


if __name__ == "__main__":
    main()
