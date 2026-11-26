"""The Choir's home, turn-start ambush and whole kit through registered combat tools."""

import json
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from acceptance.choir_harness import (
    HOME,
    KIT,
    ChoirFight,
    Payload,
    ability,
    defend,
    enemy_declaration,
    enemy_turn,
    move,
    party_turn,
    seeded_dice,
)
from asyncpg import Connection

import choir_scene
import combat_hollow_death
import combat_rewards
import combat_spatial
import db_mutations
import db_queries
import spells
from combat_participant import CombatParticipant
from combat_state import CombatState
from condition_restrictions import cannot_act
from session_data import SessionData
from spell_voice_rules import is_silenced


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


@pytest.fixture
async def fight(reset_db_pool: str) -> AsyncIterator[ChoirFight]:
    h = ChoirFight()
    try:
        await h.setup()
        yield h
    finally:
        await h.close()


def aura_events(h: ChoirFight) -> list[Payload]:
    calls = h.publisher.call_args_list
    return [
        event
        for call in calls
        if (event := json.loads(call.args[0])).get("roll_type") == "choir_aura" and event["actor_id"] == h.players[0]
    ]


def resonance(rows: dict[str, Payload]) -> dict[str, int]:
    return {pid: row.get("resonance", {}).get("current", 0) for pid, row in rows.items()}


@pytest.mark.parametrize("seed_value", [0, 1])
async def test_terminal_tool_fight(fight: ChoirFight, seed_value: int, monkeypatch: pytest.MonkeyPatch) -> None:
    h = fight
    rewards = AsyncMock(wraps=combat_rewards.grant_victory_rewards)
    monkeypatch.setattr(combat_rewards, "grant_victory_rewards", rewards)
    death_totals = []
    pre_lethal = []
    accrue = combat_hollow_death.accrue_death

    async def observe_death(
        session: SessionData, state: CombatState, target: CombatParticipant, *, conn: Connection, queries: Any
    ) -> None:
        assert target.id == h.owner_id and target.hollow_death_resolved
        recipients = {
            p.id
            for p in state.participants
            if p.id in h.players[:3]
            and p.hp_current > 0
            and not p.is_dead
            and not p.is_fallen
            and combat_spatial.inside(
                combat_spatial.position(state.spatial, target.id),
                combat_spatial.position(state.spatial, p.id),
                60,
            )
        }
        assert recipients and state.veil_ward is None
        before = await h.player_rows(conn=conn)
        pre_lethal.append(before)
        await accrue(session, state, target, conn=conn, queries=queries)
        after = resonance(await h.player_rows(conn=conn))
        assert after == {pid: value + (5 if pid in recipients else 0) for pid, value in resonance(before).items()}
        death_totals.append(after)

    monkeypatch.setattr(combat_hollow_death, "accrue_death", observe_death)
    with seeded_dice(seed_value):
        cleric = h.players[0]
        await h.command("activate", {"id": "divine_bless", "target_id": cleric})
        assert h.sd.member_state(cleric).concentration.spell_id == "divine_bless"
        response = await h.enter()
        assert not aura_events(h)
        caster = h.state.get_participant(cleric)
        assert caster is not None and not caster.is_fallen and not cannot_act(caster.conditions)
        assert combat_spatial.inside(
            combat_spatial.position(h.state.spatial, h.owner_id),
            combat_spatial.position(h.state.spatial, cleric),
            600,
        )
        assert h.encounter["aura_receipts"] == {}
        assert all(p.hp_current == p.hp_max for p in h.state.participants)
        before = await h.snapshot()
        publisher = h.publisher
        publications = publisher.call_count
        refusal = await h.declare([ability(h.players[1], "arcane_bolt", h.owner_id)], error=True)
        assert "hidden Choir core" in refusal
        assert await h.snapshot() == before and publisher.call_count == publications

        counts: Counter[str] = Counter()
        executions: set[str] = set()
        windows: set[str] = set()
        redirects = 0
        searches: list[bool] = []
        core_hits = 0
        destroyed = False
        before_settlement = None
        for round_number in range(1, 46):
            action = enemy_turn(h, response, counts)
            declarations = await party_turn(
                h, response["choir"], bool(counts["Stolen Melody"]), all(counts[name] for name in KIT)
            )
            await h.declare([*declarations, action])
            declared_casts = {d["actor_id"]: d for d in declarations if d["kind"] == "ability"}
            round_hp = {p.id: p.hp_current for p in h.state.participants}
            round_players = await h.player_rows() if declared_casts else {}
            generated: Counter[str] = Counter()
            for _ in range(24):
                response = await h.command("resolve_phase", {})
                for packet in response.get("packets", []):
                    if (
                        packet.get("actor_id") == h.owner_id
                        and packet.get("resolved")
                        and action["kind"] in {"ability", "attack"}
                    ):
                        receipt = h.owner.last_action_execution
                        assert receipt and receipt["round"] == round_number
                        assert receipt["action"] == action["action"].casefold() and receipt["id"] not in executions
                        executions.add(receipt["id"])
                        counts[action["action"]] += 1
                    if packet.get("action", "").startswith("choir_search_") and "dc" in packet:
                        assert packet["dc"] == 18 and packet["success"] == (packet["total"] >= 18)
                        assert packet["choir"]["phase"] == ("exposed" if packet["success"] else "search")
                        await h.reload()
                        assert h.encounter["phase"] == response["choir"]["phase"]
                        searches.append(packet["success"])
                    pid = packet.get("actor_id")
                    cast = packet.get("cast")
                    if not cast:
                        continue
                    generated[pid] += cast["resonance_generated"]
                    declared = declared_casts.get(pid)
                    if not declared or declared["targets"] != [h.owner_id]:
                        continue
                    for damage in cast.get("damage_results", []):
                        if damage["target_id"] == h.owner_id and damage["damage"] > 0:
                            assert h.owner.hp_current <= damage["target_hp_current"] < round_hp[h.owner_id]
                            core_hits += 1
                        elif damage["target_id"] == pid and damage["damage"] > 0:
                            assert spells.get_spell(declared["action"]).verbal
                            if not redirects:
                                assert damage["target_hp_current"] == round_hp[pid] - damage["damage"]
                                committed = await db_queries.get_player(pid)
                                assert committed is not None
                                assert committed["hp"]["current"] == damage["target_hp_current"]
                                assert committed["focus"]["current"] == (
                                    round_players[pid]["focus"]["current"]
                                    - spells.get_spell(declared["action"]).focus_cost
                                )
                            redirects += 1
                if h.sd.combat_state is None:
                    break
                if not destroyed and response["choir"]["phase"] == "destroyed":
                    assert death_totals and h.owner.hollow_death_resolved and h.owner.hp_current == 0
                    assert all(
                        h.owner.action_ledger[name.casefold()]["remaining"] == 0
                        for name in ("Cacophony", "Silence Void")
                    )
                    await h.reload()
                    before_settlement = await h.player_rows()
                    [lethal] = pre_lethal
                    lethal_balance = resonance(lethal)
                    [death_balance] = death_totals
                    assert resonance(before_settlement) == {
                        pid: value + generated[pid] + death_balance[pid] - lethal_balance[pid]
                        for pid, value in resonance(round_players).items()
                    }
                    destroyed = True
                window = response["next"]["waiting_on"]
                if window and window["window_id"] not in windows:
                    windows.add(window["window_id"])
                    await h.reload()
                    if round_number == 1:
                        assert h.encounter["aura_receipts"].get(cleric) == 1
                        assert len(aura_events(h)) == 1
                h.sd.event_bus.drain()
                if h.state.round_number != round_number:
                    break
            else:
                pytest.fail(f"seed {seed_value}, round {round_number}: hold did not drain: {response}")
            if round_number == 1:
                [event] = aura_events(h)
                assert event["dc"] == 15
                assert h.encounter["aura_receipts"].get(cleric) == 1
                player = await db_queries.get_player(cleric)
                assert player is not None
                assert player["concentration"]["spell_id"] == ("divine_bless" if event["success"] else None)
            if h.sd.combat_state is None:
                break
            for pid in response["death_saves_due"]:
                death = await h.command("request_death_save", {"player_id": pid})
                if h.sd.combat_state is None:
                    response = death
                    break
            if h.sd.combat_state is None:
                break
        else:
            participants = [(p.name, p.hp_current, p.conditions) for p in h.state.participants]
            pytest.fail(
                f"seed {seed_value}: fight did not end at round {h.state.round_number} "
                f"{h.state.beat}, window={h.state.open_window}, kit={counts}, participants={participants}"
            )
        outcome = response["outcome"]
        print(seed_value, round_number, outcome, counts, redirects, len(windows))
        assert outcome in ("victory", "defeat")
        assert all(counts[name] for name in KIT)
        assert counts["Cacophony"] == counts["Silence Void"] == 1
        assert any(searches) and core_hits and redirects and windows
        assert await db_mutations.load_combat_state(h.combat_id) is None
        if outcome == "defeat":
            assert seed_value != 0, "Seed 0 supplies the required victory and settlement evidence"
            rewards.assert_not_awaited()
            return

        assert destroyed and response["choir"]["phase"] == "destroyed" and response["xp_total"] == 3000
        rewards.assert_awaited_once()
        assert len(death_totals) == 1
        [lethal] = pre_lethal
        assert before_settlement is not None
        settled = await h.player_rows()
        assert resonance(settled) == resonance(before_settlement)
        assert all(settled[pid]["xp"] - lethal[pid]["xp"] == 1875 for pid in h.players)
        assert choir_scene.read(settled[cleric], HOME) == {
            "location_id": HOME,
            "source_id": choir_scene.key(HOME),
            "status": "destroyed",
        }
        assert (await h.reopen_home()).get("choir") is None
        refusal = await h.command("enter_mode", {"mode": "combat", "encounter_id": h.encounter_id}, error=True)
        assert "destroyed" in refusal
        assert await h.player_rows() == settled
        rewards.assert_awaited_once()


def assert_available(h: ChoirFight, response: Payload, reason: str | None, *, occupied: bool) -> None:
    owner = h.roster(response)
    action = next(a for a in owner["executable_actions"] if a["id"] == "Dissonant Chord")
    assert action["reason"] == reason and action["available"] is (reason is None)
    [reaction] = owner["automatic_reactions"]
    assert reaction["id"] == "Harmonic Shield" and reaction["available"] is (reason is None)
    assert is_silenced(h.state, h.owner_id) is occupied


async def finish_round(h: ChoirFight, declaration: Payload) -> tuple[Payload, list[Payload]]:
    await h.declare([defend(h.players[0]), declaration])
    round_number = h.state.round_number
    packets = []
    for _ in range(12):
        result = await h.command("resolve_phase", {})
        packets.extend(result["packets"])
        h.sd.event_bus.drain()
        if h.state.round_number != round_number:
            return result, packets
    pytest.fail(f"Choir round {round_number} did not finish")


async def test_silence_suppresses_one_choir_turn_per_own_turn_exposure(
    fight: ChoirFight, monkeypatch: pytest.MonkeyPatch
) -> None:
    import combat_spatial_declarations
    from combat_action_availability import action_summary

    h = fight
    with seeded_dice(0) as rng:
        entry = await h.enter()
        assert_available(h, entry, None, occupied=False)
        inside = combat_spatial.position(h.state.spatial, h.owner_id)
        outside = {**inside, "x": inside["x"] + 5}
        target = h.players[0]
        response, packets = await finish_round(h, ability(h.owner_id, "Silence Void", target))
        [created] = [p for p in packets if "silence_zone" in p]
        zone_id = created["silence_zone"]
        zone = h.state.choir_silences[zone_id]
        assert (zone["inflicted_round"], zone["expires_round"]) == (1, 5)
        assert combat_spatial.require_spatial(h.state)["zones"][zone_id]["radius_ft"] == 30
        assert created["center"] == combat_spatial.position(h.state.spatial, target)
        assert h.owner.action_ledger["silence void"]["remaining"] == 0

        placements: list[tuple[int, bool, bool]] = []
        place = combat_spatial_declarations.place

        def observe_placement(state: CombatState, actor_id: str, destination: Payload) -> None:
            place(state, actor_id, destination)
            if actor_id == h.owner_id:
                owner = state.get_participant(actor_id)
                assert owner is not None
                placements.append(
                    (
                        state.round_number,
                        is_silenced(state, actor_id),
                        action_summary(owner)["automatic_reactions"][0]["available"],
                    )
                )

        monkeypatch.setattr(combat_spatial_declarations, "place", observe_placement)
        for suppressed_round, occupied in [(2, True), (5, False)]:
            assert h.state.round_number == suppressed_round
            await h.reload()
            assert h.owner.action_ledger["silence void"]["remaining"] == 0
            assert_available(h, response, "suppressed", occupied=occupied)
            action = next(a for a in h.roster(response)["executable_actions"] if a["id"] == "Dissonant Chord")
            attack = enemy_declaration(h.owner_id, action, target)
            before = await h.snapshot()
            dice_before = rng.getstate()
            assert "Choir abilities are suppressed" in await h.declare([attack], error=True)
            assert rng.getstate() == dice_before and await h.snapshot() == before

            response, _ = await finish_round(h, move(h.owner_id, outside) if occupied else defend(h.owner_id))
            assert h.state.round_number == suppressed_round + 1
            assert_available(h, response, None, occupied=False)
            response, packets = await finish_round(h, attack)
            assert any(p.get("action") == "Dissonant Chord" and p["resolved"] for p in packets)
            if occupied:
                assert h.state.choir_silences[zone_id] == zone
                response, _ = await finish_round(h, move(h.owner_id, inside))
                assert h.state.choir_silences == {}
        assert placements == [(2, False, False), (4, True, False)]
