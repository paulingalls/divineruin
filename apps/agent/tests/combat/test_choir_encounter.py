import json
from unittest.mock import AsyncMock

import pytest
from sample_fixtures import CONTENT_ROOT, load_test_creature, make_context, make_db_mod

import combat_init
from tests.combat.test_start_combat import _make_start_combat_mocks


async def start_choir():
    mutations, queries, content = _make_start_combat_mocks()
    mutations.set_player_flag = AsyncMock()
    content.get_encounter_template = AsyncMock(
        return_value=next(
            row
            for row in json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
            if row["id"] == "hollow_choir"
        )
    )
    content.load_creature_enemy = load_test_creature
    ctx = make_context()
    _, raw = await combat_init._start_combat_impl(
        ctx, "hollow_choir", "voices", mutations=mutations, queries=queries, content=content, db_mod=make_db_mod()[0]
    )
    return ctx, json.loads(raw), mutations, queries


@pytest.mark.asyncio
async def test_choir_seeded_enter_mode_starts_search(mock_combat_agent_factory):
    ctx, response, mutations, _ = await start_choir()
    assert response.get("choir", {}).get("phase") == "search"
    facts = response["choir"]
    assert facts["search_target_id"] == "choir_sound"
    assert {a["action"] for a in facts["search_actions"]} == {"choir_search_perception", "choir_search_arcana"}
    assert "core_id" not in facts
    enemy = next(p for p in ctx.userdata.combat_state.participants if p.type == "enemy")
    assert (enemy.hp_current, enemy.hp_max, enemy.ac, enemy.xp_value, enemy.role) == (200, 200, 18, 3000, "named")
    assert mutations.save_combat_state.call_args.args[1]["choir_encounter"]["phase"] == "search"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,targets",
    [
        ("attack", {"action": "Longsword", "target_id": "choir_zone"}),
        ("ability", {"action": "arcane_bolt", "target_id": "choir_zone"}),
        ("ability", {"action": "divine_bless", "target_ids": ["player_1", "choir_zone"]}),
        ("maneuver", {"target_id": "choir_zone"}),
        ("attack", {"action": "Longsword", "target_id": "choir_sound"}),
        ("attack", {"action": "Longsword", "target_id": "choir_zone_core"}),
    ],
)
async def test_choir_hidden_core_refused_on_every_target_path(kind, targets, mock_combat_agent_factory):
    from livekit.agents.llm import ToolError

    import combat_turn

    ctx, _, mutations, _ = await start_choir()
    before = ctx.userdata.combat_state.to_dict()
    mutations.save_combat_state.reset_mock()
    with pytest.raises(ToolError, match="Choir"):
        await combat_turn._declare_phase_impl(ctx, {"player_1": {"type": kind, **targets}}, mutations=mutations)
    assert ctx.userdata.combat_state.to_dict() == before
    mutations.save_combat_state.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", ["perception", "arcana"])
@pytest.mark.parametrize("face,success", [(1, False), (20, True)])
@pytest.mark.parametrize("tier", ["untrained", "trained", "expert", "master"])
async def test_choir_search_success_and_failure_spend_action(skill, face, success, tier, mock_combat_agent_factory):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20

    import combat_packet
    from combat_phase import ResolutionPacket
    from declarations import resolve_declaration

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    actor = state.get_participant("player_1")
    from rules_engine import skill_modifier

    player = {
        **queries.get_player.return_value,
        "level": 16,
        "attributes": {"wisdom": 14, "intelligence": 18},
        "skill_tiers": {skill: tier},
    }
    queries.get_player.return_value = player
    decl = resolve_declaration({"type": "interact", "action": f"choir_search_{skill}", "target_id": "choir_sound"})
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        packet = await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            ResolutionPacket(actor_id=actor.id, declaration=decl, initiative=actor.initiative),
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=None,
        )
    assert packet["resolved"] is True
    assert packet["success"] is success
    assert packet["dc"] == 18
    assert packet["modifier"] == skill_modifier(player, skill)
    assert packet["auto_fail"] is False
    assert state.choir_encounter["phase"] == ("exposed" if success else "search")
    assert ("core_id" in packet["choir"]) is success
    if success:
        stale = await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            ResolutionPacket(actor.id, decl, actor.initiative),
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=None,
        )
        assert stale["resolved"] is False and state.choir_encounter["phase"] == "exposed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage_type,expected",
    [
        ("slashing", 0),
        ("piercing", 0),
        ("bludgeoning", 0),
        ("fire", 0),
        ("cold", 0),
        ("necrotic", 0),
        ("force", 10),
        ("thunder", 10),
        ("psychic", 20),
        ("radiant", 20),
    ],
)
async def test_choir_core_attack_damage_policy(damage_type, expected, mock_combat_agent_factory):
    from check_resolution_attack import AttackResult
    from combat_support import apply_attack_result

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    state.choir_encounter["phase"] = "exposed"
    actor, target = state.get_participant("player_1"), state.get_participant("choir_zone")
    roll = AttackResult(True, 15, 5, 20, 18, 10, damage_type, 190, False, "hit")
    packet = await apply_attack_result(
        ctx.userdata,
        actor,
        {"name": "type-policy strike"},
        target,
        roll,
        18,
        mutations=mutations,
        queries=queries,
        combat_state=state,
    )
    assert packet["damage"] == expected
    assert target.hp_current == 200 - expected


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["search", "exposed"])
async def test_choir_search_and_exposed_reload(phase, mock_combat_agent_factory):
    from session_data import CombatState

    ctx, _, _, _ = await start_choir()
    state = ctx.userdata.combat_state
    state.choir_encounter["phase"] = phase
    assert CombatState.from_dict(state.to_dict()).to_dict() == state.to_dict()
    for defect in [
        "missing",
        "bad_phase",
        "dangling",
        "false_destroyed",
        "bad_receipt",
        "unknown_receipt",
        "future_receipt",
    ]:
        data = state.to_dict()
        if defect == "missing":
            data.pop("choir_encounter")
        elif defect == "bad_phase":
            data["choir_encounter"]["phase"] = "invalid"
        elif defect == "dangling":
            data["choir_encounter"]["owner_id"] = "absent"
        elif defect == "false_destroyed":
            data["choir_encounter"]["phase"] = "destroyed"
        else:
            actor = "unknown" if defect == "unknown_receipt" else "player_1"
            turn = False if defect == "bad_receipt" else state.round_number + 1 if defect == "future_receipt" else 1
            data["choir_encounter"]["aura_receipts"] = {actor: turn}
        with pytest.raises(ValueError, match="Choir"):
            CombatState.from_dict(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["search", "exposed"])
@pytest.mark.parametrize("distance,eligible", [(600, True), (600.01, False)])
async def test_choir_aura_turn_start_once_across_hold_resume(phase, distance, eligible, mock_combat_agent_factory):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    import combat_packet
    from combat_phase import ResolutionPacket
    from declarations import resolve_declaration
    from session_data import CombatState

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    state.choir_encounter["phase"] = phase
    actor = state.get_participant("player_1")
    state.spatial["positions"][actor.id] = {"x": 30 + distance, "y": 0, "z": 0}
    ctx.userdata.party.primary.concentration.spell_id = "divine_bless"
    end = MagicMock(end_concentration=AsyncMock(return_value="divine_bless"))
    packet = ResolutionPacket(
        actor_id=actor.id, declaration=resolve_declaration({"type": "defend"}), initiative=actor.initiative
    )
    with patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=False)) as save:
        await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            packet,
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=end,
        )
        state = CombatState.from_dict(state.to_dict())
        await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            packet,
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=end,
        )
    assert save.call_count == int(eligible)
    assert end.end_concentration.await_count == int(eligible)
    if eligible:
        assert save.call_args.args[1:3] == ("wisdom", 15)
        assert save.call_args.kwargs["bonus_dice_eligible"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("species", ["hollow_still", "hollow_architect", "custom_named"])
@pytest.mark.parametrize("role", ["standard", "boss", "named"])
async def test_named_entry_rejects_unsupported_before_effects(species, role, mock_combat_agent_factory, monkeypatch):
    from copy import deepcopy
    from unittest.mock import MagicMock

    from livekit.agents.llm import ToolError
    from sample_fixtures import TEST_CREATURES

    from creature_combat import translate_creature

    row = deepcopy(TEST_CREATURES["hollow_choir" if species == "custom_named" else species])
    row["id"] = species
    mutations, queries, content = _make_start_combat_mocks()
    template = next(
        row
        for row in json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
        if row["id"] == "hollow_choir"
    )
    template["enemies"][0].update(creature_id=species, role=role)
    content.get_encounter_template = AsyncMock(return_value=template)

    async def load(_id, **kwargs):
        return translate_creature(row, **kwargs)

    content.load_creature_enemy = load
    initiative = MagicMock(wraps=combat_init.combat_resolution.roll_initiative)
    monkeypatch.setattr(combat_init.combat_resolution, "roll_initiative", initiative)
    ctx = make_context()
    with pytest.raises(ToolError, match="unsupported"):
        await combat_init._start_combat_impl(
            ctx, "unsupported", "test", mutations=mutations, queries=queries, content=content
        )
    initiative.assert_not_called()
    mutations.save_combat_state.assert_not_called()
    mock_combat_agent_factory.assert_not_called()
    assert ctx.userdata.combat_state is None
    with pytest.raises(ValueError, match="unsupported"):
        translate_creature(row, encounter_id="direct", enemy_id="one", role=role)


@pytest.mark.asyncio
@pytest.mark.parametrize("skill,auto_fail", [("perception", True), ("arcana", False)])
async def test_choir_search_typed_hearing_contract(skill, auto_fail, mock_combat_agent_factory):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _d20

    import combat_packet
    from combat_phase import ResolutionPacket
    from declarations import resolve_declaration

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    actor = state.get_participant("player_1")
    actor.conditions = [{"type": "deafened", "duration": 10, "source": "test"}]
    packet = ResolutionPacket(
        actor_id=actor.id,
        declaration=resolve_declaration(
            {
                "type": "interact",
                "action": f"choir_search_{skill}",
                "target_id": "choir_sound",
            }
        ),
        initiative=actor.initiative,
    )
    with patch("check_resolution.dice_roll", return_value=_d20(20)) as roll:
        result = await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            packet,
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=None,
        )
    assert result["resolved"] and result["auto_fail"] is auto_fail
    assert result["success"] is not auto_fail
    assert roll.call_count == (1 if auto_fail else 2)


@pytest.mark.asyncio
async def test_choir_core_touch_and_condition_immunities(mock_combat_agent_factory):
    from livekit.agents.llm import ToolError

    import combat_turn
    from combat_condition_landing import _land_condition_on_one

    ctx, _, mutations, _ = await start_choir()
    state = ctx.userdata.combat_state
    state.choir_encounter["phase"] = "exposed"
    for spell in ["arcane_frost_touch", "divine_revivify", "primal_healing_touch"]:
        with pytest.raises(ToolError, match="touch"):
            await combat_turn._declare_phase_impl(
                ctx, {"player_1": {"type": "ability", "action": spell, "target_id": "choir_zone"}}, mutations=mutations
            )
    actor, source = state.get_participant("player_1"), state.get_participant("choir_zone")
    for condition in ["grappled", "restrained"]:
        assert not _land_condition_on_one(state, source.id, actor, condition, "test", packet={})
    assert source.conditions == []


@pytest.mark.asyncio
async def test_choir_aura_movement_uses_turn_start_position(mock_combat_agent_factory):
    from types import SimpleNamespace
    from unittest.mock import patch

    import combat_packet
    from combat_phase import ResolutionPacket
    from declarations import resolve_declaration

    ctx, _, mutations, queries = await start_choir()
    state = ctx.userdata.combat_state
    actor = state.get_participant("player_1")
    state.spatial["positions"][actor.id] = {"x": 629, "y": 0, "z": 0}
    move = resolve_declaration(
        {"type": "maneuver", "action": "move", "target_id": actor.id, "destination": {"x": 659, "y": 0, "z": 0}}
    )
    with patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=True)) as save:
        await combat_packet._resolve_one_packet(
            ctx.userdata,
            state,
            ResolutionPacket(actor.id, move, actor.initiative),
            mutations=mutations,
            queries=queries,
            resolver=None,
            concentration_break_mod=None,
        )
    assert save.call_count == 1
    assert state.spatial["positions"][actor.id]["x"] == 659


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect", ["encoding", "location", "status", "source", "pointer", "owner", "hp", "phase", "round"]
)
async def test_choir_scene_receipts_fail_loud(defect, mock_combat_agent_factory):
    from dataclasses import asdict

    import choir_scene

    ctx, _, _, queries = await start_choir()
    location = ctx.userdata.location_id
    source = ctx.userdata.combat_state.get_participant("choir_zone")
    assert source is not None
    record = {
        "source_id": choir_scene.key(location),
        "location_id": location,
        "status": "dormant",
        "owner": asdict(source),
        "phase": "search",
        "round": 1,
    }
    if defect == "encoding":
        raw = record
    else:
        if defect in {"location", "status", "source"}:
            record[{"location": "location_id", "source": "source_id", "status": "status"}[defect]] = "wrong"
            if defect == "status":
                record = {key: value for key, value in record.items() if key in {"source_id", "location_id", "status"}}
        elif defect == "pointer":
            record = {"source_id": record["source_id"], "location_id": location, "status": "combat", "combat_id": None}
        elif defect == "owner":
            record["owner"]["creature_id"] = "bandit"
        elif defect == "hp":
            record["owner"]["hp_current"] = 0
        elif defect == "phase":
            record["phase"] = "destroyed"
        else:
            record["round"] = False
        raw = json.dumps(record)
    queries.get_player.return_value = {"flags": {choir_scene.key(location): raw}}
    with pytest.raises(ValueError, match="Choir"):
        await choir_scene.load(ctx.userdata, queries=queries)


@pytest.mark.asyncio
async def test_choir_destroyed_removes_only_source_owned_effects(mock_combat_agent_factory):
    import choir_encounter
    from choir_effects import inflict_silence
    from combat_hollow_death import mark_destroyed
    from declarations import resolve_declaration

    ctx, response, _, _ = await start_choir()
    state = ctx.userdata.combat_state
    source = state.get_participant("choir_zone")
    state.choir_encounter["phase"] = "exposed"
    inflict_silence(
        state,
        source,
        {"radius_ft": 30, "rounds": 3},
        resolve_declaration({"type": "attack", "action": "Silence Void", "target_id": source.id}),
    )
    assert state.choir_silences and source.choir_suppression
    actor = state.get_participant("player_1")
    actor.conditions = [{"type": "charmed", "source": source.id}, {"type": "blessed", "source": "other"}]
    exposed = choir_encounter.facts(state)
    assert exposed is not None
    assert "30 feet east" in exposed["cue"]
    assert "Memory Predator" in response["choir"]["targeting_guidance"]
    assert "Stolen Melody" in response["choir"]["targeting_guidance"]
    source.hp_current = 0
    source.is_fallen = True
    mark_destroyed(source)
    choir_encounter.destroyed(state)
    assert not state.choir_silences
    assert not state.spatial["zones"]
    assert not state.spatial["locations"]
    assert source.choir_suppression is None and not source.choir_silence_exposed
    assert actor.conditions == [{"type": "blessed", "source": "other"}]
    facts = choir_encounter.facts(state)
    assert facts is not None
    assert facts["phase"] == "destroyed" and "core_id" not in facts and "search_actions" not in facts
    assert "stolen voice" in facts["cue"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ineligible", ["none", "source", "fallen", "dead", "incapacitated", "destroyed"])
async def test_choir_aura_eligibility_and_success(ineligible, mock_combat_agent_factory):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    import choir_encounter

    ctx, _, _, _ = await start_choir()
    state = ctx.userdata.combat_state
    actor = state.get_participant("player_1")
    ctx.userdata.party.primary.concentration.spell_id = "divine_bless"
    if ineligible == "source":
        actor = choir_encounter.owner(state)
    elif ineligible in {"fallen", "dead"}:
        setattr(actor, "is_" + ineligible, True)
    elif ineligible == "incapacitated":
        actor.conditions = [{"type": "stunned"}]
    elif ineligible == "destroyed":
        state.choir_encounter["phase"] = "destroyed"
    end = MagicMock(end_concentration=AsyncMock())
    with patch("check_resolution_save.roll_participant_save", return_value=SimpleNamespace(success=True)) as save:
        await choir_encounter.turn_start(ctx.userdata, state, actor, conn=None, concentration_break_mod=end)
        state.round_number += 1
        await choir_encounter.turn_start(ctx.userdata, state, actor, conn=None, concentration_break_mod=end)
    assert save.call_count == (2 if ineligible == "none" else 0)
    end.end_concentration.assert_not_called()
    assert ctx.userdata.party.primary.concentration.spell_id == "divine_bless"
