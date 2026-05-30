"""Shared constants for the async-worker subsystem.

Lives in its own module so claim helpers can import POLL_INTERVAL without
pulling in `async_worker` (which imports them — circular).
"""

from __future__ import annotations

POLL_INTERVAL = 300  # 5 minutes — main worker loop sleep between ticks.
