import logging

log = logging.getLogger(__name__)


class ConsoleNotifier:
    """Local demo notification; does not imply a supervisor received an alert."""

    async def notify(self, deviation_id: str, text: str) -> bool:
        log.info("Deviation %s: %s", deviation_id, " ".join(text.split()))
        return True
