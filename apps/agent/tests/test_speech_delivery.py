"""Source ownership checks for shared speech delivery."""

import re
from pathlib import Path


def test_generate_reply_delivery_has_one_implementation():
    agent_dir = Path(__file__).parents[1]
    sources = {path.name: path.read_text() for path in agent_dir.glob("*.py")}

    await_owners = {name for name, source in sources.items() if re.search(r"(?m)^\s+await handle\s*$", source)}
    exception_owners = {name for name, source in sources.items() if "handle.exception()" in source}
    assert await_owners == {"speech_delivery.py"}
    assert exception_owners == {"speech_delivery.py"}

    delivery_source = sources.get("speech_delivery.py", "")
    assert "GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS = frozenset(" in delivery_source
    for caller in ("agent.py", "background_process.py", "onboarding_background.py"):
        assert "from speech_delivery import deliver_speech" in sources[caller]
    for message in (
        "AgentSession isn't running",
        "AgentSession is closing, cannot use generate_reply()",
    ):
        assert delivery_source.count(message) == 1
        assert sum(source.count(message) for source in sources.values()) == 1
