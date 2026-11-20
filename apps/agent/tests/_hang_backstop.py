"""Hard backstop for a hang that swallows pytest-timeout's one-shot SIGALRM.

When the alarm lands inside an asyncio callback or a background task step,
asyncio logs and drops the Failed it raises, and pytest-timeout never re-arms,
so a hang that keeps the loop busy stays unbounded. faulthandler's watchdog
thread runs outside the loop: at twice the bound it dumps every thread's stack
and exits the process. Under xdist only the worker dies; the controller reports
the test as crashed and the rest still run.
"""

import faulthandler
import os

import pytest

_stderr_fd: int | None = None


def pytest_configure() -> None:
    global _stderr_fd
    # The real stderr, duplicated before capture swallows fd 2, so the dump is seen.
    _stderr_fd = os.dup(2)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item):
    bound = float(item.config.getini("timeout") or 0)
    if bound > 0 and _stderr_fd is not None:
        faulthandler.dump_traceback_later(2 * bound, exit=True, file=_stderr_fd)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()
