"""Authored autonomy awards and high-water tiers for the Unbound."""

import functools
import json
from dataclasses import dataclass
from pathlib import Path

from favor_rules import apply_favor_delta
from patron_favor import tier_index

_UNBOUND_JSON_PATH = Path(__file__).resolve().parents[2] / "content" / "unbound.json"
_KINDS = {"won_alone", "succeeded_alone", "channeled_raw"}


@functools.cache
def load_unbound() -> tuple[dict[str, int], tuple[str, ...]]:
    data = json.loads(_UNBOUND_JSON_PATH.read_text())
    rows = data.get("autonomy_actions")
    if not isinstance(rows, list) or len(rows) != len(_KINDS):
        raise ValueError("autonomy_actions: expected all three action kinds")
    actions = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("action") not in _KINDS:
            raise ValueError("autonomy_actions.action: unknown kind")
        kind, amount = row["action"], row.get("amount")
        if kind in actions:
            raise ValueError(f"autonomy_actions.action: duplicate {kind}")
        if type(amount) is not int or amount <= 0:
            raise ValueError(f"autonomy_actions.{kind}.amount: expected positive integer")
        actions[kind] = amount
    tiers = data.get("tiers")
    if (
        not isinstance(tiers, list)
        or len(tiers) != 3
        or any(not isinstance(t, str) or not t.strip() for t in tiers)
        or len(set(tiers)) != 3
    ):
        raise ValueError("tiers: expected three distinct nonblank names")
    return actions, tuple(tiers)


@dataclass(frozen=True)
class AutonomyGrant:
    previous_level: int
    new_level: int
    previous_tier: str
    new_tier: str
    reached_tier: str | None


def judge_autonomy(deeds: dict, stored: dict | None) -> tuple[dict, AutonomyGrant] | None:
    actions, tiers = load_unbound()
    amount = sum(amount for kind, amount in actions.items() if deeds.get(kind) == "pending")
    state = stored if stored is not None else {"level": 0, "max": 100, "tier": tiers[0]}
    level, maximum, previous_tier = state["level"], state.get("max", 100), state["tier"]
    new_level = apply_favor_delta(level, maximum, amount)
    if previous_tier not in tiers:
        raise ValueError(f"unbound_autonomy.tier: unknown tier {previous_tier!r}")
    if not amount:
        return None
    previous_index = tiers.index(previous_tier)
    new_index = max(previous_index, tier_index(new_level, maximum))
    new_tier = tiers[new_index]
    return (
        dict(state, level=new_level, max=maximum, tier=new_tier),
        AutonomyGrant(level, new_level, previous_tier, new_tier, new_tier if new_index > previous_index else None),
    )
