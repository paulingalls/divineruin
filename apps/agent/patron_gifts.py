"""Authored patron passives shared by skill resolution and world queries."""

from _gods_content import load_gods

NATURES_PULSE_SKILLS = frozenset({"perception", "survival"})
KNOWLEDGE_SKILLS = frozenset({"arcana", "history", "investigation", "nature", "religion"})
VEYTHAR_INSIGHT = "veythar_lorekeepers_insight"


def veythar_gift(player: dict) -> dict | None:
    if (player.get("divine_favor") or {}).get("patron") != "veythar":
        return None
    gift = next(row["layer_1_gift"] for row in load_gods() if row["god_id"] == "veythar")
    if gift["id"] != VEYTHAR_INSIGHT:
        raise ValueError("Veythar's gift id does not match its activation")
    return gift if gift["status"] == "active" else None


def thyra_gift(favor: dict) -> dict | None:
    if favor.get("patron") != "thyra":
        return None
    gift = next(row["layer_1_gift"] for row in load_gods() if row["god_id"] == "thyra")
    return gift if gift["status"] == "active" else None


def skill_gift(player: dict, skill: str, *, ally_present: bool, natural_terrain: bool) -> tuple[int, bool, str | None]:
    favor = player.get("divine_favor") or {}
    if ally_present and favor.get("patron") == "aelora":
        gift = next(row["layer_1_gift"] for row in load_gods() if row["god_id"] == "aelora")
        if gift["mechanics"]["requires"] != "ally_present":
            raise ValueError(f"Aelora's gift requires {gift['mechanics']['requires']!r}, not a present ally")
        if gift["status"] == "active":
            return gift["mechanics"]["amount"], False, gift["name"]
    if natural_terrain and skill in NATURES_PULSE_SKILLS and (gift := thyra_gift(favor)):
        return 0, True, gift["name"]
    return 0, False, None
