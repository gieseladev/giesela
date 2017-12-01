import configparser
import json

from giesela.exceptions import HelpfulError


class RandomSets:

    def __init__(self, file_location):
        self.random_file = file_location
        self.update_sets()

    def update_sets(self):
        random_sets = configparser.ConfigParser()

        if not random_sets.read(self.random_file, encoding="utf-8"):
            print("[Random Sets] Sets file not found")
            with open(self.random_file, "w+", encoding="utf-8") as f:
                pass

            self.update_sets()

        self.random_sets = configparser.ConfigParser(interpolation=None)
        self.random_sets.read(self.random_file, encoding="utf-8")

    def save_sets(self):
        with open(self.random_file, "w", encoding="utf-8") as set_file:
            self.random_sets.write(set_file)

    def get_set(self, name):
        if self.random_sets.has_section(name):
            if self.random_sets.has_option(name, "items"):
                try:
                    sec = self.random_sets.get(name, "items")
                    return json.loads(sec)
                except:
                    return None
        return None

    def create_set(self, name, items):
        if self.random_sets.has_section(name):
            return False

        try:
            self.random_sets.add_section(str(name))
            self.random_sets.set(str(name), "items", str(json.dumps(items)))
            self.save_sets()
            self.update_sets()
            return True
        except:
            return False

    def remove_set(self, name):
        if not self.random_sets.has_section(name):
            return None

        try:
            self.random_sets.remove_section(str(name))
            self.save_sets()
            self.update_sets()
            return True
        except:
            return False

    def add_option(self, name, option):
        if not self.random_sets.has_section(name):
            return None

        try:
            existing_items = self.get_set(name)
            existing_items.append(option)
            self.random_sets.set(str(name), "items",
                                 str(json.dumps(existing_items)))
            self.save_sets()
            self.update_sets()
            return True
        except:
            return False

    def remove_option(self, name, option):
        if not self.random_sets.has_section(name):
            return None

        try:
            existing_items = self.get_set(name)
            existing_items.remove(option)
            self.random_sets.set(str(name), "items",
                                 str(json.dumps(existing_items)))
            self.save_sets()
            self.update_sets()
            return True
        except:
            return False

    def replace_options(self, name, new_options):
        if not self.random_sets.has_section(name):
            return None

        try:
            self.random_sets.set(str(name), "items",
                                 str(json.dumps(new_options)))
            self.save_sets()
            self.update_sets()
            return True
        except:
            return False

    def get_sets(self):
        sets = []
        for section in self.random_sets.sections():
            sec_name = section.replace("_", " ").title()
            sets.append((sec_name, self.get_set(section)))

        return sets
