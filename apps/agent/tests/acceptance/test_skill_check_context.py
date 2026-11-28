"""Seasonal Attunement through each registered skill roll route."""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy
from acceptance._catalog_cutover_helpers import started as started
from acceptance.mawling_harness import MawlingHarness
from acceptance.quick_fingers_harness import FingersFight
from acceptance.quick_fingers_harness import fingers as fingers
from acceptance.seeds import seed_player, seed_player_with_pools
from acceptance.synergy_discovery import LOCATION, SKILL, discover
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_self_buff_electives import declare, enter_bandit_fight
from acceptance.test_still_actions import reveal_and_wake
from acceptance.test_still_anchors import enter, search_round
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_vanish import walk as walk
from sample_fixtures import make_mock_room, published_payloads
from weapon_fixtures import DAGGER

import combat_terrain
import db
import db_mutations
import db_queries
import patron_gifts
import patron_passives
import thyra_seasons
from combat_agent import CombatAgent
from exploration_agent import EXPLORATION_TOOLS
from session_data import CompanionState, SessionData

FOREST = "greyvale_wilderness_north"
FAVOR = {"patron": "thyra", "level": 0, "max": 100}


@pytest.fixture(autouse=True)
async def autumn(reset_db_pool: str) -> AsyncIterator[None]:
    pool = await db.get_pool()
    previous = await pool.fetchval("SELECT data FROM world_flags WHERE flag_name='season'")
    assert previous is not None
    await pool.execute("""UPDATE world_flags SET data='{"value":"autumn"}' WHERE flag_name='season'""")
    try:
        yield
    finally:
        await pool.execute("UPDATE world_flags SET data=$1::jsonb WHERE flag_name='season'", previous)


@pytest.fixture
def persuasion_on_natural_ground(monkeypatch: pytest.MonkeyPatch) -> None:
    skills = patron_gifts.NATURES_PULSE_SKILLS | {"persuasion"}
    monkeypatch.setattr(patron_gifts, "NATURES_PULSE_SKILLS", skills)
    monkeypatch.setattr(combat_terrain, "NATURES_PULSE_SKILLS", skills)


@contextmanager
def attunement(skill: str, *, active: bool) -> Iterator[None]:
    catalog = deepcopy(patron_passives.load_gods())
    if not active:
        thyra = next(god for god in catalog if god["god_id"] == "thyra")
        thyra["layer_3_tier_abilities"]["acknowledged"]["status"] = "pending"
    with (
        patch.dict(thyra_seasons.SKILL_SEASONS, {skill: "autumn"}),
        patch.object(patron_passives, "load_gods", return_value=catalog),
    ):
        yield


async def mark_roller(player_id: str, **fields: object) -> None:
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        player_id,
        json.dumps({"divine_favor": FAVOR, **fields}),
    )


def dice_packet(session: SessionData, roll_type: str, *, after: int = 0) -> dict:
    [packet] = [p for p in published_payloads(session.room)[after:] if p.get("roll_type") == roll_type]
    return packet


def assert_bonus(rolls: list[dict], skill: str, *, bonus: int = 1) -> None:
    baseline, attuned = rolls
    assert baseline["skill"] == attuned["skill"] == skill
    assert baseline["roll"] == attuned["roll"]
    if "dc" in baseline:
        assert baseline["dc"] == attuned["dc"]
    assert attuned["modifier"] == baseline["modifier"] + bonus
    assert attuned["total"] == baseline["total"] + bonus


@pytest.mark.parametrize(
    "location, skill, roll_type, roll",
    [
        (
            LOCATION,
            "athletics",
            "skill_check",
            SKILL | {"skill": "athletics", "difficulty": "moderate", "context_description": "Climb the ledge"},
        ),
        (LOCATION, "investigation", "skill_check", discover()),
        ("greyvale_south_road", "survival", "gathering_check", {"kind": "gather", "category": "any"}),
        ("greyvale_ruins_exterior", "survival", "navigation_check", None),
        (
            FOREST,
            "persuasion",
            "social_check",
            {
                "kind": "social",
                "npc_id": "guildmaster_torin",
                "skill": "persuasion",
                "difficulty": "easy",
                "synergy_context": "none",
            },
        ),
    ],
    ids=["skill", "discover", "gather", "travel", "social"],
)
async def test_exploration_skill_rolls(
    location: str, skill: str, roll_type: str, roll: dict | None, persuasion_on_natural_ground: None
) -> None:
    pool = await db.get_pool()
    packets, dcs = [], []
    for active in (False, True):
        player_id = f"context_{skill}_{int(active)}"
        await seed_player(pool, player_id=player_id, class_="diplomat", location_id=location)
        await mark_roller(player_id, flags={"ressa_corrow_scout_token.discovered": True})
        session = SessionData(player_id=player_id, location_id=location, room=make_mock_room())
        call = game_tools(session, *EXPLORATION_TOOLS)
        with attunement(skill, active=active), patch("check_resolution.dice_roll", side_effect=[_d20(5), _d20(19)]):
            if roll is None:
                result = await call("travel", destination_id=FOREST, mode="dangerous", hours=4, forced_march=False)
            else:
                result = await call("check", roll=roll)
        packet = dice_packet(session, roll_type)
        assert (packet["roll"], packet["total"]) == (result["roll"], result["total"])
        if "modifier" in result:
            assert packet["modifier"] == result["modifier"]
        if skill == "persuasion":
            assert packet["roll"] == 5
        packets.append(packet)
        dcs.append(result["dc"])
    assert dcs[0] == dcs[1]
    assert_bonus(packets, skill)


async def test_choir_search(started) -> None:
    packets = []
    for active in (False, True):
        ctx, _ = await started("hollow_choir", player_class="mage")
        actor = ctx.userdata.player_id
        await mark_roller(actor)
        call = game_tools(ctx.userdata, agent=CombatAgent())
        await call(
            "declare_phase",
            declarations=[
                {"kind": "interact", "actor_id": actor, "action": "choir_search_arcana", "target_id": "choir_sound"}
            ],
        )
        with attunement("arcana", active=active), patch("check_resolution.dice_roll", return_value=_d20(5)):
            result = await call("resolve_phase")
        packets.append(next(p for p in result["packets"] if p.get("action") == "choir_search_arcana"))
    assert_bonus(packets, "arcana")


async def test_still_search() -> None:
    packets = []
    for active in (False, True):
        still = MawlingHarness()
        try:
            await still.prepare((18,), companion=None, location="ashmark_still")
            await mark_roller(still.players[0])
            response, _ = await enter(still)
            action = next(a for a in response["still"]["search_actions"] if a["action"] == "still_search_arcana")
            with attunement("arcana", active=active):
                packets.append(await search_round(still, action, face=5))
        finally:
            await still.close()
    assert_bonus(packets, "arcana")


@pytest.mark.parametrize("companion", [False, True], ids=["player", "companion"])
async def test_still_illusion(companion: bool) -> None:
    still = MawlingHarness()
    try:
        await still.prepare((18,), companion=None, location="ashmark_still")
        await mark_roller(still.players[0])
        roller = "companion_kael" if companion else still.players[0]
        if companion:
            still.sd.companion = CompanionState(id=roller, name="Kael", player_level=18)
        state = await reveal_and_wake(still)
        for _ in range(sum(p.is_ally for p in state.participants) - 1):
            if still.last_result["still"]["illusion"]["target_id"] == roller:
                break
            await declare(still, {"kind": "defend", "actor_id": still.players[0], "reshape": []})
            await still.drain()
        illusion = still.last_result["still"]["illusion"]
        assert illusion["target_id"] == roller

        receipts = []
        for active in (False, True):
            before = len(published_payloads(still.sd.room))
            with attunement("investigation", active=active), patch("check_resolution.dice_roll", return_value=_d20(5)):
                result = await still.command("check", {"roll": illusion["check"]})
            packet = dice_packet(still.sd, "skill_check", after=before)
            assert not result["seen_through"]
            assert all(result[key] == packet[key] for key in ("roll", "modifier", "total"))
            receipts.append(result)
        assert_bonus(receipts, "investigation", bonus=0 if companion else 1)
    finally:
        await still.close()


async def restore_fight(fight: MawlingHarness, snapshot: tuple[dict, list[dict | None]]) -> None:
    state, players = snapshot
    await db_mutations.save_combat_state(state["combat_id"], state)
    restored = await db_mutations.load_combat_state(state["combat_id"])
    assert restored is not None
    fight.sd.combat_state = restored
    for player_id, row in zip(fight.players, players, strict=True):
        assert row is not None
        await fight.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", player_id, json.dumps(row))


async def test_cunning_action_hide(walk: MawlingHarness) -> None:
    actor = walk.players[0]
    await mark_roller(actor, attributes={"dexterity": 10}, proficiencies=[])
    foe = await enter_bandit_fight(walk)
    state = await walk.reload()
    for enemy in state.participants:
        if not enemy.is_ally:
            enemy.attributes["wisdom"] = 10
    await walk.persist()
    initial = await walk.snapshot()
    for active in (False, True):
        await declare(walk, weapon_attack(actor, foe, "hide", weapon=DAGGER["name"]))
        with (
            attunement("stealth", active=active),
            patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(9)]),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            packets = await walk.drain()
        receipt = next(p["cunning_action"] for p in packets if p["actor_id"] == actor)
        assert (receipt["roll"], receipt["dc"], receipt["concealed"]) == (9, 10, active)
        player = await db_queries.get_player(actor)
        assert player is not None and player["flags"]["concealed"] is active
        if not active:
            await restore_fight(walk, initial)


async def test_quick_fingers(fingers: FingersFight) -> None:
    await mark_roller(fingers.actor)
    initial = await fingers.snapshot()
    receipts = []
    for active in (False, True):
        await fingers.declare(fingers.attack("steal"))
        with attunement("sleight_of_hand", active=active):
            packet = await fingers.swing(7, 17)
        assert packet["hit"]
        receipts.append(packet["quick_fingers"])
        if not active:
            await restore_fight(fingers, initial)
    baseline, attuned = receipts
    assert baseline["dc"] == attuned["dc"]
    assert attuned["total"] == baseline["total"] + 1


async def test_deescalation_argument(persuasion_on_natural_ground: None) -> None:
    pool = await db.get_pool()
    packets = []
    for active in (False, True):
        actor = f"context_argument_{int(active)}"
        await seed_player_with_pools(pool, player_id=actor, class_="diplomat")
        await mark_roller(actor, attributes={"charisma": 10}, location_id=FOREST)
        foe = _enemy("cultist", hp=40)
        state = _build_state(f"combat_{actor}", actor, [foe])
        state.terrain = "forest"
        state.location_id = FOREST
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        session = SessionData(player_id=actor, location_id=FOREST, room=make_mock_room(), combat_state=state)
        call = game_tools(session, agent=CombatAgent())
        await call(
            "declare_phase",
            declarations=[
                {
                    "kind": "ability",
                    "actor_id": actor,
                    "action": "de_escalate",
                    "argument_type": "threat",
                    "targets": [foe.id],
                    "reshape": [],
                }
            ],
        )
        with (
            attunement("persuasion", active=active),
            patch("check_resolution.dice_roll", side_effect=[_d20(5), _d20(19)]),
        ):
            result = await call("resolve_phase")
        receipt = next(p for p in result["packets"] if p.get("action") == "de_escalate")
        packet = dice_packet(session, "de_escalate")
        assert packet["roll"] == 5
        assert receipt["resolved"] and receipt["actor_id"] == actor
        packets.append(packet)
        await db_mutations.delete_combat_state(state.combat_id)
    assert_bonus(packets, "persuasion")
