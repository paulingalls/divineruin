"""Shared Focus/Stamina pool gate for ability/spell/ward costs.

The "read a player's resource pool → fail loud if it's missing or insufficient →
return the post-deduct value" block was duplicated across ability_tools,
veil_ward_tools, and spell_casting._gate_spell. gate_pool is the single pure
gate; callers collect the returned new values and make ONE
update_player_resources call (preserving each site's own deduct shape)."""

from livekit.agents.llm import ToolError


def gate_pool(player: dict, pool_name: str, cost: int, *, label: str) -> int | None:
    """Gate ``player``'s ``pool_name`` pool against ``cost``; return the post-deduct
    value, or ``None`` when ``cost`` is 0 (a free/cantrip action deducts nothing).

    Pure — no I/O. Fail-loud: raises ToolError when the pool is absent (no
    ``current`` key) or holds less than ``cost``. ``label`` names the action in the
    error message (e.g. a spell or ability name)."""
    pool = player.get(pool_name) or {}
    current = pool.get("current", 0)
    if cost > 0:
        title = pool_name.capitalize()  # "Focus" / "Stamina"
        if "current" not in pool:
            # Sentence-initial: capitalize the label's first char so a mid-sentence
            # label like "a Veil Ward" reads "A Veil Ward ..." (proper-noun labels
            # like "Bolt" are unchanged). The "Not enough" message below keeps the
            # label verbatim because it appears mid-sentence.
            sentence_label = label[:1].upper() + label[1:] if label else label
            raise ToolError(f"{sentence_label} costs {title} but you have no {title} pool.")
        if cost > current:
            raise ToolError(f"Not enough {title} for {label}: costs {cost}, you have {current}.")
        return current - cost
    return None
