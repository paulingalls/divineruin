"""Real SpeechHandles in terminal states, for tests that stub ``AgentSession.generate_reply``.

``generate_reply`` returns a handle synchronously and never raises through the await —
a generation failure surfaces only as ``handle.exception()`` — so a stub that answers with
an ``AsyncMock`` certifies nothing about the code reading that handle (constraint 9).
"""

from livekit.agents.voice import SpeechHandle


def completed_handle(error: BaseException | None = None) -> SpeechHandle:
    """A handle already done, carrying ``error`` as the generation failure (None = success)."""
    handle = SpeechHandle.create()
    handle._mark_done(error)
    return handle
