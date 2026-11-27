import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import BANDIT, SWORD
from acceptance.test_opportunity_strike import participant
from acceptance.test_still_actions import reveal_and_wake
from acceptance.test_still_anchors import fresh_session, strike

import combat_spatial
import db_mutations_concentration
import db_queries
from caster_state import ConcentrationState, ResonanceTrack
from db_mutations_resonance import read_player_resonance
from party_state import PartyMember

BRACE = "warrior_brace_for_impact"
SHIELD = "mage_shield_spell"
THOUGHT = "whisper_thought_shield"
CHOIR = "hollow_choir"
SPELL = "arcane_fly"


@asynccontextmanager
async def defense_fight(
    archetype: str, enemy: str = BANDIT, *, fate: bool = False, constitution: int = 14, ally_archetype: str = "guardian"
) -> AsyncIterator[MawlingHarness]:
    fight = MawlingHarness()
    try:
        await fight.prepare(
            (18, 6), companion=None, location="ashmark_still" if enemy == "still" else "greyvale_wilderness_north"
        )
        for actor, class_ in zip(fight.players, (archetype, ally_archetype), strict=True):
            row = await player_row(actor)
            row["class"] = class_
            row["attributes"]["constitution"] = constitution
            await fight.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", actor, json.dumps(row))
        if enemy == "still":
            state = await reveal_and_wake(fight, count=2)
            owner = state.still_encounter["owner_id"]
            fight.enemies = [owner]
            positions = combat_spatial.require_spatial(state)["positions"]
            origin = positions[owner]
            positions[fight.players[0]] = {**origin, "x": origin["x"] + 5}
            positions[fight.players[1]] = {**origin, "x": origin["x"] + 10}
        else:
            fight.encounter_id = f"defense_{uuid4().hex}"
            fight.owns_template = True
            fight.enemies = [enemy, "lookout"] if enemy in (BANDIT, "hollow_warden") else [enemy]
            template = {
                "id": fight.encounter_id,
                "name": "Roadside ambush",
                "description": "A boot scrapes gravel.",
                "difficulty": "hard",
                "recommended_party_level": 6,
                "enemies": [{"id": actor, "creature_id": enemy, "role": "standard"} for actor in fight.enemies],
                "scene_placement": {
                    "party_start": pos(0),
                    "companion_start": pos(0),
                    "actors": {actor: pos(-5, index * 5) for index, actor in enumerate(fight.enemies)},
                    "zones": {},
                    "locations": {},
                },
            }
            await fight.pool.execute(
                "INSERT INTO encounter_templates (id, data) VALUES ($1,$2::jsonb)",
                fight.encounter_id,
                json.dumps(template),
            )
            await fight.command("enter_mode", {"mode": "combat", "encounter_id": fight.encounter_id})
            state = await fight.reload()
            combat_spatial.require_spatial(state)["positions"].update(
                {fight.players[0]: pos(0), fight.players[1]: pos(5)}
            )
        state.initiative_order = [
            *fight.enemies,
            *[actor for actor in state.initiative_order if actor not in fight.enemies],
        ]
        for index, actor in enumerate(fight.enemies):
            participant(state, actor).initiative = 30 - index
        participant(state, fight.players[0]).ac = 16
        if fate:
            await fight.pool.execute(
                "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
                fight.players[0],
                '{"patron":"zhael","level":0,"max":100,"last_whisper_level":0}',
            )
            fight.sd.concentration.spell_id = SPELL
            await db_mutations_concentration.update_player_concentration(fight.players[0], SPELL, conn=fight.pool)
        await fight.persist()
        yield fight
    finally:
        await fight.close()


async def spend(fight: MawlingHarness, ability: str, *, stage: str) -> list[dict]:
    packets = []
    for _ in range(8):
        result = await fight.command("resolve_phase", {})
        if offer := result.get("fate_offer"):
            result = await keep_original(fight, offer)
        packets.extend(result["packets"])
        if window := result["next"]["waiting_on"]:
            if window["stage"] != stage:
                continue
            assert ability in {reaction["id"] for reaction in window["reactions"]}, window
            target = fight.players[0]
            pool = "stamina" if ability == BRACE else "focus"
            before = (await player_row(target))[pool]["current"]
            await fight.command("activate", {"id": ability})
            assert (await player_row(target))[pool]["current"] == before - (2 if ability == BRACE else 1)
            return packets
    raise AssertionError(f"No {stage} window for {ability}")


async def player_row(actor: str) -> dict:
    row = await db_queries.get_player(actor)
    assert row is not None
    return row


async def hp(fight: MawlingHarness) -> list[int]:
    state = await fight.reload()
    health = [(await player_row(actor))["hp"]["current"] for actor in fight.players]
    assert health == [participant(state, actor).hp_current for actor in fight.players]
    return health


def action_packet(packets: list[dict], actor: str, action: str) -> dict:
    (packet,) = [packet for packet in packets if packet.get("action") == action and packet["actor_id"] == actor]
    return packet


def reaction_packet(packets: list[dict], ability: str) -> dict:
    (packet,) = [packet for packet in packets if packet.get("ability_id") == ability]
    return packet


async def declare_attacks(fight: MawlingHarness, target: str, *actors: str) -> None:
    await fight.command(
        "declare_phase",
        {"declarations": [{"actor_id": actor, **strike(target, action=SWORD)} for actor in actors or fight.enemies]},
    )


async def reload_session(fight: MawlingHarness) -> None:
    await fresh_session(fight, await fight.reload())
    for actor in fight.players:
        player = await player_row(actor)
        resonance = await read_player_resonance(actor)
        concentration = await db_mutations_concentration.read_player_concentration(actor)
        favor = player.get("divine_favor") or {}
        if actor != fight.players[0]:
            fight.sd.party.members.append(PartyMember(actor, ResonanceTrack(), ConcentrationState()))
        member = fight.sd.member_state(actor)
        member.patron_id = favor.get("patron", "none")
        member.resonance.current = resonance["current"]
        member.resonance.flickering_bonus = resonance["flickering_bonus"]
        member.concentration.spell_id = concentration["spell_id"]
