from os import path

MAIN_VERSION = "5.4.11"
SUB_VERSION = "refreshed"
VERSION = MAIN_VERSION + "_" + SUB_VERSION

maj_versions = {
    "5": "Refreshed",
    "4": "Webiesela",
    "3": "Giesenesis"
}

AUDIO_CACHE_PATH = path.join("cache", "audio_cache")
