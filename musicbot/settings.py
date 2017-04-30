import pickle


class Settings:
    settings = ***REMOVED******REMOVED***

    def load_settings():
        Settings.settings = pickle.load(open("config/settings.bin", "rb"))

    def save_settings():
        pickle.dump(Settings.settings, open("config/settings.bin", "wb+"))

    def get_setting(key, default=None):
        Settings.load_settings()
        if key in Settings.settings:
            return Settings.settings[key]
        else:
            return default

    def set_setting(key, value):
        Settings.settings[key] = value
        Settings.save_settings()
