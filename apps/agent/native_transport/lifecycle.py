import asyncio
import signal
from collections.abc import Callable, Coroutine
from typing import Any


async def run_cancellable(run: Callable[[], Coroutine[Any, Any, None]]) -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(run())
    for kind in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(kind, task.cancel)
    try:
        await task
    finally:
        for kind in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(kind)
