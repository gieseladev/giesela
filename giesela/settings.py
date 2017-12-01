import pickle

from giesela.config import static_config


class MetaSettings(type):

    def __getitem__(self, key):
        return Settings.get_setting(key)

    def __setitem__(self, key, value):
        return Settings.set_setting(key, value)


class Settings(metaclass=MetaSettings):
    settings = {}

    def load_settings():
        Settings.settings = pickle.load(open(static_config.settings_file, "r+b"))

    def save_settings():
        pickle.dump(Settings.settings, open(static_config.settings_file, "w+b"))

    def get_setting(key, **kwargs):
        try:
            Settings.load_settings()
        except FileNotFoundError:
            pass

        if key in Settings.settings:
            return Settings.settings[key]
        else:
            if "default" in kwargs:
                return kwargs["default"]

            raise IndexError

    def set_setting(key, value):
        Settings.settings[key] = value
        Settings.save_settings()

    def remove_setting(key):
        if key in Settings.settings:
            Settings.settings.pop(key)
            Settings.save_settings()
        else:
            raise IndexError
