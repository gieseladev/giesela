class GieselaSignal(Exception):
    pass


class ExitSignal(GieselaSignal):
    pass


class RestartSignal(ExitSignal):
    pass


class TerminateSignal(ExitSignal):
    pass
