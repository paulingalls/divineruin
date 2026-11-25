"""Passive patron gifts and tier abilities."""

from _gods_content import load_gods
from patron_favor import get_patron_tier

ORENTHEL_BEACON = "orenthel_beacon"
DAWNS_RESILIENCE = "orenthel_dawns_resilience"
TIDEWALKER = "nythera_tidewalker"
SCHOLARS_WARD = "veythar_scholars_ward"
WARRIORS_ENDURANCE = "kaelen_warriors_endurance"


def acknowledged_passive(player: dict, patron_id: str, ability_id: str) -> bool:
    favor = player.get("divine_favor")
    if favor is None or favor.get("patron") != patron_id or get_patron_tier(favor) is None:
        return False
    patron = next(god for god in load_gods() if god["god_id"] == patron_id)
    ability = patron["layer_3_tier_abilities"]["acknowledged"]
    return (
        ability["id"] == ability_id
        and ability["status"] == "active"
        and ability["resolution"] == "engine"
        and ability["implementation_id"] == ability_id
        and ability["recharge"] == "always"
    )


def orenthel_beacon(player: dict) -> bool:
    return acknowledged_passive(player, "orenthel", ORENTHEL_BEACON)


def dawns_resilience(player: dict) -> dict | None:
    if (player.get("divine_favor") or {}).get("patron") != "orenthel":
        return None
    patron = next(god for god in load_gods() if god["god_id"] == "orenthel")
    gift = patron["layer_1_gift"]
    if (
        gift["id"] == DAWNS_RESILIENCE
        and gift["status"] == "active"
        and gift.get("resolution") == "engine"
        and gift.get("implementation_id") == DAWNS_RESILIENCE
    ):
        return gift
    return None


def scholars_ward(player: dict) -> bool:
    return acknowledged_passive(player, "veythar", SCHOLARS_WARD)


def tidewalker(player: dict) -> bool:
    return acknowledged_passive(player, "nythera", TIDEWALKER)


def warriors_endurance(player: dict) -> int:
    return 5 if acknowledged_passive(player, "kaelen", WARRIORS_ENDURANCE) else 0


def effective_max_hp(player: dict, base_max: int, *, override_delta: int = 0) -> int:
    return max(1, base_max + player.get("maxhp_override", 0) + override_delta + warriors_endurance(player))


def effective_hp(player: dict) -> dict:
    """Project the stored base pool without changing the player row."""
    hp = dict(player["hp"])
    if "max" in hp:
        hp["max"] = effective_max_hp(player, hp["max"])
        if "current" in hp:
            hp["current"] = min(hp["current"], hp["max"])
    return hp
