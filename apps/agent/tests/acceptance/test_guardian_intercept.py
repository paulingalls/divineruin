import json
from collections.abc import AsyncIterator
from itertools import chain, repeat
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_opportunity_strike import participant, stamina
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_slippery_restrain import strike
from livekit.agents.llm import FunctionCallOutput, FunctionTool

import combat_spatial
import db
import db_mutations
import db_mutations_concentration
import db_queries
from combat_structures import THORNWALL, add_wall
from combat_turn import resolve_phase

INTERCEPT = "guardian_intercept"
BANDIT = "bandit"
SWORD = "Short Sword"
WALL = "thornwall"
SHIELD = "guardian_retaliating_shield"
SHIELD_ITEM = "thornveld_guardian_shield"
ARMOR = "chain_mail"
SPELL = "arcane_fly"


@pytest.fixture
async def fight(reset_db_pool: str, scenario: str, request: pytest.FixtureRequest) -> AsyncIterator[MawlingHarness]:
    harness = MawlingHarness()
    try:
        await harness.prepare((3, 6, 3), companion=None)
        guardian, ally, other = harness.players
        followup = scenario in ("followup", "duplicate_followup")
        for actor, class_ in zip(
            harness.players,
            (
                "guardian",
                "guardian" if scenario in ("self", "shield") else "rogue",
                "guardian" if scenario.startswith("duplicate") else "mage",
            ),
            strict=True,
        ):
            await harness.pool.execute(
                "UPDATE players SET data = jsonb_set(data, '{class}', $2::jsonb) WHERE player_id = $1",
                actor,
                json.dumps(class_),
            )
        if scenario == "shield":
            for actor in (guardian, ally):
                for item in (SHIELD_ITEM, ARMOR):
                    await harness.pool.execute(
                        "INSERT INTO player_inventory (player_id,item_id,data) VALUES ($1,$2,$3::jsonb)",
                        actor,
                        item,
                        '{"equipped":true,"current_hits":25}',
                    )
        if scenario == "concentration":
            for actor in (guardian, ally):
                harness.sd.member_state(actor).concentration.spell_id = SPELL
                await db_mutations_concentration.update_player_concentration(actor, SPELL, conn=harness.pool)
        harness.encounter_id = f"intercept_{uuid4().hex}"
        harness.owns_template = True
        enemies = [BANDIT, "lookout"] if followup else [BANDIT]
        template = {
            "id": harness.encounter_id,
            "name": "Roadside ambush",
            "description": "A boot scrapes gravel.",
            "difficulty": "hard",
            "recommended_party_level": 3,
            "enemies": [{"id": actor, "creature_id": BANDIT, "role": "standard"} for actor in enemies],
            "scene_placement": {
                "party_start": pos(0),
                "companion_start": pos(0),
                "actors": {BANDIT: pos(-5), **({"lookout": pos(0, 5)} if followup else {})},
                "zones": {},
                "locations": {},
            },
        }
        await harness.pool.execute(
            "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)",
            harness.encounter_id,
            json.dumps(template),
        )
        await harness.command("enter_mode", {"mode": "combat", "encounter_id": harness.encounter_id})
        if getattr(request, "param", False):
            # Register the underlying verb to exercise settlement without Fate's tool wrapper.
            agent = harness.session.current_agent
            await agent.update_tools(
                [
                    resolve_phase if isinstance(tool, FunctionTool) and tool.id == "resolve_phase" else tool
                    for tool in agent.tools
                ]
            )
        state = await harness.reload()
        combat_spatial.require_spatial(state)["positions"].update(
            {guardian: pos(6 if scenario == "range" else 5), ally: pos(0), other: pos(0, -5)}
        )
        if scenario == "resistance":
            for actor in (guardian, ally):
                participant(state, actor).damage_affinities = {"resistant": ["slashing"]}
        if scenario == "temp":
            participant(state, guardian).hp_current = 4
            participant(state, guardian).temp_hp = 5
            async with db.transaction() as conn:
                await db_mutations.update_player_temp_hp(guardian, 5, conn=conn)
        bandit = participant(state, BANDIT)
        sword = next(action for action in bandit.action_pool if action["name"] == SWORD)
        if scenario == "grapple":
            sword["properties"] = [*sword.get("properties", []), "grapple"]
        if scenario == "condition":
            sword.update(applies_condition="frightened", save="wisdom", dc=12)
        if scenario == "critical":
            participant(state, guardian).attributes["constitution"] = 20
            participant(state, ally).attributes["constitution"] = 10
            sword["critical_save"] = {"applies_condition": "hollowed", "save": "CON", "dc": 8, "stage": 1}
        if scenario == "prepared":
            bandit.pending_preparation = {"on_hit": {"applies_condition": "poisoned", "duration": 3}}
        if followup:
            bandit.initiative = 30
            participant(state, "lookout").initiative = 29
            state.initiative_order = [BANDIT, "lookout", *harness.players]
        if scenario == "structure":
            add_wall(state, WALL, "Thornwall", pos(0, -4), pos(0, 4), kind=THORNWALL)
        target = WALL if scenario == "structure" else ally
        await harness.persist()
        await harness.command(
            "declare_phase",
            {
                "declarations": [
                    *(strike(actor, target, SWORD) for actor in enemies),
                    *({"reshape": [], "kind": "defend", "actor_id": p} for p in harness.players),
                ]
            },
        )
        with (
            patch(
                "check_resolution.dice_roll",
                side_effect=chain(
                    [_d20(20 if scenario == "critical" else 17)],
                    repeat(_d20(4 if scenario in ("condition", "concentration", "critical") else 17)),
                ),
            ),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            yield harness
    finally:
        await harness.close()


async def pools(fight: MawlingHarness) -> list[tuple[int, int]]:
    state = await fight.reload()
    pools = []
    for actor in fight.players:
        player = participant(state, actor)
        row = await db_queries.get_player(actor)
        assert row is not None
        pools.append((player.hp_current, player.temp_hp))
        assert pools[-1] == (row["hp"]["current"], row.get("temp_hp", 0))
    return pools


async def opening(fight: MawlingHarness) -> dict:
    for _ in range(4):
        result = await fight.command("resolve_phase", {})
        if window := result["next"]["waiting_on"]:
            assert "on_ally_hit" in window["triggers"], window
            return window
    raise AssertionError("the held hit never opened a reaction window")


async def tool_receipt(fight: MawlingHarness, actor: str, name: str, arguments: dict) -> FunctionCallOutput:
    fight.model.commands.append((name, arguments))
    with fight.sd._bind_authenticated_actor(actor, 1, lambda *_: None):
        await fight.session.run(user_input="Execute the next command.")
    receipt = list(fight.model.receipts.values())[-1]
    assert receipt.name == name
    return receipt


async def activate(fight: MawlingHarness, actor: str) -> FunctionCallOutput:
    return await tool_receipt(fight, actor, "activate", {"id": INTERCEPT})


def blows(packets: list[dict]) -> list[dict]:
    return [p for p in packets if p["actor_id"] in (BANDIT, "lookout") and p.get("hit")]


@pytest.mark.parametrize(
    "scenario, intercept, fight",
    [
        pytest.param(scenario, intercept, False, id=f"{scenario}-{'intercept' if intercept else 'baseline'}")
        for scenario in ("plain", "resistance", "temp", "grapple", "condition", "critical", "prepared", "followup")
        for intercept in ((True,) if scenario == "followup" else (False, True))
    ]
    + [pytest.param(scenario, True, True, id=f"{scenario}-immediate") for scenario in ("critical", "prepared")],
    indirect=["fight"],
)
async def test_hit(fight: MawlingHarness, scenario: str, intercept: bool) -> None:
    guardian, ally, _ = fight.players
    before = await pools(fight)
    start = await stamina(guardian)
    window = await opening(fight)
    if intercept:
        assert any(r["id"] == INTERCEPT for r in window["reactions"])
        receipt = await activate(fight, guardian)
        assert not receipt.is_error, receipt.output
        state = await fight.reload()
        assert state.reactions_available[guardian]["window_id"] == window["window_id"]
    assert await stamina(guardian) == start - (3 if intercept else 0)
    packets = await fight.drain()
    (guardian_hp, guardian_temp), (ally_hp, ally_temp), other_pool = await pools(fight)
    damage = {"resistance": 3, "critical": 14}.get(scenario, 7)
    absorbed = 5 if scenario == "temp" and intercept else 0
    assert (guardian_hp, guardian_temp) == (
        before[0][0] - (damage - absorbed if intercept else 0),
        before[0][1] - absorbed,
    )
    assert (ally_hp, ally_temp) == (before[1][0] - (damage if not intercept or scenario == "followup" else 0), 0)
    assert other_pool == before[2]
    blow, *later = blows(packets)
    assert blow["damage"] == damage and not blow["target_fallen"]
    if intercept:
        assert (blow["target_id"], blow["damage_target_id"]) == (ally, guardian)
        assert [p["actor_id"] for p in packets if p.get("mechanical_effect") == "damage_intercepted"] == [guardian]
    if scenario == "followup":
        (second,) = later
        assert second["damage"] == 7 and "damage_target_id" not in second
    if scenario == "critical":
        assert blow["critical"] and blow["critical_save"]["success"] is False
    if scenario in ("grapple", "condition", "critical", "prepared"):
        state = await fight.reload()
        condition = {"grapple": "grappled", "condition": "frightened", "critical": "hollowed", "prepared": "poisoned"}[
            scenario
        ]
        source = BANDIT if scenario == "grapple" else SWORD
        assert blow["condition_inflicted"] == condition
        assert any(c["type"] == condition and c["source"] == source for c in participant(state, ally).conditions)
        assert all(c["type"] != condition for c in participant(state, guardian).conditions)


async def wear(actor: str) -> dict[str, int]:
    return {i["id"]: i["slot_info"]["current_hits"] for i in await db_queries.get_player_inventory(actor)}


@pytest.mark.parametrize("scenario", ["shield"])
async def test_spent_shield_wears_its_owner(fight: MawlingHarness) -> None:
    guardian, ally, _ = fight.players
    window = await opening(fight)
    assert {INTERCEPT, SHIELD} <= {r["id"] for r in window["reactions"]}
    for actor, ability in ((ally, SHIELD), (guardian, INTERCEPT)):
        receipt = await tool_receipt(fight, actor, "activate", {"id": ability})
        assert not receipt.is_error, receipt.output
    packets = await fight.drain()
    assert await wear(ally) == {SHIELD_ITEM: 24, ARMOR: 25}
    assert await wear(guardian) == {SHIELD_ITEM: 25, ARMOR: 24}
    (blow,) = blows(packets)
    assert blow["damage_target_id"] == guardian
    effects = [p["mechanical_effect"] for p in packets if p["actor_id"] == ally and p.get("ability_id") == SHIELD]
    assert effects == ["shield_durability"]


@pytest.mark.parametrize("scenario", ["concentration"])
async def test_intercepted_hit_tests_guardian_concentration(fight: MawlingHarness) -> None:
    guardian, ally, _ = fight.players
    await opening(fight)
    assert not (await activate(fight, guardian)).is_error
    await fight.drain()
    held = db_mutations_concentration.read_player_concentration
    assert await held(guardian, conn=fight.pool) == {"spell_id": None}
    assert await held(ally, conn=fight.pool) == {"spell_id": SPELL}
