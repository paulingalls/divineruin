import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.seeds import seed_known_spells
from acceptance.test_still_anchors import declare, destroy, enter, fresh_session, search_round, spell, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import still as still
from sample_fixtures import published_payloads

import db_mutations
import db_queries
import event_types as E
import spells
from check_resolution import D20Roll


async def reveal_and_wake(still, count=1):
    response, initial = await enter(still)
    record = initial.still_encounter
    search = response["still"]["search_actions"][0]
    for _ in range(count):
        await search_round(still, search)
    await declare(still, **strike(record["anchor_ids"][0]))
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        await still.drain()
    return await still.reload()


async def stored_charm(still):
    player = await db_queries.get_player(still.players[0])
    assert player is not None
    key = f"still_charm:{still.sd.location_id}"
    return json.loads(player["flags"][key]) if key in player["flags"] else None


async def assert_charm_survives_flee(still, kind, hours):
    expected = dict(location_id=still.sd.location_id, kind=kind, remaining_zone_hours=hours) if kind else None
    assert await stored_charm(still) == expected
    await fresh_session(still, await still.reload())
    await still.command("end_combat", {"outcome": "fled"})
    assert await stored_charm(still) == expected


@pytest.mark.parametrize("existing_kind", [None, "paradise_trap"])
async def test_touch_charms_and_memory_keeps_charm_while_disabling_next_turn(still, existing_kind):
    await seed_known_spells(still.pool, still.players[0], ("arcane_bolt", "arcane_elemental_burst"))
    state = await reveal_and_wake(still, count=2)
    owner_id = state.still_encounter["owner_id"]
    player_id = still.players[0]
    if existing_kind:
        await db_mutations.set_player_flag(
            player_id,
            f"still_charm:{state.location_id}",
            json.dumps(dict(location_id=state.location_id, kind=existing_kind, remaining_zone_hours=None)),
        )
    player = state.get_participant(player_id)
    player.ac = 100
    state.spatial["positions"][player_id] = {**state.spatial["positions"][owner_id], "x": 120}
    inside = state.spatial["positions"][player_id]
    owner_position = state.spatial["positions"][owner_id]
    aura = state.get_participant(owner_id).hollow["corruption_aura"]
    state.spatial["positions"][player_id] = {**owner_position, "x": owner_position["x"] + aura + 1}
    state = await still.persist()
    touch = strike(player_id, action="Serenity's Touch")
    assert "outside the Still's zone" in await declare(still, actor_id=owner_id, error=True, **touch)
    state.spatial["positions"][player_id] = inside
    await still.persist()
    await declare(still, actor_id=owner_id, **touch)
    events_before = len(published_payloads(still.sd.room))
    with (
        patch("dice.roll", return_value=SimpleNamespace(total=7)) as damage,
        patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1)),
        patch("check_resolution_attack.resolve_attack", side_effect=AssertionError("Touch rolled to hit")),
    ):
        packets = await still.drain()
    assert damage.call_args_list[0].args == ("2d6",)
    result = next(p for p in packets if p.get("action") == "Serenity's Touch")
    assert (result["damage"], result["damage_type"], result["save_dc"], result["charmed"]) == (7, "psychic", 20, True)
    assert not [event for event in published_payloads(still.sd.room)[events_before:] if event["type"] == E.DICE_ROLL]

    state = await still.reload()
    await fresh_session(still, state)
    anchors = state.still_encounter["revealed_ids"]
    for anchor in anchors:
        assert "Charmed" in await declare(still, **strike(anchor), error=True)
        assert "Charmed" in await declare(still, **spell("arcane_bolt", anchor), error=True)
        burst = spell("arcane_elemental_burst", anchor) | {"argument_type": "fire"}
        assert "Charmed" in await declare(still, **burst, error=True)
    player = still.sd.combat_state.get_participant(player_id)
    player.ac = 20
    assert player.hp_current == 93
    await still.persist()
    await declare(still, actor_id=owner_id, **strike(player_id, action="Perfect Memory"))
    with (
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(12)),
        patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(8 if self.modifier == 12 else 1)),
    ):
        packets = await still.drain()
    result = next(p for p in packets if p.get("action") == "Perfect Memory")
    assert result["hit"], result
    assert (result["damage"], result["damage_type"], result["save_dc"]) == (12, "psychic", 20)
    assert "stunned" in await declare(still, kind="defend", reshape=[], error=True)
    await declare(still, actor_id=owner_id, kind="defend", reshape=[])
    await still.drain()
    assert "Charmed" in await declare(still, **strike(anchors[-1]), error=True)
    await assert_charm_survives_flee(still, existing_kind or "serenitys_touch", None if existing_kind else 1)


@pytest.mark.parametrize("duration,face", [(1, 20), (3, 20), (3, 1)])
async def test_final_stillness_threshold_and_single_use(still, duration, face):
    response, state = await enter(still)
    record = state.still_encounter
    owner = record["owner_id"]
    search = response["still"]["search_actions"][0]
    final = spell("Final Stillness")
    for index, anchor in enumerate(record["anchor_ids"][:4]):
        await search_round(still, search)
        await destroy(still, anchor)
        if index == 2:
            assert "unavailable" in await declare(still, actor_id=owner, error=True, **final)
    if face == 1:
        await db_mutations.set_player_flag(
            still.players[0],
            f"still_charm:{state.location_id}",
            json.dumps(dict(location_id=state.location_id, kind="serenitys_touch", remaining_zone_hours=1)),
        )
        actor = (await still.reload()).get_participant(still.players[0])
        actor.has_reaction_ability = True
        actor.reaction_ids = ["whisper_implant_doubt"]
        await still.persist()
    await declare(still, actor_id=owner, **final)
    if face == 1:
        await still.command("resolve_phase", {})
        paused = await still.command("resolve_phase", {})
        assert paused["next"]["waiting_on"]["action"] == "Final Stillness"
        await fresh_session(still, await still.reload())
    with (
        patch("dice.roll", return_value=SimpleNamespace(total=duration)) as roll,
        patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(face)),
    ):
        packets = await still.drain()
    assert roll.call_args_list[0].args == ("1d4",)
    packet = next(p for p in packets if p.get("action") == "Final Stillness")
    (target,) = packet["targets"]
    success = face == 20
    assert (target["save_type"], target["save_dc"], target["save_success"]) == ("wisdom", 22, success)
    assert target.get("stunned_rounds", 0) == (duration // 2 if success else duration)
    assert target.get("charmed", False) is not success
    await fresh_session(still, await still.reload())
    assert "unavailable" in await declare(still, actor_id=owner, error=True, **final)
    if success and duration == 1:
        await search_round(still, search)
        await destroy(still, record["anchor_ids"][4])
        assert "unavailable" in await declare(still, actor_id=owner, error=True, **final)
    await assert_charm_survives_flee(still, None if success else "final_stillness", None)


async def test_illusion_investigation_updates_only_after_commit(still, monkeypatch):
    await still.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{attributes,intelligence}','18') WHERE player_id=$1",
        still.players[0],
    )
    state = await reveal_and_wake(still)
    illusion = still.last_result["still"]["illusion"]
    assert (illusion["target_id"], illusion["round"], illusion["dc"]) == (still.players[0], state.round_number, 22)
    payload = {"roll": illusion["check"]}

    def total(target_total):
        def roll(spec, _rng=None):
            face = target_total - spec.modifier
            assert 1 < face < 20
            return spec.evaluate(face)

        return roll

    with patch.object(D20Roll, "roll", total(21)):
        failed = await still.command("check", payload)
    assert (failed["total"], failed["dc"], failed["seen_through"]) == (21, 22, False)

    save = db_mutations.save_combat_state
    before = (await still.reload()).to_dict()
    events = published_payloads(still.sd.room)

    async def fail_after_write(combat_id, data, *, conn=None):
        assert data["still_encounter"]["illusion"]["seen_through"] is True
        await save(combat_id, data, conn=conn)
        raise RuntimeError("injected illusion commit failure")

    with patch.object(D20Roll, "roll", total(22)):
        with monkeypatch.context() as fault:
            fault.setattr(db_mutations, "save_combat_state", fail_after_write)
            await still.command("check", payload, error=True)
        assert (await still.reload()).to_dict() == before
        assert published_payloads(still.sd.room) == events
        succeeded = await still.command("check", payload)
    assert (succeeded["total"], succeeded["dc"], succeeded["seen_through"]) == (22, 22, True)
    await fresh_session(still, await still.reload())
    assert (await still.reload()).still_encounter["illusion"]["seen_through"] is True


async def test_spell_paths_arm_the_resolved_anchor_and_use_typed_and_divine_vulnerability(still, monkeypatch):
    player = still.players[0]
    flame = "divine_sacred_flame"
    await still.pool.execute(
        "UPDATE players SET data=jsonb_set(data || $2::jsonb,'{focus,current}','100') WHERE player_id=$1",
        player,
        json.dumps({"class": "mage"}),
    )
    await seed_known_spells(
        still.pool, player, ("arcane_bolt", "arcane_magic_missile", "arcane_elemental_burst", flame)
    )
    response, state = await enter(still)
    anchors = state.still_encounter["anchor_ids"]
    for _ in anchors:
        await search_round(still, response["still"]["search_actions"][0])
    for index, name in enumerate(("arcane_bolt", "arcane_magic_missile", "arcane_elemental_burst")):
        target = anchors[index]
        action = spell(name, target)
        if name == "arcane_elemental_burst":
            action["argument_type"] = "fire"
        prior = (await still.reload()).still_encounter["pending_rejection"]
        await declare(still, **action)
        with (
            patch("check_resolution.dice_roll", return_value=_d20(20)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
            patch("dice.roll", return_value=SimpleNamespace(total=3)),
        ):
            packets = await still.drain()
        state = await still.reload()
        trigger = state.still_encounter["pending_rejection"]
        assert trigger["execution_id"] != (prior or {}).get("execution_id")
        damages = next(packet["cast"]["damage_results"] for packet in packets if "cast" in packet)
        recipients = [damage for damage in damages if damage["target_id"] in anchors]
        assert recipients and recipients[0]["target_id"] == target
        assert trigger["anchor_id"] == recipients[-1]["target_id"]
        if name == "arcane_elemental_burst":
            assert len(recipients) > 1
            for damage in recipients:
                assert damage["damage"] == (2 if damage["save"]["success"] else 6)

    raw = next(
        row
        for row in json.loads((Path(__file__).resolve().parents[4] / "content/spells.json").read_text())
        if row["id"] == flame
    )
    base = await _flame_damage(still, flame, anchors[3])
    raw["combat_damage"]["components"][0]["damage_type"] = "force"
    with monkeypatch.context() as catalog:
        catalog.setitem(spells._spells, flame, spells.parse_spell_row(flame, raw))
        divine = await _flame_damage(still, flame, anchors[4])
        raw.update(source="arcane", resonance_by_source={"arcane": 0})
        catalog.setitem(spells._spells, flame, spells.parse_spell_row(flame, raw))
        arcane = await _flame_damage(still, flame, anchors[5])
    assert base == divine == 2 * arcane > 0


async def _flame_damage(still, name, target):
    before = (await still.reload()).get_participant(target).hp_current
    await declare(still, **spell(name, target))
    with (
        patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1)),
        patch("dice.roll", return_value=SimpleNamespace(total=3)),
    ):
        packets = await still.drain()
    landed = next(packet["cast"]["damage_result"] for packet in packets if "cast" in packet)
    after = (await still.reload()).get_participant(target).hp_current
    assert landed["damage"] == before - after
    return landed["damage"]
