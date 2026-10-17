from typing import Protocol


class Notifier(Protocol):
    async def notify(self, deviation_id: str, text: str) -> bool: ...
