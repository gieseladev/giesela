import configparser
import os
import shutil
import traceback

from .exceptions import HelpfulError
from random import choice


class Radios:

    def __init__(self, config_file):
        self.config_file = config_file
        self.config = configparser.ConfigParser(interpolation=None)

        self.config.read(config_file, encoding='utf-8')

    def get_random_station(self):
        section = choice(self.config.sections())
        return StationInfo(self.config.get(section, "name"), self.config.get(section, "language"), self.config.get(section, "cover"), self.config.get(section, "url"))

    def get_station(self, station_name):
        for section in self.config.sections():
            if section == station_name or self.config.get(section, "name").lower() == station_name:
                return StationInfo(self.config.get(section, "name"), self.config.get(section, "language"), self.config.get(section, "cover"), self.config.get(section, "url"))

        return None

    def get_all_stations(self):
        return_list = []

        for section in self.config.sections():
            return_list.append(StationInfo(self.config.get(section, "name"), self.config.get(section, "language"), self.config.get(section, "cover"), self.config.get(section, "url")))

        return return_list

class StationInfo:

    def __init__(self, name, language, cover, url):
        self.name = name
        self.language = language
        self.cover = cover
        self.url = url
