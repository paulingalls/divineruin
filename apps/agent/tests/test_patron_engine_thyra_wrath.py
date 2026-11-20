import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from _patron_engine_fixtures import configure
from _thyra_wrath_fixtures import GIFT, OTHER_GIFTS, add_foe, checkpoint, declare, fight, fighter, refuse, rolls, saved
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant

import event_types as E
from exploration_agent import ExplorationAgent
from patron_favor import _EXALTED_PERCENT
from terrain import TerrainType, is_natural
from zhael_fate import FATE, FateOffer, Resumed

NATURAL_DAMAGE = {
    "ancient_forest": "piercing",
    "forest": "piercing",
    "grassland": "slashing",
    "farmland": "slashing",
    "mountain": "bludgeoning",
    "underground": "bludgeoning",
    "coast": "cold",
    "wetland": "poison",
}


async def forest(world):
    foes = [fighter("marauder"), fighter("sentinel", damage_affinities={"resistant": ["piercing"]})]
    async with fight(world, *foes) as call:
        session = world.ctx.userdata
        before = await row(world, 0)
        gift = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
        session.combat_state.current_turn_index = 1
        await declare(world, call)
        declarations = session.combat_state.pending_declarations.copy()
        before_activation = len(published_payloads(session.room))
        with rolls() as dice:
            result = await call("activate", id=gift["id"])
        dice.assert_called_once_with("3d8")
        assert (gift["tier"], gift["status"], gift["recharge"], gift["available"], gift["spent"], gift["state"]) == (
            "Exalted",
            "active",
            "per_session",
            True,
            False,
            "ready",
        )
        assert f'activate(id="{GIFT}")' in gift["activation_hint"] and "immediately" in gift["activation_hint"]
        assert (result["terrain"], result["damage_type"], result["roll"]) == (
            "forest",
            "piercing",
            {"notation": "3d8", "total": 15},
        )
        assert [(t["name"], t["damage"], t["target_fallen"], t["target_dead"]) for t in result["targets"]] == [
            ("Marauder", 15, False, False),
            ("Sentinel", 7, False, False),
        ]
        assert "3d8 rolled 15 piercing" in result["dm_cue"] and "forest" in result["dm_cue"]
        for line in ("Marauder takes 15 piercing and stays standing", "Sentinel takes 7 piercing and stays standing"):
            assert line in result["dm_cue"]
        events = published_payloads(session.room)[before_activation:]
        updates = [e for e in events if e["type"] == E.COMBAT_UI_UPDATE]
        assert [
            {p["id"]: p["hpCurrent"] for p in e["combatants"] if p["id"] in ("marauder", "sentinel")} for e in updates
        ] == [{"marauder": 35, "sentinel": 43}]
        assert [
            g["state"]
            for e in events
            if e["type"] == E.PATRON_ABILITIES_UPDATED
            for g in e["abilities"]
            if g["id"] == GIFT
        ] == ["spent"]
        state = await saved(world)
        assert state.to_dict() == session.combat_state.to_dict()
        assert [p.hp_current for p in state.participants] == [50, 50, 50, 35, 43]
        assert state.pending_declarations == declarations
        after = await row(world, 0)
        assert after["patron_gifts"] == {**OTHER_GIFTS, GIFT: {"spent": True}}
        assert all(after[key] == before[key] for key in ("hp", "focus", "stamina", "resonance"))
        refreshed = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
        assert (refreshed["available"], refreshed["spent"], refreshed["state"]) == (False, True, "spent")
        assert "new session" in refreshed["reason"]
        await refuse(world, call, "new session")
        await call("resolve_phase")
        await call("resolve_phase")
        assert session.combat_state.round_number == 2
        assert [p.hp_current for p in session.combat_state.participants][-2:] == [35, 43]


SCENARIOS = {GIFT: ("thyra_wrath:wildmothers_wrath", forest, [()])}


def test_terrain_scenario_covers_every_natural_type():
    assert {t for t in TerrainType if is_natural(t)} == NATURAL_DAMAGE.keys()


@pytest.mark.parametrize("terrain,damage_type", [(t, d) for t, d in NATURAL_DAMAGE.items() if t != "forest"])
async def test_cached_natural_terrain(world, terrain, damage_type):
    async with fight(world, fighter("foe"), terrain=terrain) as call:
        with (
            patch("db_content_queries.get_location_terrain", side_effect=AssertionError("combat cache bypassed")),
            rolls(),
        ):
            result = await call("activate", id=GIFT)
        assert (result["terrain"], result["damage_type"], result["targets"][0]["damage"]) == (terrain, damage_type, 15)
        assert terrain.replace("_", " ") in result["dm_cue"] and damage_type in result["dm_cue"]


async def test_living_hostiles_and_affinities(world):
    foes = [
        fighter("vulnerable", damage_affinities={"vulnerable": ["piercing"]}),
        fighter("immune", damage_affinities={"immune": ["piercing"]}),
        fighter("resists_mundane", resist_nonmagical_physical=True),
        fighter("echo", "temporary_hollowed"),
        fighter("fallen", is_fallen=True),
        fighter("dead", is_dead=True),
        fighter("zero", hp=0),
    ]
    async with fight(world, *foes) as call:
        with rolls():
            result = await call("activate", id=GIFT)
        assert [(t["id"], t["damage"]) for t in result["targets"]] == [
            ("vulnerable", 30),
            ("immune", 0),
            ("resists_mundane", 15),
            ("echo", 15),
        ]
        assert all(not (t["target_fallen"] or t["target_dead"]) for t in result["targets"])
        assert [p.hp_current for p in (await saved(world)).participants][-7:] == [20, 50, 35, 35, 50, 50, 0]
        assert (await row(world, 0))["patron_gifts"][GIFT] == {"spent": True}


@pytest.mark.parametrize("terrain", ["city", "village"])
async def test_urban_ground_refuses(world, terrain):
    async with fight(world, fighter("foe"), terrain=terrain) as call:
        await refuse(world, call, "natural ground")


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"favor": _EXALTED_PERCENT - 1}, "Requires Exalted"),
        ({"patron": "mortaen"}, "follower of thyra"),
        ({"patron": "none"}, "Unbound"),
    ],
)
async def test_ineligible_follower_refuses(world, options, reason):
    async with fight(world, fighter("foe"), **options) as call:
        await refuse(world, call, reason)


async def test_wrath_refuses_outside_combat(world):
    await configure(world, "thyra", "warrior", divine_favor={"patron": "thyra", "level": 75, "max": 100})
    call = game_tools(world.ctx.userdata, agent=ExplorationAgent())
    await refuse(world, call, "only be used in combat")


@pytest.mark.parametrize(
    "field,value", [("absent", None), ("type", "companion"), ("is_fallen", True), ("is_dead", True), ("hp_current", 0)]
)
async def test_acting_participant_must_be_living_player(world, field, value):
    async with fight(world, fighter("foe")) as call:
        state = world.ctx.userdata.combat_state
        actor = participant(state, world.ids[0])
        if field == "absent":
            state.participants.remove(actor)
            state.initiative_order.remove(actor.id)
            for entries in ("positions", "speeds"):
                del state.spatial[entries][actor.id]
        else:
            setattr(actor, field, value)
        await checkpoint(world)
        await refuse(world, call, "living acting player")


async def test_last_foe_falls_then_wrap_ends_combat(world):
    async with fight(world, fighter("foe", hp=5)) as call:
        await declare(world, call)
        session = world.ctx.userdata
        with rolls() as dice:
            result = await call("activate", id=GIFT)
        dice.assert_called_once_with("3d8")
        assert "Foe takes 15 piercing and falls" in result["dm_cue"]
        assert "No foe is left standing" in result["dm_cue"]
        await call("resolve_phase")
        _, outcome = await call("resolve_phase")
        assert outcome["outcome"] == "victory" and session.combat_state is None
        assert [e["outcome"] for e in published_payloads(session.room) if e["type"] == E.COMBAT_ENDED] == ["victory"]


@pytest.mark.parametrize("encounter", ["hollow_still", "hollow_choir"])
async def test_encounter_protection(world, encounter):
    async with fight(world, encounter=encounter) as call:
        state = world.ctx.userdata.combat_state
        still = state.still_encounter
        protected = still or state.choir_encounter
        owner = participant(state, protected["owner_id"])
        reason = "protected by the Still's anchors" if still else "protected until its core is exposed"
        await refuse(world, call, reason)
        foe = fighter("marauder")
        add_foe(state, foe)
        if still:
            anchor_id = still["anchor_ids"][0]
            still["revealed_ids"].append(anchor_id)
        await checkpoint(world)
        with rolls():
            result = await call("activate", id=GIFT)
        assert f"{owner.name} is {reason}" in result["dm_cue"]
        assert f"{owner.name} is {reason}." in result["spared"]
        checkpointed = await saved(world)
        assert participant(checkpointed, foe.id).hp_current == 35
        if still:
            assert "5 unrevealed anchors" in result["dm_cue"]
            serialized = json.dumps(result)
            for hidden_id in still["anchor_ids"][1:]:
                hidden = participant(state, hidden_id)
                assert hidden.id not in serialized and hidden.name not in serialized
                assert participant(checkpointed, hidden_id).hp_current == hidden.hp_current
            assert [t["damage"] for t in result["targets"] if t["id"] == anchor_id] == [15]
            assert participant(checkpointed, anchor_id).hp_current == participant(state, anchor_id).hp_max - 15
            assert participant(checkpointed, owner.id).hp_current == owner.hp_max - 15
        else:
            assert participant(checkpointed, owner.id).hp_current == owner.hp_current


async def test_exposed_choir_core_can_be_hit(world):
    async with fight(world, encounter="hollow_choir") as call:
        state = world.ctx.userdata.combat_state
        state.choir_encounter["phase"] = "exposed"
        await checkpoint(world)
        with rolls():
            result = await call("activate", id=GIFT)
        assert result["spared"] == []
        assert [(t["id"], t["damage"]) for t in result["targets"]] == [(state.choir_encounter["owner_id"], 0)]


async def test_no_living_foe_refuses(world):
    async with fight(world, fighter("foe", hp=0, is_fallen=True)) as call:
        await refuse(world, call, "no living unprotected foe")


async def test_live_fate_offer_prevents_wrath(world):
    async with fight(world, fighter("foe")) as call:
        session = world.ctx.userdata
        original = AsyncMock(return_value=Resumed({"outcome": "original"}))
        offer = FateOffer("wrap-save", "save", world.ids[0], 12, 12, {FATE: (world.ids[1],)}, Mock(), original, Mock())
        session.fate_offer = offer
        await refuse(world, call, "partially resolved")
        assert session.fate_offer is offer
        original.assert_not_called()
