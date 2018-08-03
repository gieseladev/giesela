import pickle

from giesela.config import static_config


class MetaSettings(type):

    def __getitem__(self, key):
        return Settings.get_setting(key)

    def __setitem__(self, key, value):
        return Settings.set_setting(key, value)


def save_settings():
    pickle.dump(Settings.settings, open(static_config.settings_file, "w+b"))


def load_settings():
    Settings.settings = pickle.load(open(static_config.settings_file, "r+b"))


class Settings(metaclass=MetaSettings):
    settings = {}

    @staticmethod
    def get_setting(key, **kwargs):
        try:
            load_settings()
        except FileNotFoundError:
            pass

        if key in Settings.settings:
            return Settings.settings[key]
        else:
            if "default" in kwargs:
                return kwargs["default"]

            raise IndexError

    @staticmethod
    def set_setting(key, value):
        Settings.settings[key] = value
        save_settings()

    @staticmethod
    def remove_setting(key):
        if key in Settings.settings:
            Settings.settings.pop(key)
            save_settings()
        else:
            raise IndexError
