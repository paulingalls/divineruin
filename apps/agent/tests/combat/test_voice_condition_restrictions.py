from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state, _resolve_deps
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import combat_maneuver
import combat_packet
import combat_phase
from combat_phase import ResolutionPacket
from declarations import resolve_declaration


def charm_state():
    state = _make_combat_state(enemy_hp=30)
    state.participants[0].conditions = [{"type": "charmed", "source": "goblin_scout_1", "duration": 3}]
    other = deepcopy(state.participants[1])
    other.id = "other"
    state.participants.append(other)
    state.initiative_order.append(other.id)
    state.spatial = {
        "positions": {p.id: {"x": 0, "y": 0, "z": 0} for p in state.participants},
        "speeds": {p.id: 30 for p in state.participants},
        "locations": {},
        "zones": {},
    }
    return state


def attack(target="goblin_scout_1"):
    return {"type": "attack", "action": "Longsword", "target_id": target}


@pytest.mark.parametrize("raw", [attack(), {"type": "maneuver", "action": "shove", "target_id": "goblin_scout_1"}])
def test_charm_declaration_paths(raw):
    state = charm_state()
    assert state.spatial is not None
    with pytest.raises(ValueError, match=r"[Cc]harmed"):
        combat_phase.advance_combat_phase(state, {"player_1": raw})
    assert state.pending_declarations == {}
    assert state.beat == "declaration"


def test_charm_other_actor_with_same_name_stays_legal():
    state, _ = combat_phase.advance_combat_phase(charm_state(), {"player_1": attack("other")})
    assert state.pending_declarations["player_1"]["target_id"] == "other"


@pytest.mark.asyncio
async def test_charm_packet_resolution_rechecks_current_condition():
    state = charm_state()
    assert state.spatial is not None
    ctx = make_context()
    ctx.userdata.combat_state = state
    deps = _resolve_deps()
    packet = ResolutionPacket(actor_id="player_1", declaration=resolve_declaration(attack()), initiative=15)
    result = await combat_packet._resolve_one_packet(
        ctx.userdata,
        state,
        packet,
        mutations=deps["mutations"],
        queries=deps["queries"],
        resolver=deps["resolver"],
        concentration_break_mod=deps["concentration_break_mod"],
    )
    assert result["resolved"] is False
    assert "charmed" in result["reason"].lower()
    deps["resolver"].resolve_attack.assert_not_called()
    deps["mutations"].update_player_hp.assert_not_awaited()


def test_charm_maneuver_rechecks_before_roll():
    state = charm_state()
    assert state.spatial is not None
    decl = resolve_declaration({"type": "maneuver", "action": "shove", "target_id": "goblin_scout_1"})
    rng = MagicMock(randint=MagicMock(return_value=10))
    with pytest.raises(ValueError, match=r"[Cc]harmed"):
        combat_maneuver.resolve_maneuver(state, state.participants[0], decl, rng=rng)
    rng.randint.assert_not_called()


@pytest.mark.parametrize(
    "spell_id",
    [
        "arcane_bolt",
        "arcane_hold_person",
        "arcane_fireball",
        "arcane_chain_lightning",
        "primal_call_lightning",
        "divine_miracle",
    ],
)
def test_charm_spell_declaration_paths(spell_id):
    target = "goblin_scout_1" if spell_id in ("arcane_bolt", "arcane_hold_person") else "other"
    with pytest.raises(ValueError, match=r"[Cc]harmed"):
        combat_phase.advance_combat_phase(
            charm_state(),
            {
                "player_1": {"type": "ability", "action": spell_id, "target_id": target},
            },
        )


@pytest.mark.parametrize("spell_id", ["arcane_bolt", "divine_bless", "divine_mass_heal"])
def test_charm_spell_legal_controls(spell_id):
    target = "other" if spell_id == "arcane_bolt" else "goblin_scout_1"
    state, _ = combat_phase.advance_combat_phase(
        charm_state(),
        {
            "player_1": {"type": "ability", "action": spell_id, "target_id": target},
        },
    )
    assert state.beat == "resolution"


@pytest.mark.parametrize("resolver_name,threshold", [("resolve_skill_check", "easy"), ("resolve_skill_check_dc", 8)])
def test_hearing_auto_failure_without_rng_or_bonus(resolver_name, threshold):
    import check_resolution

    player = {"conditions": [{"type": "deafened"}, {"type": "inspired"}]}
    rng = MagicMock(randint=MagicMock(return_value=20))
    result = getattr(check_resolution, resolver_name)(
        player, "perception", threshold, rng=rng, ally_present=True, hearing_only=True
    )
    assert result.success is False
    assert result.roll == 0
    assert result.auto_fail is True
    assert result.consumed_conditions == ()
    assert result.gift_name is None
    rng.randint.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["skill", "discover"])
@pytest.mark.parametrize("candidate", [False, True])
async def test_public_hearing_and_sight_routes(kind, candidate, monkeypatch):
    import json

    import check_tools
    from check_payloads import DiscoverCheck, SkillCheck
    from tools._helpers import SAMPLE_PLAYER, _skill_mocks

    queries, mutations = _skill_mocks()
    player = {**SAMPLE_PLAYER, "conditions": [{"type": "deafened"}]}
    queries.get_player.return_value = player
    monkeypatch.setattr(check_tools.db_queries, "get_player", queries.get_player)
    monkeypatch.setattr(check_tools.db_queries, "get_single_skill_advancement", queries.get_single_skill_advancement)
    monkeypatch.setattr(
        check_tools.db_mutations_skill_advancement, "update_skill_advancement", mutations.update_skill_advancement
    )
    hidden = [{"id": "secret", "discover_skill": "perception", "dc": 8, "description": "secret"}] if candidate else []
    monkeypatch.setattr(
        check_tools.db_content_queries, "get_location", AsyncMock(return_value={"hidden_elements": hidden})
    )
    events = AsyncMock()
    monkeypatch.setattr(check_tools, "publish_game_event", events)
    import check_discovery

    monkeypatch.setattr(check_discovery, "publish_game_event", events)
    monkeypatch.setattr(check_discovery, "publish_hidden_revealed", AsyncMock())
    monkeypatch.setattr(check_tools.db_mutations, "set_player_flag", AsyncMock())
    ctx = make_context()
    payload = (
        SkillCheck(kind="skill", skill="perception", difficulty="easy", context_description="listen", hearing_only=True)
        if kind == "skill"
        else DiscoverCheck(kind="discover", skill="perception", target="wall", hearing_only=True)
    )
    result = json.loads(await check_tools.check(ctx, payload))
    assert result["roll"] == 0
    assert result["outcome"] == "automatic_failure"
    assert "hear" in result["narrative_hint"].lower()
    assert ctx.userdata.attempted_discoveries == set()
    events.assert_not_awaited()
    mutations.update_skill_advancement.assert_not_awaited()
    # The same public producer must carry false independently, without reading the phrase "listen".
    sight = payload.model_copy(update={"hearing_only": False})
    if kind == "discover":
        monkeypatch.setattr(check_tools.db_mutations, "set_player_flag", AsyncMock())
    visible_result = json.loads(await check_tools.check(ctx, sight))
    assert visible_result["roll"] > 0
    assert visible_result["outcome"] != "automatic_failure"
    assert events.await_count > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("verbal", [True, False])
async def test_silence_cast_precedes_focus_and_keeps_nonverbal_usable(verbal):
    from dataclasses import replace

    from _spell_casting_helpers import _cast, _spell
    from livekit.agents.llm import ToolError

    state = charm_state()
    assert state.spatial is not None
    state.participants[0].conditions = [{"type": "deafened"}]
    state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "player_1", "radius_ft": 0}}
    spell = replace(_spell(spell_id="arcane_bolt", focus_cost=2, resonance=0), verbal=verbal)
    if verbal:
        with pytest.raises(ToolError, match="silenced"):
            await _cast(spell, focus=0, combat_state=state)
    else:
        packet, _, persistence, _, _ = await _cast(spell, focus=10, combat_state=state)
        assert packet["effect"] == spell.mechanics
        persistence.update_player_resources.assert_awaited_once()


@pytest.mark.asyncio
async def test_outside_silence_cast_to_inside_target_is_legal():
    from _spell_casting_helpers import _cast, _spell

    state = charm_state()
    assert state.spatial is not None
    state.participants[0].conditions = [{"type": "deafened"}]
    state.spatial["positions"]["goblin_scout_1"]["x"] = 40
    state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": "goblin_scout_1", "radius_ft": 0}}
    packet, _, _, _, _ = await _cast(_spell(spell_id="arcane_bolt", focus_cost=0, resonance=0), combat_state=state)
    assert "Deals force damage" in packet["effect"]


@pytest.mark.asyncio
async def test_charm_actual_cast_core_refuses_before_queries():
    import spell_casting
    import spells

    ctx = make_context()
    ctx.userdata.combat_state = charm_state()
    queries = MagicMock(
        get_player=AsyncMock(side_effect=AssertionError("caster queried before condition guard")),
        get_players_for_update=AsyncMock(side_effect=AssertionError("caster queried before condition guard")),
    )
    with pytest.raises(ToolError, match="Charmed"):
        await spell_casting._resolve_cast(
            ctx.userdata,
            "arcane_bolt",
            target_id="goblin_scout_1",
            conn=object(),
            queries_mod=queries,
            spells_mod=spells,
        )
    queries.get_players_for_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_charm_prevalidation_refuses_before_focus_or_ownership():
    from types import SimpleNamespace

    state = charm_state()
    assert state.spatial is not None
    decl = resolve_declaration({"type": "ability", "action": "arcane_bolt", "target_id": "goblin_scout_1"})
    adv = SimpleNamespace(packets=[ResolutionPacket("player_1", decl, 15)])
    ctx = make_context()
    ctx.userdata.combat_state = state
    queries = MagicMock(get_player=AsyncMock(return_value={"class": "mage", "level": 5, "focus": {"current": 10}}))
    import spells

    caster = MagicMock(_gate_spell=MagicMock(return_value=spells.get_spell("arcane_bolt")))
    known = MagicMock(get_known=AsyncMock(return_value=[{"spell_id": "arcane_bolt"}]))
    with pytest.raises(ToolError, match="Charmed"):
        await combat_packet._prevalidate_ability_focus(
            ctx.userdata, state, adv, conn=object(), queries=queries, cast_resolver=caster, character_spells_mod=known
        )
    caster._gate_spell.assert_not_called()


@pytest.mark.parametrize("source_index", [0, 1, 2])
def test_charm_hostile_nonarea_checks_every_explicit_target(source_index, monkeypatch):
    from dataclasses import replace

    import spells

    fixture = replace(spells.get_spell("arcane_bolt"), max_targets=3)
    monkeypatch.setitem(spells._spells, fixture.id, fixture)
    targets = ["other", "player_1"]
    targets.insert(source_index, "goblin_scout_1")
    with pytest.raises(ValueError, match="Charmed"):
        combat_phase.advance_combat_phase(
            charm_state(),
            {
                "player_1": {
                    "type": "ability",
                    "action": fixture.id,
                    "target_ids": targets,
                }
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("ability_id", ["bard_inspire", "diplomat_inspire", "bard_mass_inspire"])
async def test_spoken_ooc_producers_exclude_deafened(ability_id):
    from combat.test_inspire_producer import _activate, _bard

    import abilities

    ability = abilities.get_ability(ability_id)
    with pytest.raises(ToolError, match="eligible"):
        await _activate(
            ability,
            caster=_bard(),
            rows={"ally": _bard("ally", [{"type": "deafened"}])},
            party_member_ids=["ally"],
            target_ids=["ally"] if ability.max_targets else None,
            target_id=None if ability.max_targets else "ally",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("ability_id", ["bard_inspire", "diplomat_inspire", "bard_mass_inspire"])
@pytest.mark.parametrize("restriction", ["deafened", "silenced"])
async def test_spoken_combat_producers_refuse_before_debit(ability_id, restriction):
    from combat.test_inspire_producer import _bard
    from sample_fixtures import make_context

    import abilities
    import combat_ability

    state = charm_state()
    assert state.spatial is not None
    state.participants[0].conditions = []
    target = state.participants[2]
    target.type = "companion"
    if restriction == "deafened":
        target.conditions = [{"type": "deafened"}]
    else:
        state.spatial["positions"][target.id]["x"] = 40
        state.spatial["zones"] = {"quiet": {"kind": "silence", "center_id": target.id, "radius_ft": 0}}
    ability = abilities.get_ability(ability_id)
    raw: dict = {"type": "ability", "action": ability.id, "target_id": target.id}
    if ability.max_targets:
        raw.pop("target_id")
        raw["target_ids"] = [target.id]
    decl = resolve_declaration(raw)
    ctx = make_context()
    ctx.userdata.combat_state = state
    persistence = MagicMock(update_player_resources=AsyncMock())
    with pytest.raises(ValueError, match="eligible"):
        await combat_ability._resolve_ability_condition_packet(
            ctx.userdata,
            state.participants[0],
            decl,
            (ability, None),
            state=state,
            conn=object(),
            player=_bard("player_1"),
            persistence=persistence,
        )
    persistence.update_player_resources.assert_not_awaited()
    assert target.conditions == ([{"type": "deafened"}] if restriction == "deafened" else [])


@pytest.mark.parametrize("kind", ["attack", "save", "skill"])
def test_deafened_cannot_spend_inspired_but_blessed_stays_usable(kind):
    from sample_fixtures import FixedRng

    import check_resolution
    import check_resolution_attack
    import check_resolution_save

    player = {"conditions": [{"type": "deafened"}, {"type": "inspired"}, {"type": "blessed"}]}
    if kind == "attack":
        result = check_resolution_attack.resolve_attack(
            player, {"damage": "1d1", "damage_type": "force"}, 10, 30, rng=FixedRng(10)
        )
    elif kind == "save":
        result = check_resolution_save.resolve_saving_throw(player, "wisdom", 8, "stunned", rng=FixedRng(10))
    else:
        result = check_resolution.resolve_skill_check_dc(
            player, "athletics", 8, rng=FixedRng(10), ally_present=False, hearing_only=False
        )
    assert "inspired" not in result.consumed_conditions
    assert ("blessed" in result.consumed_conditions) is (kind != "skill")
    assert any(c["type"] == "inspired" for c in player["conditions"])
