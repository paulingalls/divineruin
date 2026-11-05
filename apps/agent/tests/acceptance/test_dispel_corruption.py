"""Dispel inventory objects through persisted deterministic tool commands."""

import json
from uuid import uuid4

import pytest
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel
from livekit.agents import Agent, AgentSession
from sample_fixtures import make_mock_room, published_payloads

import db
import db_mutations
import db_queries
import spells
from activate_tools import activate
from caster_state import ConcentrationState, ResonanceTrack
from inventory_tools import transact
from party_state import PartyMember
from query_tools import query_info
from session_data import SessionData

SPELL = "divine_dispel_corruption"


class DispelHarness:
    async def start(self):
        self.pool = await db.get_pool()
        self.players = [f"dispel_{uuid4().hex}" for _ in range(3)]
        for pid in self.players:
            await seed_player_with_pools(self.pool, player_id=pid, class_="cleric", known_spells=(SPELL,))
        await spells.load_spells()
        self.sd = SessionData(player_id=self.players[0], location_id="accord_guild_hall", room=make_mock_room())
        self.sd.party.members.append(PartyMember(self.players[1], ResonanceTrack(), ConcentrationState()))
        self.model = ScenarioModel([])
        self.session = AgentSession(llm=self.model, max_tool_steps=5, userdata=self.sd)
        await self.session.start(Agent(instructions="Execute the command.", tools=[activate, query_info, transact]))
        return self

    async def command(self, name, arguments, *, error=False):
        self.model.commands.append((name, arguments))
        with self.sd._bind_authenticated_actor(self.players[0], 1, lambda *_: None):
            await self.session.run(user_input="Execute the next command.")
        receipt = list(self.model.receipts.values())[-1]
        assert receipt.name == name and receipt.is_error is error, receipt.output
        return receipt.output if error else json.loads(receipt.output)

    async def add(self, owner, item="rend_shard", clean=2, tainted=3):
        for quantity, dirty in [(clean, False), (tainted, True)]:
            if quantity:
                await db_mutations.add_inventory_item(owner, item, quantity, tainted=dirty)

    async def selector(self, owner, item="rend_shard", *, tainted=True):
        inventory = await self.command("query_info", {"kind": "inventory", "target_id": owner})
        return next(i["item_target_id"] for i in inventory["items"] if i["id"] == item and i["tainted"] == tainted)

    async def cast(self, target, *, error=False):
        return await self.command("activate", {"id": SPELL, "target_id": target}, error=error)

    async def focus(self, owner):
        player = await db_queries.get_player(owner)
        assert player is not None
        return player["focus"]["current"]

    async def snapshot(self, owner):
        return await db_queries.get_inventory_snapshot(owner)

    def events(self):
        return [p for p in published_payloads(self.sd.room) if p["type"] == "inventory_updated"]

    async def assert_snapshot(self, owner):
        assert self.events() == [{"type": "inventory_updated", **await self.snapshot(owner)}]

    async def close(self):
        await self.session.aclose()
        for pid in self.players:
            await self.pool.execute("DELETE FROM players WHERE player_id=$1", pid)


@pytest.fixture
async def dispel(reset_db_pool):
    h = await DispelHarness().start()
    try:
        yield h
    finally:
        await h.close()


@pytest.mark.parametrize("clean", [2, 0])
async def test_whole_stack_commits_once(dispel, clean):
    h = dispel
    owner = h.players[0]
    await h.add(owner, clean=clean)
    before = await h.snapshot(owner)
    selector = await h.selector(owner)
    result = await h.cast(selector)
    assert result["purified"] == dict(player_id=owner, source_item_id="rend_shard", item_id="rend_shard", quantity=3)
    assert result["target_id"] == selector
    assert {
        "narration_cue",
        "audio_cue",
        "effect",
        "state",
        "resonance_generated",
        "resonance_modifiers",
        "ward_active",
    } <= result.keys()
    rows = await db_queries.get_player_inventory(owner)
    assert [(r["id"], r["tainted"], r["slot_info"]["quantity"]) for r in rows] == [("rend_shard", False, clean + 3)]
    assert await h.focus(owner) == 7
    assert int((await h.snapshot(owner))["inventory_revision"]) > int(before["inventory_revision"])
    await h.assert_snapshot(owner)
    h.sd.room.local_participant.publish_data.reset_mock()
    assert "no tainted stack" in (await h.cast(selector, error=True)).lower()
    assert await h.focus(owner) == 7 and not h.events()


async def test_selected_party_owner_only(dispel):
    h = dispel
    a, b, _ = h.players
    assert h.sd.companion is None
    await h.add(a, clean=4, tainted=6)
    await h.add(b, clean=1, tainted=5)
    before_a = await h.snapshot(a)
    result = await h.cast(await h.selector(b))
    assert result["purified"]["player_id"] == b and result["purified"]["quantity"] == 5
    assert await h.snapshot(a) == before_a
    assert [(r["tainted"], r["slot_info"]["quantity"]) for r in await db_queries.get_player_inventory(b)] == [
        (False, 6)
    ]
    assert await h.focus(a) == 7 and await h.focus(b) == 10
    await h.assert_snapshot(b)


@pytest.mark.parametrize(
    "item,clean,tainted,message",
    [
        ("corruption_saturated_stone", 0, 3, "unpurifiable"),
        ("rend_shard", 2, 0, "no tainted stack"),
        ("rend_shard", 0, 0, "no tainted stack"),
    ],
)
async def test_refusal_preserves_inventory_and_focus(dispel, item, clean, tainted, message):
    h = dispel
    owner = h.players[0]
    await h.add(owner, item, clean=clean, tainted=tainted)
    before = await h.snapshot(owner)
    selector = await h.selector(owner, item, tainted=bool(tainted)) if clean or tainted else f"item:{owner}:{item}"
    assert message in (await h.cast(selector, error=True)).lower()
    assert await h.snapshot(owner) == before and await h.focus(owner) == 10
    assert not h.events()


async def test_outsider_cannot_be_purified(dispel):
    h = dispel
    a, b, outsider = h.players
    await h.add(outsider)
    before = [await h.snapshot(p) for p in h.players]
    assert "party" in (await h.cast(f"item:{outsider}:rend_shard", error=True)).lower()
    assert [await h.snapshot(p) for p in h.players] == before
    assert [await h.focus(p) for p in [a, b, outsider]] == [10, 10, 10]
    assert not h.events()


async def test_bare_item_refused_before_focus(dispel):
    h = dispel
    owner = h.players[0]
    await h.add(owner)
    before = await h.snapshot(owner)
    assert "item:<owner" in await h.cast("rend_shard", error=True)
    assert await h.focus(owner) == 10 and await h.snapshot(owner) == before
    assert not h.events()


async def test_salvage_becomes_usable_martial_weapon(dispel):
    h = dispel
    owner = h.players[0]
    await h.add(owner, "salvageable_weapon", clean=0)
    await h.add(owner, "battleaxe_common", clean=2, tainted=0)
    result = await h.cast(await h.selector(owner, "salvageable_weapon"))
    assert result["purified"] == dict(
        player_id=owner, source_item_id="salvageable_weapon", item_id="battleaxe_common", quantity=3
    )
    inventory = await h.command("query_info", {"kind": "inventory"})
    assert len(inventory["items"]) == 1
    weapon = inventory["items"][0]
    assert weapon["id"] == "battleaxe_common" and weapon["quantity"] == 5
    assert weapon["type"] == "weapon" and weapon["subtype"] == "martial melee"
    assert weapon["durability_tier"] == "standard"
    assert any(e.get("damage_type") == "slashing" for e in weapon["effects"])
    await h.assert_snapshot(owner)
    pushed = h.events()[0]["inventory"][0]
    assert pushed["damage_dice"] == "1d8" and "versatile" in pushed["properties"]
    h.sd.room.local_participant.publish_data.reset_mock()
    await h.command("transact", {"item_id": "battleaxe_common", "delta": -1})
    assert (await db_queries.get_player_inventory(owner))[0]["slot_info"]["quantity"] == 4
    await h.assert_snapshot(owner)
