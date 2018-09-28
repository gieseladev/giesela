from typing import Any

__all__ = ["ObjectChain"]


class ObjectChain:
    def __init__(self, *targets: Any) -> None:
        self._targets = list(targets)

    def __getattr__(self, item: str):
        _return_none = False

        for target in self._targets:
            try:
                value = getattr(target, item)
            except AttributeError:
                continue
            else:
                if value is not None:
                    return value
                else:
                    _return_none = True

        if not _return_none:
            raise AttributeError(f"{self.targets} don't have {item}")
