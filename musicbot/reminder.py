import asyncio
import time
from datetime import datetime, timedelta
from threading import Thread


class Action:

    def __init__(self, channel=None, msg_content=None, source_url=None, source_location=None, entry=None, callback=None, playlist_name=None):
        self.send_message = False
        self.play_online_media = False
        self.play_local_media = False
        self.play_entry = False
        self.call_back = False
        self.play_playlist = False

        if callback is not None:
            self.call_back = True
            self.callback = callback

        if channel is not None:
            self.channel = channel
            if msg_content is not None:
                self.send_message = True
                self.msg_content = msg_content

            if entry is not None:
                self.play_entry = True
                self.entry = entry
                entry.get_ready_future()
            elif playlist_name is not None:
                self.play_playlist = True
                self.playlist_name = playlist_name
            elif source_url is not None:
                self.play_online_media = True
                self.source_url = source_url
            elif source_location is not None:
                self.play_local_media = True
                self.source_location = source_location

    async def act(self, musicbot):
        if self.send_message:
            await musicbot.safe_send_message(self.channel, self.msg_content)

        if self.call_back:
            await callback()

        if self.play_entry:
            pl = await musicbot.get_player(self.channel, create=True)
            await pl.playlist._add_entry_now(self.entry, pl)

        if self.play_playlist:
            pl = await musicbot.get_player(self.channel, create=True)
            await musicbot.cmd_playlist(self.channel, None, None, pl, ["load", self.playlist_name])

        if self.play_online_media:
            pl = await musicbot.get_player(self.channel, create=True)
            entry = await pl.playlist.get_entry(self.source_url)
            await pl.playlist._add_entry_now(entry, pl)


class Reminder:

    def __init__(self, name, expiry_date, action, repeat_every=None, repeat_end=None, description=""):
        self.name = name
        self.action = action
        self.description = description
        self.expiry_date = expiry_date
        self.repeat_every = repeat_every
        self.repeat_end = repeat_end

    def __repr__(self):
        return "Reminder(***REMOVED******REMOVED***, ***REMOVED******REMOVED***, ***REMOVED******REMOVED***, ***REMOVED******REMOVED***, ***REMOVED******REMOVED***)".format(repr(self.name), repr(self.expiry_date), repr(self.action), repr(self.repeat_every), repr(self.repeat_end))

    def on_expire(self, musicbot):
        asyncio.run_coroutine_threadsafe(self.action.act(musicbot), musicbot.loop)

        if self.repeat_every is not None:
            next_expiry_date = datetime.now() + self.repeat_every
            if self.repeat_end is None or self.repeat_end < next_expiry_date:
                self.expiry_date = next_expiry_date
                return False
        return True

    @property
    def is_due(self):
        return datetime.now() >= self.expiry_date

    @property
    def seconds_until(self):
        t_delta = max(.1, (self.expiry_date -
                           datetime.now()).total_seconds() - 1)
        return t_delta


class Calendar:

    def __init__(self, musicbot):
        self.musicbot = musicbot
        self.reminders = []
        self.run_loop = None
        self.running = False
        self.force_update = False
        self.stop_thread = False

    def create_reminder(self, name, expiry_date, action, repeat_every=None, repeat_end=None):
        self.reminders.append(
            Reminder(name, expiry_date, action, repeat_every, repeat_end))
        self.update()

    def remove_reminder(self, index):
        try:
            del self.reminders[index]
            self.update()
            return True
        except:
            return False

    def update(self):
        if len(self.reminders) > 0 and self.running == False:
            if self.run_loop is not None and not self.run_loop.is_alive():
                self.run_loop.join()

            self.run_loop = Thread(target=self.loop)
            self.run_loop.start()

        self.force_update = True

    def shutdown(self):
        self.stop_thread = True
        self.force_update = True

    def loop(self):
        try:
            self.running = True
            while len(self.reminders) > 0 and not self.stop_thread:
                lowest_delay = None
                delete_reminders = []
                for reminder in self.reminders:
                    if reminder.is_due:
                        if reminder.on_expire(self.musicbot):
                            delete_reminders.append(reminder)
                    if lowest_delay is None or reminder.seconds_until < lowest_delay:
                        lowest_delay = reminder.seconds_until

                for rem in delete_reminders:
                    self.remove_reminder(self.reminders.index(rem))

                #print("next check in: ***REMOVED******REMOVED*** seconds".format(lowest_delay))
                sleep_time = lowest_delay if lowest_delay is not None else 10
                while sleep_time > 0 and not self.force_update:
                    time.sleep(1)
                    sleep_time -= 1

                self.force_update = False

            self.running = False
            self.stop_thread = False
        except Exception as e:
            raise
