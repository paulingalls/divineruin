"""M4.4 resurrection (story-003) — core return-from-death loop.

Death always returns the character (spec §Mortaen's Domain); the cost escalates with the permanent
death count (story-001's death_cost). This module turns a DeathCost into concrete persistence deltas
(apply_death_cost), resolves the nearest safe anchor (resolve_resurrection_anchor, 4-tier), and
orchestrates the whole death->cost->anchor->revive flow (trigger_character_death). Pure helpers stay
free of IO; persistence lives in db_mutations_resurrection. Hollowed-death + Temporary Hollowed are
story-007.
"""

import conditions as conditions_mod
import creation_deities
import db_content_queries
import db_mutations_conditions
import db_mutations_death
import db_mutations_resurrection
from catalog_parse import ATTRIBUTE_KEYS
from creation_classes import CLASSES
from death_cost import DeathCost, determine_death_cost

# Canonical attribute order doubles as the deterministic tie-break for the lowest/highest selectors.
_ATTR_ORDER = ATTRIBUTE_KEYS


def lowest_attribute(attributes: dict) -> str:
    """The attribute with the lowest score; ties break by canonical order (min keeps first seen)."""
    present = [a for a in _ATTR_ORDER if a in attributes]
    if not present:
        raise ValueError("attributes dict has no recognized attribute keys")
    return min(present, key=lambda a: attributes[a])


def highest_attribute(attributes: dict) -> str:
    """The attribute with the highest score; ties break by canonical order (max keeps first seen)."""
    present = [a for a in _ATTR_ORDER if a in attributes]
    if not present:
        raise ValueError("attributes dict has no recognized attribute keys")
    return max(present, key=lambda a: attributes[a])


def _primary_attribute(player: dict) -> str:
    """The character's class primary attribute (creation_classes), or the highest score as a
    defensible fallback when the class is missing/unknown — resurrection must not crash on it."""
    cls = CLASSES.get(player.get("class", ""))
    if cls is not None:
        return cls.primary_attribute
    return highest_attribute(player["attributes"])


_STARTER_ZONE_FALLBACK = "accord_market_square"


def resolve_resurrection_anchor(
    death_location: str,
    locations: dict[str, dict],
    player: dict,
    *,
    combat_cleared: bool,
) -> str:
    """Pick the resurrection anchor by the spec's 4-tier hierarchy (§Resurrection Location).

    1. Cleared battlefield: the death site, if combat is over AND the area is no longer hostile
       (danger_level <= 1).
    2. Nearest allied camp/settlement: a same-region location with a settlement_tier. No map
       coordinates exist, so "nearest" = same region, preferring safer (lower danger_level) then a
       stable id sort.
    3. Last-rested settlement: player.last_rested_settlement_id. NOTE forward-seam — no rest tool
       writes this yet (apply_long_rest has no production caller), so tier 3 is dormant at runtime
       and the resolver falls through to tier 4 until a rest caller ships.
    4. Starter zone: a location tagged "starting_area" (fallback accord_market_square).
    """
    death = locations.get(death_location, {})
    if combat_cleared and death.get("danger_level", 99) <= 1:
        return death_location

    region = death.get("region")
    settlements = (
        [loc_id for loc_id, loc in locations.items() if loc.get("settlement_tier") and loc.get("region") == region]
        if region is not None
        else []
    )
    if settlements:
        return min(settlements, key=lambda i: (locations[i].get("danger_level", 99), i))

    last_rested = player.get("last_rested_settlement_id")
    if last_rested and last_rested in locations:
        return last_rested

    starter = next((i for i, loc in locations.items() if "starting_area" in loc.get("tags", [])), None)
    return starter or _STARTER_ZONE_FALLBACK


def apply_death_cost(player: dict, cost: DeathCost) -> dict:
    """Resolve a DeathCost's selectors against the character into concrete persistence deltas.

    Returns {attribute, attribute_delta, maxhp_override_delta}: the attribute to penalize (or None),
    the signed attribute change, and the signed maxHP-override change (negative, accumulates). The DB
    layer (db_mutations_resurrection) applies these; keeping the resolution pure makes it unit-testable.
    """
    attrs = player["attributes"]
    target = cost.attribute_target
    if target == "none":
        attribute = None
    elif target == "lowest":
        attribute = lowest_attribute(attrs)
    elif target == "primary":
        attribute = _primary_attribute(player)
    elif target == "highest":
        attribute = highest_attribute(attrs)
    else:
        raise ValueError(f"unknown attribute_target: {target!r}")

    return {
        "attribute": attribute,
        "attribute_delta": -cost.attribute_penalty if attribute is not None else 0,
        "maxhp_override_delta": -cost.maxhp_penalty_total,
    }


async def trigger_character_death(
    player: dict,
    locations: dict[str, dict],
    *,
    combat_cleared: bool,
    anchor: str | None = None,
    waive_cost: bool = False,
    death_mutations=db_mutations_death,
    mutations=db_mutations_resurrection,
    conditions_mutations=db_mutations_conditions,
    conn=None,
) -> dict:
    """Orchestrate the full death->cost->anchor->revive loop and return a Mortaen-narration context.

    Reads the permanent death count (story-001), computes + records the escalating cost, applies the
    attribute/maxHP penalties, resolves the nearest anchor (4-tier), and revives the character there —
    HP clamped to the post-override effective max so a death-7+ character isn't healed above their
    reduced ceiling. ``player`` is the players.data dict; writes thread ``conn`` for tx participation
    (combat-end calls this inside its defeat tx). Hollowed-death handling is story-007.

    ``anchor`` (story-004): when set, skip resolution and revive at the supplied anchor — lets a
    party wipe share one anchor. ``waive_cost`` (story-004): a free death (a Mortaen patron's
    first-ever) — the count is read for the return context but NOT incremented or recorded, and no
    attribute/maxHP cost is applied; the character is still revived.

    Hollowed death (story-007): when the dying character carries a Hollowed condition (any stage),
    the death permanently marks them Hollow-killed (a later divine_revivify is refused) and clears
    the Hollowed condition — corruption doesn't follow you past Mortaen's threshold. Story-008's
    combat-engine path reaches this same branch when the Temporary Hollowed echo is destroyed.
    """
    player_id = player["player_id"]
    level = player.get("level", 1)

    history = await death_mutations.read_death_history(player_id, conn=conn)
    deltas = {"attribute": None, "attribute_delta": 0, "maxhp_override_delta": 0}
    if waive_cost:
        death_count = history["count"]  # unchanged — a waived death is not counted
        tier = "waived"
    else:
        death_count = history["count"] + 1
        cost = determine_death_cost(death_count, level)
        await death_mutations.record_death(player_id, cost, conn=conn)
        tier = cost.tier
        deltas = apply_death_cost(player, cost)
        if deltas["attribute"] is not None and deltas["attribute_delta"]:
            await mutations.apply_attribute_penalty(
                player_id, deltas["attribute"], deltas["attribute_delta"], conn=conn
            )
        if deltas["maxhp_override_delta"]:
            await mutations.apply_maxhp_override_delta(player_id, deltas["maxhp_override_delta"], conn=conn)

    if anchor is None:
        anchor = resolve_resurrection_anchor(
            player.get("location_id", ""), locations, player, combat_cleared=combat_cleared
        )

    base_max = player.get("hp", {}).get("max", 1)
    effective_max = max(1, base_max + player.get("maxhp_override", 0) + deltas["maxhp_override_delta"])
    revive_hp = effective_max  # Mortaen's return is a full recovery (time passes); clamped to the new max.
    await mutations.revive_player(player_id, anchor, revive_hp, conn=conn)

    # Hollowed death (story-007): mark Hollow-killed + clear the Hollowed condition (purged past
    # Mortaen's threshold). combat_end persists the participant's conditions BEFORE this runs, so the
    # cleared list is the authoritative post-death store.
    player_conditions = player.get("conditions", [])
    hollow_killed = any(c.get("type") == "hollowed" for c in player_conditions)
    if hollow_killed:
        await mutations.set_hollow_killed(player_id, conn=conn)
        await conditions_mutations.save_player_conditions(
            player_id, conditions_mod.remove_condition(player_conditions, "hollowed"), conn=conn
        )

    return {
        "death_count": death_count,
        "tier": tier,
        "attribute": deltas["attribute"],
        "attribute_delta": deltas["attribute_delta"],
        "maxhp_override_delta": deltas["maxhp_override_delta"],
        "anchor": anchor,
        "revive_hp": revive_hp,
        "hollow_killed": hollow_killed,
        "hollowed_cleared": hollow_killed,
    }


async def resurrect_party_on_defeat(
    party: list[dict],
    *,
    combat_cleared: bool,
    conn=None,
    content_queries=db_content_queries,
    death_mutations=db_mutations_death,
    mutations=db_mutations_resurrection,
) -> list[dict]:
    """Party-wipe engine (story-004): each member's death is recorded + costed independently, and
    all members revive at ONE shared anchor (spec §Party wipe).

    The shared anchor is resolved once from the party's common death location. Anchor tiers 1/2/4
    are member-independent and tier-3 (last-rested) is dormant (no rest caller ships yet), so a
    single resolution IS the shared highest-priority anchor today; per-member tier-3 divergence is
    a future concern when a rest caller lands. A Mortaen patron's first-ever death is waived
    (creation_deities.patron_waives_first_death): not recorded, not counted, no cost — still revived.

    Forward-wired: combat is single-player, so prod feeds a 1-member party (resurrect_on_defeat
    delegates here); the multi-member path is exercised by tests until multiplayer combat lands.
    Threads ``conn`` so the whole party rides combat-end's defeat transaction.
    """
    if not party:
        return []

    locations = await content_queries.get_all_locations()
    shared_anchor = resolve_resurrection_anchor(
        party[0].get("location_id", ""), locations, party[0], combat_cleared=combat_cleared
    )

    contexts: list[dict] = []
    for member in party:
        patron = member.get("divine_favor", {}).get("patron", "none")
        prior_count = (await death_mutations.read_death_history(member["player_id"], conn=conn))["count"]
        waive = creation_deities.patron_waives_first_death(patron, prior_count)
        contexts.append(
            await trigger_character_death(
                member,
                locations,
                combat_cleared=combat_cleared,
                anchor=shared_anchor,
                waive_cost=waive,
                death_mutations=death_mutations,
                mutations=mutations,
                conn=conn,
            )
        )
    return contexts


async def resurrect_on_defeat(
    player: dict,
    *,
    combat_cleared: bool,
    conn=None,
    content_queries=db_content_queries,
    death_mutations=db_mutations_death,
    mutations=db_mutations_resurrection,
) -> dict:
    """combat_end defeat-path entry: the live single-player defeat path. Delegates to the party
    engine with a 1-member party so the single and multi-member paths share one implementation,
    and returns the single death context. Threads ``conn`` for the defeat transaction.
    """
    contexts = await resurrect_party_on_defeat(
        [player],
        combat_cleared=combat_cleared,
        conn=conn,
        content_queries=content_queries,
        death_mutations=death_mutations,
        mutations=mutations,
    )
    return contexts[0]
