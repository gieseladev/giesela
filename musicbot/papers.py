import os
import shutil
import traceback

import configparser

from .exceptions import HelpfulError


class Papers:

    def __init__(self, config_file):
        self.config_file = config_file
        self.config = configparser.ConfigParser(interpolation=None)

        self.config.read(config_file, encoding='utf-8')

    def get_paper(self, paper_name):
        for section in self.config.sections():
            if section == paper_name:
                return PaperInfo(self.config.get(section, "name"), self.config.get(section, "language"), self.config.get(section, "cover"), self.config.get(section, "url"))

        return None


class PaperInfo:

    def __init__(self, name, language, cover, url):
        self.name = name
        self.language = language
        self.cover = cover
        self.url = url
