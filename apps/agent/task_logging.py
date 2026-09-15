"""Shared logging for completed asyncio tasks."""

import asyncio
import logging


def log_task_failure(task: asyncio.Task, logger: logging.Logger, message: str) -> None:
    if task.cancelled():
        return
    exception = task.exception()
    if exception is None:
        return
    logger.error(message, exc_info=exception)
