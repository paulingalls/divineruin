"""Authored patron passives shared by skill resolution and world queries."""

from _gods_content import load_gods
from patron_synergy import has_engine_synergy

UNBOUND_ALONE_BONUS = 1
NATURES_PULSE_SKILLS = frozenset({"perception", "survival"})
KNOWLEDGE_SKILLS = frozenset({"arcana", "history", "investigation", "nature", "religion"})
SYRATH_SHADOW_VEIL = "syrath_shadow_veil"
VEYTHAR_INSIGHT = "veythar_lorekeepers_insight"


def veythar_gift(player: dict) -> dict | None:
    if (player.get("divine_favor") or {}).get("patron") != "veythar":
        return None
    gift = next(row["layer_1_gift"] for row in load_gods() if row["god_id"] == "veythar")
    if gift["id"] != VEYTHAR_INSIGHT:
        raise ValueError("Veythar's gift id does not match its activation")
    return gift if gift["status"] == "active" else None


def syrath_gift(player: dict) -> dict | None:
    if (player.get("divine_favor") or {}).get("patron") != "syrath":
        return None
    gift = next(row["layer_1_gift"] for row in load_gods() if row["god_id"] == "syrath")
    if gift["id"] != SYRATH_SHADOW_VEIL:
        raise ValueError("Syrath's gift id does not match its activation")
    return gift if gift["status"] == "active" else None


def thyra_gift(favor: dict) -> dict | None:
    if favor.get("patron") != "thyra":
        return None
    gift = next(row["layer_1_gift"] for row in load_gods() if row["god_id"] == "thyra")
    return gift if gift["status"] == "active" else None


def skill_gift(
    player: dict, skill: str, *, ally_present: int, natural_terrain: bool, first_stay: bool = False
) -> tuple[int, bool, str | None]:
    favor = player.get("divine_favor") or {}
    if not ally_present and favor.get("patron") in (None, "none"):
        return UNBOUND_ALONE_BONUS, False, None
    if ally_present and favor.get("patron") == "aelora":
        gift = next(row["layer_1_gift"] for row in load_gods() if row["god_id"] == "aelora")
        if gift["mechanics"]["requires"] != "ally_present":
            raise ValueError(f"Aelora's gift requires {gift['mechanics']['requires']!r}, not a present ally")
        if gift["status"] == "active":
            adjustment = int(ally_present >= 2 and has_engine_synergy(player, "aelora_common_bond"))
            return gift["mechanics"]["amount"] + adjustment, False, gift["name"]
    if natural_terrain and skill in NATURES_PULSE_SKILLS and (gift := thyra_gift(favor)):
        return 0, True, gift["name"]
    if first_stay and favor.get("patron") == "nythera":
        if skill in {"investigation", "perception"} and has_engine_synergy(player, "nythera_uncharted_senses"):
            return 3, False, "Uncharted Senses"
        if skill == "animal_handling" and has_engine_synergy(player, "nythera_uncharted_handling"):
            return 1, False, "Uncharted Handling"
    return 0, False, None
