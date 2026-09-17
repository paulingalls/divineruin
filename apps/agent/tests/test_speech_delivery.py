"""Source ownership checks for shared speech delivery."""

import ast
from pathlib import Path


def _expression_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name | ast.Attribute):
        return ast.unparse(node)
    return None


def _reply_handles(tree: ast.AST) -> set[str]:
    """Expressions bound to a ``generate_reply`` call — the handle a delivery would read."""
    handles: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.NamedExpr):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "generate_reply"):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        handles.update(key for target in targets if (key := _expression_key(target)) is not None)
    return handles


def _delivery_owners(sources: dict[str, str]) -> tuple[set[str], set[str]]:
    """Modules that await a reply handle, and modules that read its ``exception()``.

    Resolved on the AST rather than the text the delivery happens to be written in: a
    second copy that names its handle ``reply`` is the same duplication as one that
    names it ``handle``, and a grep for ``await handle`` would miss it.
    """
    awaiters: set[str] = set()
    readers: set[str] = set()
    for name, source in sources.items():
        tree = ast.parse(source)
        handles = _reply_handles(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Await):
                directly_awaits_reply = any(
                    isinstance(child, ast.Call) and getattr(child.func, "attr", None) == "generate_reply"
                    for child in ast.walk(node.value)
                )
                if directly_awaits_reply or _expression_key(node.value) in handles:
                    awaiters.add(name)
            func = node.func if isinstance(node, ast.Call) else None
            if isinstance(func, ast.Attribute) and func.attr == "exception" and _expression_key(func.value) in handles:
                readers.add(name)
    return awaiters, readers


def test_delivery_ownership_detects_bare_await_without_a_bound_handle():
    awaiters, readers = _delivery_owners(
        {
            "bare.py": "async def deliver(session):\n    await session.generate_reply(instructions='hi')\n",
            "attribute.py": (
                "async def deliver(self):\n"
                "    self._reply = self.session.generate_reply(instructions='hi')\n"
                "    await self._reply\n"
                "    self._reply.exception()\n"
            ),
            "helper.py": (
                "async def deliver(session, finish):\n    await finish(session.generate_reply(instructions='hi'))\n"
            ),
        }
    )

    assert awaiters == {"bare.py", "attribute.py", "helper.py"}
    assert readers == {"attribute.py"}


def test_generate_reply_delivery_has_one_implementation():
    agent_dir = Path(__file__).parents[1]
    sources = {path.name: path.read_text() for path in agent_dir.glob("*.py")}

    awaiters, readers = _delivery_owners(sources)
    assert awaiters == {"speech_delivery.py"}
    assert readers == {"speech_delivery.py"}

    delivery_source = sources["speech_delivery.py"]
    assert "GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS = frozenset(" in delivery_source
    for caller in ("agent.py", "background_process.py", "onboarding_background.py"):
        assert "from speech_delivery import deliver_speech" in sources[caller]
    for message in (
        "AgentSession isn't running",
        "AgentSession is closing, cannot use generate_reply()",
    ):
        assert delivery_source.count(message) == 1
        assert sum(source.count(message) for source in sources.values()) == 1
