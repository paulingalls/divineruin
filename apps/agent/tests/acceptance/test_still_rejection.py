from types import SimpleNamespace
from unittest.mock import patch

from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_still_anchors import declare, destroy, enter, fresh_session, search_round, spell, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import still as still

import combat_spatial
import still_encounter
from check_resolution import D20Roll
from combat_participant import CombatParticipant


async def test_anchor_miss_wakes_still_only_when_resolved(still):
    response, state = await enter(still)
    owner = state.still_encounter["owner_id"]
    anchor = state.still_encounter["anchor_ids"][0]
    memory = strike(still.players[0], action="Perfect Memory")
    assert next(row for row in response["participants"] if row["id"] == owner)["actions"] == []
    assert "take no actions" in await declare(still, actor_id=owner, error=True, **memory)
    await search_round(still, response["still"]["search_actions"][0])
    await declare(still, **strike(anchor))
    assert (await still.reload()).still_encounter.get("pending_rejection") is None
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        packets = await still.drain()
    assert any(packet.get("hit") is False for packet in packets)
    state = await still.reload()
    assert state.get_participant(anchor).hp_current == 40
    assert state.still_encounter["pending_rejection"]["anchor_id"] == anchor
    roster = await declare(still, actor_id=owner, **memory)
    actions = next(row for row in roster["participants"] if row["id"] == owner)["actions"]
    assert {"Serenity's Touch", "Perfect Memory"} <= set(actions)


async def test_rejection_only_recharges_with_a_pending_anchor_attack(still):
    response, state = await enter(still)
    owner_id = state.still_encounter["owner_id"]
    first, anchor = state.still_encounter["anchor_ids"][:2]
    search = response["still"]["search_actions"][0]
    with patch("combat_recharge.roll") as dice:
        await search_round(still, search)
        await search_round(still, search)
    dice.assert_not_called()
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)):
        await destroy(still, first)
    await declare(still, **strike(anchor))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)) as dice,
    ):
        await still.drain()
    dice.assert_called_once_with("1d6")
    rejection = spell("Rejection")
    await declare(still, actor_id=owner_id, error=True, **rejection)
    with patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)):
        await declare(still, kind="defend")
        await still.drain()
    state = await still.reload()
    owner = state.get_participant(owner_id)
    player = state.get_participant(still.players[0])
    player.has_reaction_ability = True
    player.reaction_ids = ["whisper_implant_doubt"]
    origin = state.spatial["positions"][anchor]
    state.spatial["positions"][player.id] = {**origin, "y": origin["y"] - 30}
    for name, offset in (("inside", 25), ("outside", 31)):
        participant = CombatParticipant(
            id=name, name=name, type="companion", initiative=30, hp_current=100, hp_max=100, ac=12, tier=1
        )
        state.participants.append(participant)
        state.initiative_order.insert(0, participant.id)
        state.spatial["positions"][participant.id] = {**origin, "x": origin["x"] + offset}
        state.spatial["speeds"][participant.id] = 30
    before_position = state.spatial["positions"][player.id]
    owner_center = state.spatial["positions"][owner.id]
    assert not combat_spatial.inside(before_position, owner_center, 30)
    await still.persist()
    await declare(still, actor_id=owner_id, **rejection)
    await still.command("resolve_phase", {})
    paused = await still.command("resolve_phase", {})
    assert "whisper_implant_doubt" in [reaction["id"] for reaction in paused["next"]["waiting_on"]["reactions"]]
    state = await still.reload()
    anchors_before = [state.get_participant(a).hp_current for a in state.still_encounter["anchor_ids"]]
    revealed = state.still_encounter["revealed_ids"]
    trigger = state.still_encounter["pending_rejection"]
    await fresh_session(still, state)
    assert (await still.reload()).still_encounter["pending_rejection"] == trigger
    await still.pool.execute(
        """UPDATE players SET data=data || $2::jsonb WHERE player_id=$1""",
        player.id,
        '{"divine_favor":{"patron":"zhael","level":0,"max":100,"last_whisper_level":0},'
        '"patron_gifts":{"zhael_fates_thread":{"spent":true}}}',
    )
    rolled = []

    def save_face(roll, _rng=None):
        rolled.append(roll.dc)
        return roll.evaluate(20 if len(rolled) == 1 else 1)

    with (
        patch("combat_recharge.roll", return_value=SimpleNamespace(total=4)) as dice,
        patch.object(D20Roll, "roll", save_face),
    ):
        offered = await still.command("resolve_phase", {})
        assert offered["fate_offer"]["roller_id"] == player.id
        state = await still.reload()
        assert state.held_actions[0]["still_zone"]["results"][0]["stunned_rounds"] == 1
        assert state.held_actions[0]["still_zone"]["trigger"] == trigger
        still_encounter.record_attack(state, player, state.get_participant(anchor), strike(anchor))
        newer = state.still_encounter["pending_rejection"]
        assert newer["execution_id"] != trigger["execution_id"]
        await still.persist()
        await fresh_session(still, state)
        packets = await still.drain()
    assert rolled == [20, 20]
    dice.assert_called_once_with("1d6")
    result = next(packet for packet in packets if packet.get("action") == "Rejection")
    assert result["origin_anchor_id"] == anchor
    success, target = result["targets"]
    assert (success["target_id"], success["save_success"], success["stunned_rounds"]) == ("inside", True, 1)
    assert (target["target_id"], target["save_type"], target["save_dc"], target["save_success"]) == (
        player.id,
        "wisdom",
        20,
        False,
    )
    state = await still.reload()
    edge = state.spatial["positions"][player.id]
    assert edge == target["destination"]
    assert combat_spatial.distance(edge, owner_center) == owner.hollow["corruption_aura"]
    assert state.still_encounter["pending_rejection"] == newer
    assert state.still_encounter["revealed_ids"] == revealed
    assert [state.get_participant(a).hp_current for a in state.still_encounter["anchor_ids"]] == anchors_before
    assert state.get_participant(first).is_fallen and anchors_before[0] == 0
    assert not state.get_participant("outside").conditions
    assert state.spatial["positions"]["inside"] == {**origin, "x": origin["x"] + 25}
    assert not state.held_actions
    assert state.get_participant(player.id).hp_current == player.hp_current
    refusal = await declare(still, kind="move", destination=before_position, error=True)
    assert "exceeds speed" in refusal
    refusal = await declare(still, actor_id=owner_id, error=True, **strike(player.id, action="Perfect Memory"))
    assert "outside the Still's attack range" in refusal
    await declare(still, kind="move", destination={**edge, "y": edge["y"] + 1})


async def test_two_party_attacks_replace_the_pending_origin_and_thunder_doubles(reset_db_pool):
    from acceptance.mawling_harness import MawlingHarness

    party = MawlingHarness()
    try:
        await party.prepare((18, 18), companion=None, location="ashmark_corrupted_front")
        response, state = await enter(party)
        first, second = state.still_encounter["anchor_ids"][:2]
        for _ in range(2):
            await search_round(party, response["still"]["search_actions"][0])
        state = await party.reload()
        player_a, player_b = [state.get_participant(pid) for pid in party.players]
        assert player_a is not None and player_b is not None
        assert state.still_encounter is not None
        state.initiative_order = [
            player_a.id,
            player_b.id,
            *[pid for pid in state.initiative_order if pid not in party.players],
        ]
        player_a.initiative = 30
        player_b.initiative = 29
        next(action for action in player_b.action_pool if action["name"] == "Longsword")["damage_type"] = "thunder"
        await party.persist()
        await party.command(
            "declare_phase",
            {
                "declarations": [
                    {"actor_id": player_a.id, **strike(first)},
                    {"actor_id": player_b.id, **strike(second)},
                ]
            },
        )
        with (
            patch("check_resolution.dice_roll", return_value=_d20(20)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
            patch("combat_recharge.roll", return_value=SimpleNamespace(total=6)),
        ):
            packets = await party.drain()
        normal, thunder = [packet for packet in packets if "hit" in packet]
        assert thunder["damage"] == 2 * normal["damage"] > 0
        persisted = (await party.reload()).still_encounter
        assert persisted is not None and persisted["pending_rejection"]["anchor_id"] == second
        owner_id = state.still_encounter["owner_id"]
        await declare(party, actor_id=owner_id, **spell("Rejection"))
        packets = await party.drain()
        assert next(packet for packet in packets if packet.get("action") == "Rejection")["origin_anchor_id"] == second
    finally:
        await party.close()


async def test_only_the_illusion_target_may_investigate_it(reset_db_pool):
    from acceptance.mawling_harness import MawlingHarness

    party = MawlingHarness()
    try:
        await party.prepare((18, 18), companion=None, location="ashmark_corrupted_front")
        response, state = await enter(party)
        await search_round(party, response["still"]["search_actions"][0])
        await declare(party, **strike(state.still_encounter["anchor_ids"][0]))
        with patch("check_resolution.dice_roll", return_value=_d20(1)):
            await party.drain()
        illusion = party.last_result["still"]["illusion"]
        (bystander,) = [pid for pid in party.players if pid != illusion["target_id"]]
        party.model.commands.append(("check", {"roll": illusion["check"]}))
        with (
            party.sd._bind_authenticated_actor(bystander, 1, lambda *_: None),
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(20)),
        ):
            await party.session.run(user_input="Execute the next command.")
        receipt = list(party.model.receipts.values())[-1]
        assert receipt.name == "check" and receipt.is_error, receipt.output
        assert "Only the creature experiencing the Still illusion" in receipt.output
        record = (await party.reload()).still_encounter
        assert record is not None and record["illusion"]["seen_through"] is False
    finally:
        await party.close()
