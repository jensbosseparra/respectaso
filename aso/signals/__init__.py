# Signal collector registry.
# Each sub-package registers itself here so the management command
# can discover and run collectors by name.

_REGISTRY: dict[str, type] = {}


def register(name: str):
    """Class decorator that registers a collector under *name*."""
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_collector(name: str):
    """Return the collector class for *name*, or raise KeyError."""
    return _REGISTRY[name]


def available_collectors() -> list[str]:
    return sorted(_REGISTRY.keys())
