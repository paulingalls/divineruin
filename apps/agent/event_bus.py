"""In-process event bus for connecting tools to the background process."""

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("divineruin.event_bus")


@dataclass
class GameEvent:
    event_type: str
    payload: dict
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Async queue-based pub/sub. Bounded with drop-oldest overflow."""

    def __init__(self, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[GameEvent] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, event: GameEvent) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            logger.warning("Event bus overflow — dropped oldest event")
        self._queue.put_nowait(event)

    async def get(self, timeout: float = 30.0) -> GameEvent | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def drain(self) -> list[GameEvent]:
        events: list[GameEvent] = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    @property
    def qsize(self) -> int:
        return self._queue.qsize()
