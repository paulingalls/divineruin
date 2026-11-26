"""Greater Restoration through registered exploration and combat commands."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from _spell_heal_fixtures import LOCATION, HealWalk
from sample_fixtures import published_payloads

import combat_spatial
import combat_structures
import db
import db_mutations
import db_mutations_conditions
import still_charm
from attribute_increases import recompute_pools

SPELL = "divine_greater_restoration"
OTHER = {"type": "exhausted", "stacks": 1, "duration": None}
HOLLOWED = {"type": "hollowed", "stage": 3, "wis_drained": 2, "source": "knight"}
CHARMED = {"type": "charmed", "stacks": 1, "duration": None, "source": "foe"}
PETRIFIED = {"type": "petrified", "stacks": 1, "duration": None}


@pytest.fixture
async def walk(reset_db_pool):
    async with HealWalk(await db.get_pool()) as healer:
        await healer.prepare(SPELL)
        yield healer


async def seed(walk, pid, *active, wisdom=10):
    row = await walk.read(pid)
    await walk.patch_row(pid, conditions=[*active, OTHER], attributes={**row["attributes"], "wisdom": wisdom})


async def declare(walk, target, choice="", *, error=False):
    declarations = [
        {"kind": "ability", "actor_id": walk.player, "action": SPELL, "targets": [target], "argument_type": choice}
    ]
    declarations.extend(
        {"kind": "defend", "actor_id": p.id, "reshape": []}
        for p in walk.fight_state.participants
        if p.id != walk.player and not p.is_structure and not any(c["type"] == "petrified" for c in p.conditions)
    )
    return await walk.command("declare_phase", {"declarations": declarations}, error=error)


async def resolve(walk):
    result = await walk.command("resolve_phase", {})
    return next(p["cast"] for p in result["packets"] if p["actor_id"] == walk.player)


def assert_receipt(packet, target, removed, restored):
    assert packet["target_id"] == target
    assert packet["condition_removed"] == removed
    assert packet["wisdom_restored"] == restored
    assert removed in packet["narration_cue"].lower()
    if restored:
        assert f"{restored} Wisdom" in packet["narration_cue"]


@pytest.mark.parametrize("self_cast", [False, True], ids=["ally-stage-three", "self-at-wisdom-cap"])
async def test_hollowed_restores_only_recorded_wisdom_and_spends_focus(walk, self_cast):
    target = walk.player if self_cast else await walk.add_player()
    wisdom = 19 if self_cast else 10
    await seed(walk, target, HOLLOWED, PETRIFIED, wisdom=wisdom)
    if not self_cast:
        row = await walk.read(target)
        await walk.patch_row(
            target,
            **recompute_pools(
                {
                    **row,
                    "class": "cleric",
                    "level": 5,
                    "focus": {"current": 3},
                    "stamina": {"current": 2},
                }
            ),
            **{"class": "cleric", "level": 5},
        )
    before = await walk.read(target)
    selectors = {} if self_cast else {"target_id": target}
    packet = await walk.command("activate", {"id": SPELL, **selectors})
    restored = 1 if self_cast else 2
    after = await walk.read(target)
    assert after["conditions"] == [PETRIFIED, OTHER]
    assert after["attributes"] == {**before["attributes"], "wisdom": wisdom + restored}
    assert await walk.focus() == 23
    assert after["hp"]["current"] == before["hp"]["current"]
    if not self_cast:
        assert after["focus"] == {**before["focus"], "max": before["focus"]["max"] + 1}
        assert after["stamina"]["current"] == before["stamina"]["current"]
    assert_receipt(packet, target, "hollowed", restored)


async def test_combat_live_only_hollowed_stays_clear_after_reload_end_and_rest(walk):
    target = await walk.add_player()
    await seed(walk, target)
    state = await walk.fight()
    state.get_participant(target).conditions = [{"type": "hollowed", "stage": 1}, OTHER]
    combat_spatial.place(state, target, {"x": 30, "y": 0, "z": 0})
    combat_structures.add_wall(state, "wall", "Wall", {"x": 15, "y": -10, "z": 0}, {"x": 15, "y": 10, "z": 0})
    await walk.save()
    await declare(walk, target)
    assert_receipt(await resolve(walk), target, "hollowed", 0)
    assert (await walk.read(target))["conditions"] == [OTHER]
    walk.sd.combat_state = await walk.checkpoint()
    assert walk.fight_state.get_participant(target).conditions == [OTHER]
    assert not any(p.get("cast") for p in await walk.wrap())
    await walk.register_end()
    with patch("combat_end._build_handoff_agent", return_value=walk.session.current_agent):
        await walk.command("end_combat", {"outcome": "fled"})
    result = await walk.command("rest", {"rest_type": "long"})
    assert result["hollowed_changes"] == []
    after = await walk.read(target)
    assert all(c["type"] != "hollowed" for c in after["conditions"])
    assert after["attributes"]["wisdom"] == 10


@pytest.mark.parametrize(
    ("active", "choice", "combat", "removed", "survivors"),
    [
        ([PETRIFIED], None, False, "petrified", []),
        ([CHARMED, PETRIFIED], "charmed", False, "charmed", [PETRIFIED]),
        ([CHARMED, PETRIFIED], "petrified", True, "petrified", [CHARMED]),
    ],
)
async def test_removes_one_selected_condition(walk, active, choice, combat, removed, survivors):
    target = await walk.add_player()
    await seed(walk, target, *active)
    if combat:
        await grant_still_charm(walk, target)
        flags = (await walk.read(target))["flags"]
        state = await walk.fight()
        state.get_participant(target).conditions = [*active, OTHER]
        await declare(walk, target, choice)
        packet = await resolve(walk)
        assert (await walk.checkpoint()).get_participant(target).conditions == [*survivors, OTHER]
        assert (await walk.read(target))["flags"] == flags
    else:
        selector = {"condition": choice} if choice else {}
        packet = await walk.command("activate", {"id": SPELL, "target_id": target, **selector})
    after = await walk.read(target)
    assert after["conditions"] == [*survivors, OTHER]
    assert after["attributes"]["wisdom"] == 10
    assert await walk.focus() == 23
    assert_receipt(packet, target, removed, 0)


async def grant_still_charm(walk, *players):
    async with walk.pool.acquire() as conn, conn.transaction():
        for pid in players:
            await still_charm.grant(
                pid,
                await walk.read(pid, conn=conn),
                LOCATION,
                still_charm.PARADISE_TRAP,
                mutations=db_mutations,
                conn=conn,
            )


async def test_still_charm_and_dwell_flags_are_cleared_for_the_recipient(walk):
    target = await walk.add_player()
    await grant_still_charm(walk, walk.player, target)
    before = await walk.row()
    packet = await walk.command("activate", {"id": SPELL, "target_id": target})
    assert_receipt(packet, target, "charmed", 0)
    after = await walk.read(target)
    assert still_charm.key(LOCATION) not in after["flags"]
    assert still_charm.dwell_key(LOCATION) not in after["flags"]
    still_charm.require_departure({target: after}, "elsewhere")
    assert (await walk.row())["flags"] == before["flags"]


@pytest.mark.parametrize(
    ("active", "selector", "reason"),
    [
        ([], {}, "Hollowed, Charmed or Petrified"),
        ([CHARMED, PETRIFIED], {}, "choose"),
        ([PETRIFIED], {"condition": "charmed"}, "Charmed"),
        ([HOLLOWED, PETRIFIED], {"condition": "petrified"}, "Hollowed"),
        ([PETRIFIED], {"condition": "poisoned"}, "poisoned"),
        ([PETRIFIED], {"target_ids": []}, "one player"),
    ],
)
async def test_refuses_without_spending_or_publishing(walk, active, selector, reason):
    target = await walk.add_player()
    await seed(walk, target, *active)
    args = {"target_ids": [target]} if "target_ids" in selector else {"target_id": target, **selector}
    before = await walk.row(), await walk.read(target), published_payloads(walk.sd.room)
    error = await walk.command("activate", {"id": SPELL, **args}, error=True)
    assert reason.lower() in error.lower()
    assert (await walk.row(), await walk.read(target), published_payloads(walk.sd.room)) == before


@pytest.mark.parametrize("party", [False, True], ids=["nonparty", "remote"])
async def test_exploration_requires_a_present_party_player(walk, party):
    target = await walk.add_player(party=party, location="millhaven_square" if party else LOCATION)
    await seed(walk, target, PETRIFIED)
    walk.sd.location_id = (await walk.read(target))["location_id"]
    before = await walk.read(target)
    error = await walk.command("activate", {"id": SPELL, "target_id": target}, error=True)
    assert "present party player" in error
    assert await walk.read(target) == before
    assert await walk.focus() == 30


async def test_combat_declaration_and_activation_refuse_invalid_targets_or_mode(walk):
    ally = await walk.add_player()
    await seed(walk, ally, HOLLOWED)
    state = await walk.fight(companion=True)
    state.get_participant(ally).conditions = [HOLLOWED]
    state.get_participant("foe").conditions = [HOLLOWED]
    state.get_participant("companion").conditions = [HOLLOWED]
    await walk.save()
    before = state.to_dict()
    for target, reason in [("foe", "ally in the fight"), ("companion", "player participant")]:
        assert reason in await declare(walk, target, error=True)
        assert (await walk.checkpoint()).to_dict() == before
    error = await walk.command("activate", {"id": SPELL, "target_id": ally}, error=True)
    assert "declare_phase" in error
    assert await walk.focus() == 30
    await declare(walk, ally)


async def test_phase_preflight_rechecks_durable_condition(walk):
    target = await walk.add_player()
    await seed(walk, target, PETRIFIED)
    await walk.fight()
    await declare(walk, target)
    await seed(walk, target)
    error = await walk.command("resolve_phase", {}, error=True)
    assert "Hollowed, Charmed or Petrified" in error
    assert (await walk.checkpoint()).beat == "declaration"
    assert await walk.focus() == 30


async def test_rollback_and_retry_preserve_durable_wisdom_ledger(walk):
    target = await walk.add_player()
    await seed(walk, target, HOLLOWED)
    state = await walk.fight()
    live_only = {"type": "prone", "stacks": 1, "duration": None}
    state.get_participant(target).conditions = [
        {key: val for key, val in HOLLOWED.items() if key != "wis_drained"},
        live_only,
    ]
    await declare(walk, target)
    before = (
        await walk.row(),
        await walk.read(target),
        deepcopy(walk.sd.party.to_dict()),
        (await walk.checkpoint()).to_dict(),
        published_payloads(walk.sd.room),
    )
    write = db_mutations_conditions.save_player_conditions
    observed = []

    async def fail_after_write(pid, active, *, conn):
        await write(pid, active, conn=conn)
        row = await walk.read(pid, conn=conn)
        caster = await walk.read(walk.player, conn=conn)
        observed.append((pid, row["conditions"], row["attributes"]["wisdom"], caster["focus"]["current"]))
        raise ConnectionError("injected failure after the cleanse write")

    with patch.object(db_mutations_conditions, "save_player_conditions", side_effect=fail_after_write):
        await walk.command("resolve_phase", {}, error=True)
    assert observed == [(target, [OTHER], 12, 23)]
    assert (
        await walk.row(),
        await walk.read(target),
        walk.sd.party.to_dict(),
        (await walk.checkpoint()).to_dict(),
        published_payloads(walk.sd.room),
    ) == before
    assert_receipt(await resolve(walk), target, "hollowed", 2)
    walk.sd.combat_state = await walk.checkpoint()
    live = walk.fight_state.get_participant(target)
    assert live.conditions == [live_only] and live.attributes["wisdom"] == 12
    assert not any(p.get("cast") for p in await walk.wrap())
    assert await walk.focus() == 23


async def test_cast_rechecks_working_target_after_phase_preflight(walk):
    from combat_resolve_phase import _prevalidate_ability_focus

    target = await walk.add_player()
    state = await walk.fight()
    state.get_participant(target).conditions = [PETRIFIED]
    await declare(walk, target)

    async def after_preflight(session, working, adv, **kwargs):
        rows = await _prevalidate_ability_focus(session, working, adv, **kwargs)
        working.get_participant(target).conditions = []
        return rows

    with patch("combat_resolve_phase._prevalidate_ability_focus", side_effect=after_preflight):
        result = await walk.command("resolve_phase", {})
    packet = next(p for p in result["packets"] if p["actor_id"] == walk.player)
    assert packet["resolved"] is False
    assert "Hollowed, Charmed or Petrified" in packet["reason"]
    assert await walk.focus() == 30


async def test_combat_player_outside_the_party_is_refused(walk):
    target = await walk.add_player()
    await seed(walk, target, PETRIFIED)
    state = await walk.fight()
    walk.sd.party.members.pop()
    before = state.to_dict(), await walk.read(target)
    assert "party player" in await declare(walk, target, error=True)
    assert ((await walk.checkpoint()).to_dict(), await walk.read(target)) == before
    assert await walk.focus() == 30
