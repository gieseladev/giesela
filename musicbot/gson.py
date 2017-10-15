import json

from musicbot.lib.serialisable import Serialisable

encodable = ("", )


class GSONEncoder(json.JSONEncoder):

    def default(self, o):
        if isinstance(o, Serialisable):
            ser_o = o.to_dict()

            return ***REMOVED***
                "name": o.__name__,
                "data": ser_o
            ***REMOVED***

        return super().default(o)
