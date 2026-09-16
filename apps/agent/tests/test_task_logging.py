"""Tests for completed-task failure logging."""

import asyncio
import logging

import pytest

from task_logging import log_task_failure

logger = logging.getLogger("test.task_logging")


async def _raise_failure() -> None:
    raise RuntimeError("task broke")


@pytest.mark.asyncio
async def test_logs_failure_once_with_original_traceback(caplog):
    task = asyncio.create_task(_raise_failure())
    with pytest.raises(RuntimeError, match="task broke") as raised:
        await task

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_task_failure(task, logger, "Task failed")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "Task failed"
    assert record.exc_info is not None
    assert record.exc_info[1] is raised.value
    formatted = logging.Formatter().format(record)
    assert "RuntimeError" in formatted
    assert "task broke" in formatted


@pytest.mark.asyncio
async def test_cancelled_task_logs_nothing(caplog):
    task = asyncio.create_task(asyncio.Event().wait())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_task_failure(task, logger, "Task failed")

    assert caplog.records == []


@pytest.mark.asyncio
async def test_successful_task_logs_nothing(caplog):
    task = asyncio.create_task(asyncio.sleep(0))
    await task

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_task_failure(task, logger, "Task failed")

    assert caplog.records == []
