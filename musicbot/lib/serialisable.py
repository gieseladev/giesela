class WebSerialisable:
    """
        An object which can be serialised in order to be sent over Websockets
    """

    def to_web_dict(self):
        return self.__dict__


class Serialisable:
    """
        An object that can be serialised to a dict from which it can be recreated.
    """

    @classmethod
    def from_dict(cls, data):
        """
            Recreate the object using the data provided by the to_dict method
        """

        self = cls.__new__(cls)

        self.__dict__ = data

        return self

    def to_dict(self):
        """
            Serialise the object into a dict so it can be saved using JSON
        """

        return self.__dict__


class AsyncSerialisable(Serialisable):

    @classmethod
    async def from_dict(cls, data):
        super().from_dict(data)

    async def to_dict(self):
        return super().to_dict()
