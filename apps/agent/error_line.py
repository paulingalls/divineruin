"""Privacy-safe failure observation; existing logging and termination remain in charge."""

import asyncio
import json
import logging
import re
import sys
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal

Service = Literal["agent", "worker"]
_service: Service = "agent"
_installed = False
_MARK = "_divineruin_error_reported"
_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.]*$")


def report(service: Service, boundary: str, error: BaseException, tb: TracebackType | None = None) -> None:
    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
        return
    chain = []
    current: BaseException | None = error
    while current is not None and all(current is not item for item in chain):
        chain.append(current)
        current = current.__cause__ or current.__context__
    seen = any(getattr(item, _MARK, False) for item in chain)
    for item in chain:
        setattr(item, _MARK, True)
    if seen:
        return
    frames = []
    tb = tb or error.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(f"{code.co_filename}:{code.co_name}:{tb.tb_lineno}")
        tb = tb.tb_next
    if not frames:
        frame = sys._getframe()
        while frame is not None:
            frames.append(f"{frame.f_code.co_filename}:{frame.f_code.co_name}:{frame.f_lineno}")
            frame = frame.f_back
        frames.reverse()
    name = type(error).__qualname__
    message = boundary + (f": {name}" if _IDENTIFIER.fullmatch(name) else "")
    sys.stderr.write(
        json.dumps(
            {
                "service": service,
                "time": datetime.now(UTC).isoformat(),
                "message": message,
                "stack": "\n".join(frames[-50:]),
            }
        )
        + "\n"
    )


class _Observer(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # IPC replay has exc_text but no exception; only the originating process reports.
        if record.exc_info and record.exc_info[1] is not None:
            service = "worker" if record.name.startswith("divineruin.async_worker") else _service
            report(service, record.name, record.exc_info[1], record.exc_info[2])


def install(service: Service) -> None:
    global _installed, _service
    _service = service
    if _installed:
        return
    _installed = True
    observer = _Observer()
    for name in ("divineruin", "livekit.agents", "asyncio"):
        logging.getLogger(name).addHandler(observer)
    previous = sys.excepthook

    def fatal(kind: type[BaseException], error: BaseException, tb: TracebackType | None) -> None:
        report(_service, "Agent fatal" if _service == "agent" else "Worker fatal", error, tb)
        previous(kind, error, tb)

    sys.excepthook = fatal
