from .base import Notifier
from .console import ConsoleNotifier

__all__ = ["Notifier", "ConsoleNotifier", "get_notifier"]


def get_notifier(settings=None) -> Notifier:
    from .. import db
    settings = settings if settings is not None else db.get_settings()
    mode = db.setting(settings, "NOTIFIER")
    if mode != "console":
        raise ValueError("Only NOTIFIER=console is enabled; Photon access and API are not verified")
    return ConsoleNotifier()
