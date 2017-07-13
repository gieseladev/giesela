import os.path
import re

import requests
from bs4 import BeautifulSoup

MAIN_VERSION = "4.0.0"
SUB_VERSION = "Giesenesis"
VERSION = MAIN_VERSION + "_" + SUB_VERSION

all_sub_versions = {
    "3.9.x": "Giesenesis",
    "3.8.x": "Giezela",
    "3.7.x": "Giese_La_La_Land",
    "3.6.x": "Weebiesela",
    "3.5.x": "Veggiesela",
    "3.4.x": "Gunzulalela",
    "3.3.x": "Giselator",
    "3.2.x": "GG_iesela",
    "3.1.x": "age_of_Giesela",
    "3.0.x": "Giesela-PLUS"}

AUDIO_CACHE_PATH = os.path.join(os.getcwd(), "audio_cache")
DISCORD_MSG_CHAR_LIMIT = 2000
