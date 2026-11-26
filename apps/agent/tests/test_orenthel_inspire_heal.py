"""Restoring Song through registered tools, player rows and combat checkpoints."""

import random
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, Fight, fight
from test_kaelen_war_songs import inspire
from voice_condition_fixtures import participant

import ability_persistence
import db_mutations
from activate_tools import activate
from dice import DiceResult, roll
from query_tools import query_info
from session_data import CompanionState

HEAL = "orenthel_inspire_heal"
BUFF = "bard_inspire"
FOCUS = 10
SEED = 0


class Song:
    def __init__(self, world: SimpleNamespace, singer: int, encounter: Fight | None) -> None:
        self.world, self.singer, self.encounter = world, singer, encounter
        self.target = 1 - singer
        self.actor_id, self.target_id = world.ids[singer], world.ids[self.target]
        self.session = world.ctx.userdata
        self.call = game_tools(self.session, activate, query_info)

    async def rows(self) -> list[dict]:
        return [await row(self.world, self.singer), await row(self.world, self.target)]

    def declaration(self, action: str, target_id: str | None = None) -> dict:
        return inspire(self.actor_id, action, target_id or self.target_id)

    async def resolve(self) -> dict:
        assert self.encounter is not None
        packets = (await self.encounter.call("resolve_phase"))["packets"]
        return next(p for p in packets if p["actor_id"] == self.actor_id)

    async def finish_round(self) -> None:
        assert self.encounter is not None
        for _ in range(4):
            if self.session.combat_state.beat == "declaration":
                return
            await self.encounter.call("resolve_phase")
        raise AssertionError("round did not wrap")

    async def invoke(self, action: str) -> dict:
        if self.encounter is None:
            return await self.call("activate", id=action, target_id=self.target_id)
        before = await self.rows()
        await self.encounter.declare(self.declaration(action))
        assert await self.rows() == before
        await self.encounter.reload()
        return await self.resolve()

    async def assert_paid(self, hp: int, *, inspired: bool) -> None:
        singer, target = await self.rows()
        assert (singer["focus"]["current"], target["focus"]["current"]) == (FOCUS - 2, FOCUS)
        assert target["hp"]["current"] == hp
        if self.encounter is not None:
            saved = await self.encounter.reload()
            target = participant(saved, self.target_id)
            assert target.hp_current == hp
            active = target.conditions
        else:
            active = target.get("conditions", [])
        assert any(c["type"] == "inspired" for c in active) is inspired


@asynccontextmanager
async def party(
    world: SimpleNamespace,
    surface: str,
    *,
    singer: int = 0,
    patron: str = "orenthel",
    archetype: str = "bard",
    hp: int = 4,
    override: int = 0,
    restriction: str = "",
):
    session = world.ctx.userdata

    @asynccontextmanager
    async def bind(encounter: Fight | None):
        other_patron = "kaelen" if patron == "orenthel" else "orenthel"
        for index, pid in enumerate(world.ids):
            sings = index == singer
            active = [{"type": "deafened"}] if not sings and restriction == "deafened" else []
            member_patron = patron if sings else other_patron if singer == 1 else "veythar"
            await configure(
                world,
                member_patron,
                archetype if sings else "warrior",
                index=index,
                location_id="millhaven_inn",
                hp={"current": 16 if sings else hp, "max": 20},
                temp_hp=1 if sings else 3,
                focus={"current": FOCUS, "max": FOCUS},
                maxhp_override=0 if sings else override,
                conditions=active,
            )
            if encounter is not None:
                combatant = participant(session.combat_state, pid)
                combatant.hp_current = 16 if sings else hp
                combatant.hp_max = 20 + (0 if sings else override) + (5 if member_patron == "kaelen" else 0)
                combatant.conditions = active
        if encounter is not None:
            if restriction == "silenced":
                session.combat_state.spatial["zones"] = {
                    "quiet": {"kind": "silence", "center_id": world.ids[singer], "radius_ft": 0}
                }
            await db_mutations.save_combat_state(encounter.combat_id, session.combat_state.to_dict())
        lifecycle = _live_party(session, *world.ids)
        try:
            actor_id = world.ids[singer]
            generation = await lifecycle.authorize(actor_id)
            assert generation is not None
            session.member_state(actor_id).patron_id = other_patron
            with session._bind_authenticated_actor(actor_id, generation, lifecycle.require_authorized):
                yield Song(world, singer, encounter)
        finally:
            await lifecycle.aclose()

    if surface == "combat":
        async with fight(world, patron, archetype=archetype) as encounter, bind(encounter) as song:
            yield song
    else:
        async with bind(None) as song:
            yield song


async def heal(song: Song, hp: int, maximum: int) -> None:
    rolls: list[tuple[str, int]] = []

    def capture(notation: str) -> DiceResult:
        result = roll(notation, rng=random.Random(SEED))
        rolls.append((notation, result.total))
        return result

    expected = roll("1d4", rng=random.Random(SEED)).total
    with patch("combat_spell_heal.dice.roll", side_effect=capture):
        packet = await song.invoke(HEAL)
        after = min(hp + expected, maximum)
        assert rolls == [("1d4", expected)]
        assert packet["healing_results"] == [
            {
                "target_id": song.target_id,
                "rolled": expected,
                "modifier": 0,
                "healed": after - hp,
                "hp_current": after,
                "hp_max": maximum,
                "synergy_components": [{"id": HEAL, "dice": "1d4"}],
            }
        ]
        assert "condition_applied" not in packet and "condition_targets" not in packet
        assert "Orenthel" in packet["narration_cue"]
        await song.assert_paid(after, inspired=False)
        singer_hp = 18 if after > hp else 16
        assert (await song.rows())[0]["hp"]["current"] == singer_hp
        if song.encounter is None:
            room = song.session.room
            updates = {
                call.kwargs["destination_identities"][0]: (event["current"], event["max"], event["temp_hp"])
                for call, event in zip(
                    room.local_participant.publish_data.call_args_list, published_payloads(room), strict=True
                )
                if event["type"] == "hp_changed"
            }
            assert updates == (
                {song.target_id: (after, maximum, 3), song.actor_id: (singer_hp, 20, 1)} if after > hp else {}
            )
        if song.encounter is not None:
            await song.finish_round()
            assert rolls == [("1d4", expected)]
            await song.assert_paid(after, inspired=False)
            assert (await song.rows())[0]["hp"]["current"] == singer_hp


async def inspire_healing(world: SimpleNamespace, surface: str) -> None:
    async with party(world, surface) as song:
        await heal(song, 4, 20)
        assert HEAL in {a["id"] for a in (await song.call("query_info", kind="abilities"))["abilities"]}


SCENARIOS = {HEAL: ("patron_synergy_heal:inspire_heal", inspire_healing, [("combat",), ("exploration",)])}


@pytest.mark.parametrize("surface", ["combat", "exploration"])
@pytest.mark.parametrize("hp", [14, 15])
async def test_effective_maximum(world: SimpleNamespace, surface: str, hp: int) -> None:
    async with party(world, surface, hp=hp, override=-5) as song:
        await heal(song, hp, 15)


@pytest.mark.parametrize("surface", ["combat", "exploration"])
async def test_orenthel_guest_heals(world: SimpleNamespace, surface: str) -> None:
    async with party(world, surface, singer=1) as song:
        await heal(song, 4, 25)


@pytest.mark.parametrize("surface", ["combat", "exploration"])
@pytest.mark.parametrize(
    "singer,patron,archetype", [(0, "kaelen", "bard"), (1, "kaelen", "bard"), (0, "orenthel", "diplomat")]
)
async def test_refuses_ineligible_singer(
    world: SimpleNamespace, surface: str, singer: int, patron: str, archetype: str
) -> None:
    async with party(world, surface, singer=singer, patron=patron, archetype=archetype) as song:
        before = await song.rows()
        events = published_payloads(song.session.room)
        with pytest.raises(ToolError, match="Inspire healing requires an Orenthel bard"):
            if song.encounter is not None:
                state = song.session.combat_state.to_dict()
                await song.encounter.declare(song.declaration(HEAL))
            else:
                await song.invoke(HEAL)
        assert await song.rows() == before
        assert published_payloads(song.session.room) == events
        if song.encounter is not None:
            assert song.session.combat_state.to_dict() == state
            assert (await song.encounter.reload()).to_dict() == state
        assert HEAL not in {a["id"] for a in (await song.call("query_info", kind="abilities"))["abilities"]}


@pytest.mark.parametrize("surface", ["combat", "exploration"])
async def test_inspire_still_buffs(world: SimpleNamespace, surface: str) -> None:
    async with party(world, surface) as song:
        packet = await song.invoke(BUFF)
        assert packet["condition_applied"] == "inspired"
        assert "healing_results" not in packet
        await song.assert_paid(4, inspired=True)


@pytest.mark.parametrize(
    "surface,restriction,reason",
    [("combat", "silenced", "silenced"), ("combat", "deafened", "can hear"), ("exploration", "deafened", "can hear")],
)
async def test_inspire_heal_needs_audible_delivery(
    world: SimpleNamespace, surface: str, restriction: str, reason: str
) -> None:
    async with party(world, surface, restriction=restriction) as song:
        before = await song.rows()
        with pytest.raises(ToolError, match=reason):
            await song.invoke(HEAL)
        assert await song.rows() == before


async def test_combat_rechecks_singer_after_declaration(world: SimpleNamespace) -> None:
    async with party(world, "combat", singer=1) as song:
        encounter = song.encounter
        assert encounter is not None
        await encounter.declare(song.declaration(HEAL))
        state = (await encounter.reload()).to_dict()
        await configure(world, "kaelen", "bard", index=song.singer)
        before = await song.rows()
        with pytest.raises(ToolError, match="Inspire healing requires an Orenthel bard"):
            await song.resolve()
        assert await song.rows() == before
        assert (await encounter.reload()).to_dict() == {**state, "beat": "declaration", "pending_declarations": {}}


async def test_combat_inspire_heals_only_allies(world: SimpleNamespace) -> None:
    async with party(world, "combat") as song:
        encounter = song.encounter
        assert encounter is not None
        enemy = participant(song.session.combat_state, GOBLIN)
        enemy.hp_current = 4
        before = await song.rows()
        await encounter.declare(song.declaration(HEAL, GOBLIN))
        packet = await song.resolve()
        assert not packet["resolved"] and "requires an ally" in packet["reason"]
        assert await song.rows() == before
        assert participant(await encounter.reload(), GOBLIN).hp_current == 4


async def test_exploration_cannot_heal_companion(world: SimpleNamespace) -> None:
    async with party(world, "exploration") as song:
        song.session.companion = CompanionState(id="kael", name="Kael")
        before = await song.rows()
        with pytest.raises(ToolError, match="Inspire requires a present party player: kael"):
            await song.call("activate", id=HEAL, target_id="kael")
        assert await song.rows() == before


async def test_exploration_rechecks_singer_after_debit(world: SimpleNamespace) -> None:
    async with party(world, "exploration", singer=1) as song:
        before = await song.rows()
        events = published_payloads(song.session.room)
        update_resources = ability_persistence.update_player_resources

        async def depart_after_debit(player_id: str, **kwargs) -> None:
            await update_resources(player_id, **kwargs)
            song.session.departing_player_id = player_id

        with (
            patch.object(ability_persistence, "update_player_resources", side_effect=depart_after_debit),
            pytest.raises(RuntimeError, match=r"generation .* is stale"),
        ):
            await song.invoke(HEAL)

        assert await song.rows() == before
        assert published_payloads(song.session.room) == events
