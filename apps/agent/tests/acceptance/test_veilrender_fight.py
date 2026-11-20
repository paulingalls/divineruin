"""The solitary Veilrender is entered through its shipped public tool surface."""

import json

import pytest
from acceptance.mawling_harness import MawlingHarness
from sample_fixtures import CONTENT_ROOT


@pytest.fixture
def mock_combat_agent_factory():
    return None


def effects_in(value):
    if isinstance(value, dict):
        if "effect" in value:
            yield value
        for child in value.values():
            yield from effects_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from effects_in(child)


async def legal_party(h, level):
    from datetime import UTC, datetime

    import character_spells
    import db_queries
    from archetypes import get_archetype_chassis
    from creation_rules import build_character_data, select_starting_spells
    from progression_tools import _award_xp_core
    from rules_engine import XP_FOR_LEVEL

    for pid, cls in zip(h.players, ("rogue", "cleric", "warrior", "cleric"), strict=True):
        row = build_character_data(
            "Veilrender challenger", "human", cls, None, "", created_at=datetime(2026, 11, 18, tzinfo=UTC)
        )
        row.update(player_id=pid, location_id="ashmark_corrupted_front")
        await h.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))
        for spell in select_starting_spells(cls, get_archetype_chassis(cls).magic_source):
            await character_spells.record_learned(pid, spell, "training", is_prepared=True)
        async with h.pool.acquire() as conn, conn.transaction():
            await _award_xp_core(
                player_id=pid,
                player=row,
                amount=XP_FOR_LEVEL[level],
                reason="Veilrender certification",
                conn=conn,
                pending_events=[],
            )
        row = await db_queries.get_player(pid)
        assert row is not None
        for key in ("hp", "stamina", "focus"):
            if key in row:
                row[key]["current"] = row[key]["max"]
        await h.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))


@pytest.mark.parametrize("seed", [0, 1])
async def test_terminal_tool_fight(reset_db_pool, seed):
    import random
    from unittest.mock import patch

    from veilrender_harness import declaration

    import combat_end
    import db_queries
    from condition_restrictions import cannot_act

    h = MawlingHarness()
    effects, actions, settlements = [], [], []
    reloads = holds = 0
    original_end = combat_end._end_combat_db

    async def settle(session, state, outcome, **kwargs):
        settlements.append(
            (outcome, {p.id: (p.hp_current, p.conditions) for p in state.participants if p.type == "player"})
        )
        return await original_end(session, state, outcome, **kwargs)

    rng = random.Random(seed)
    previous = random.getstate()
    random.seed(seed)
    try:
        await h.prepare((14, 14, 14, 14), companion=None, location="ashmark_corrupted_front")
        await legal_party(h, 14)
        with (
            patch("dice.random.SystemRandom", return_value=rng),
            patch("combat_end._end_combat_db", settle),
            patch("combat_wrap._end_combat_db", settle),
        ):
            result = await h.command("enter_mode", {"mode": "combat", "encounter_id": "hollow_veilrender_boss"})
            from acceptance._catalog_cutover_helpers import assert_strength

            from encounter_budget import calculate_encounter_budget

            template = json.loads(
                await h.pool.fetchval("SELECT data FROM encounter_templates WHERE id='hollow_veilrender_boss'")
            )
            catalog = {r["id"]: r for r in json.loads((CONTENT_ROOT / "content/creatures.json").read_text())}
            assert_strength(template, catalog)
            print(
                {
                    "difficulty": template["difficulty"],
                    "level": template["recommended_party_level"],
                    "recommended_party_size": template["recommended_party_size"],
                    "hp": 120,
                    "ac": 14,
                    "budget": calculate_encounter_budget(template["enemies"], template["recommended_party_level"]),
                }
            )
            assert h.sd.combat_state is not None
            combat_id = h.sd.combat_state.combat_id
            for _ in range(60):
                state = await h.reload()
                living = [p for p in state.participants if not p.is_fallen and not p.is_dead]
                allies = [p for p in living if p.is_ally]
                foes = [p for p in living if not p.is_ally]
                if not allies:
                    for actor in state.participants:
                        if actor.type == "player" and actor.is_fallen and not actor.is_dead:
                            await h.command("request_death_save", {"player_id": actor.id})
                            if h.sd.combat_state is None:
                                break
                    if h.sd.combat_state is None:
                        break
                    allies = [p for p in state.participants if p.is_ally]
                declarations = []
                for actor in living:
                    if cannot_act(actor.conditions):
                        continue
                    target = (
                        max(allies, key=lambda p: p.hp_current)
                        if not actor.is_ally and allies
                        else foes[0]
                        if foes
                        else None
                    )
                    if target is None:
                        continue
                    cantrip = "divine_sacred_flame" if actor.id in (h.players[1], h.players[3]) else None
                    declarations.append(declaration(state, actor, target, cantrip).model_dump())
                assert declarations
                if state.round_number in (4, 5):
                    before = state.to_dict()
                    error = await h.command(
                        "declare_phase",
                        {
                            "declarations": [
                                {
                                    "reshape": [],
                                    "kind": "attack",
                                    "actor_id": "veilrender",
                                    "action": "Corruption Pulse",
                                    "target_id": h.players[0],
                                    "held_item_id": "",
                                    "rider": "",
                                }
                            ]
                        },
                        error=True,
                    )
                    assert "Corruption Pulse" in error and (await h.reload()).to_dict() == before
                await h.command("declare_phase", {"declarations": declarations})
                prior_round = state.round_number
                for _ in range(32):
                    result = await h.command("resolve_phase", {})
                    effects.extend(effects_in(result.get("packets", [])))
                    actions.extend(p.get("action") for p in result.get("packets", []))
                    if h.sd.combat_state is None:
                        break
                    state = await h.reload()
                    source = state.get_participant("veilrender")
                    assert source is not None and source.regeneration is not None
                    reloads += int(source.regeneration_suppressed or source.radiant_suppression_pending)
                    holds += int(state.open_window is not None)
                    if state.round_number != prior_round:
                        break
                else:
                    pytest.fail("Veilrender hold did not drain")
                if h.sd.combat_state is None:
                    break
                for pid in result.get("death_saves_due", []):
                    await h.command("request_death_save", {"player_id": pid})
                    if h.sd.combat_state is None:
                        break
                if h.sd.combat_state is None:
                    break
            else:
                pytest.fail(f"Veilrender fight did not terminate: {effects}")
        print(
            {
                "seed": seed,
                "rounds": prior_round,
                "actions": actions,
                "regeneration": [e for e in effects if e["effect"] == "regeneration"],
                "holds": holds,
                "suppressed_reloads": reloads,
                "settlements": settlements,
            }
        )
        assert len(settlements) == 1
        assert await h.pool.fetchval("SELECT count(*) FROM combat_instances WHERE combat_id=$1", combat_id) == 0
        import conditions

        for pid, (hp, active_conditions) in settlements[0][1].items():
            row = await db_queries.get_player(pid)
            assert row is not None and row["hp"]["current"] == hp
            assert conditions.hollowed_stage(row.get("conditions", [])) == conditions.hollowed_stage(active_conditions)
        regen = [e for e in effects if e["effect"] == "regeneration"]
        assert any(e["healed"] > 0 for e in regen)
        assert any(e["suppressed"] and "radiant" in e["causes"] for e in regen)
        spec = next(
            r
            for r in json.loads((CONTENT_ROOT / "content/creatures.json").read_text())
            if r["id"] == "hollow_veilrender"
        )["regeneration"]
        assert spec["suppressed_cue"] in str(regen) and spec["resumed_cue"] in str(regen)
        assert {"Reality Crush", "Corruption Pulse"} <= set(actions)
        assert holds and reloads
    finally:
        random.setstate(previous)
        await h.close()
