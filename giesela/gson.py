import json

from giesela.lib.serialisable import Serialisable

encodable = ("", )


class GSONEncoder(json.JSONEncoder):

    def default(self, o):
        if isinstance(o, Serialisable):
            ser_o = o.to_dict()

            return {
                "name": o.__name__,
                "data": ser_o
            }

        return super().default(o)
