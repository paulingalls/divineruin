"""Combat-state read/rehydrate round-trip against the real dev Postgres (story-002, M4.1).

story-001 shipped the WRITE side: CombatState.to_dict() (asdict) serializes the phase fields
(beat/pending_declarations/reactions_available) and save_combat_state stores the whole dict as a
single JSONB column in combat_instances. This proves the missing READ side end-to-end —
load_combat_state -> CombatState.from_dict reconstructs an equal CombatState (participants as
CombatParticipant instances, phase fields + death-save counters preserved) from that stored row.

Real-PG (the docker-compose dev DB at :55432, brought up by tests/conftest.py's session hook). No
testcontainer/reset_db_pool needed — combat_instances has no FK, so a pool against the dev DB + a
unique combat_id is enough; the row is cleaned up via delete_combat_state in a finally. The
dev_db_pool fixture mirrors acceptance's reset_db_pool (point db.get_pool() at a DB, restore after)
but targets the docker-compose dev DB rather than a per-run testcontainer.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver, _make_combat_state

import combat_phase
import combat_turn
import db_mutations
import reaction_spend
import reaction_windows
from combat_support import deserialize_roll, roll_attack, serialize_roll
from session_data import CombatParticipant, CombatState, SessionData

# dev_db_pool is provided by tests/combat/conftest.py (shared with the tx-integrity suite).


def test_make_combat_state_enemy_fallen_param_sets_is_fallen() -> None:
    """The enemy_fallen builder param drops the enemy at construction (mirrors player_fallen),
    so fixtures no longer hand-set is_fallen on the goblin. Pure unit test, no DB."""
    enemy = _make_combat_state(enemy_fallen=True).get_participant("goblin_scout_1")
    assert enemy is not None and enemy.is_fallen is True
    # Default leaves the enemy standing.
    standing = _make_combat_state().get_participant("goblin_scout_1")
    assert standing is not None and standing.is_fallen is False


def test_enhancers_field_roundtrips_and_defaults_empty() -> None:
    """story-004: a participant's enhancers list survives the asdict/from_dict JSONB
    round-trip, and a row written before the field existed rehydrates to []. Pure, no DB."""
    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.enhancers = ["extra_attack", "cunning_action"]

    rehydrated = CombatState.from_dict(state.to_dict())
    rp = rehydrated.get_participant("player_1")
    assert rp is not None
    assert rp.enhancers == ["extra_attack", "cunning_action"]

    # Backward compat: a participant dict missing 'enhancers' falls back to the empty default.
    legacy = state.to_dict()
    for p in legacy["participants"]:
        p.pop("enhancers", None)
    legacy_state = CombatState.from_dict(legacy)
    assert all(p.enhancers == [] for p in legacy_state.participants)


def test_role_fields_roundtrip_and_default_for_legacy_rows() -> None:
    """story-001 (M4.7): a participant's encounter-role fields (role, attack_mod, damage_mult,
    dc_mod, legendary_actions, signature_ability) survive the asdict/from_dict JSONB round-trip,
    and a row written before they existed rehydrates to the identity defaults. Pure, no DB."""
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.role = "boss"
    enemy.attack_mod = 2
    enemy.damage_mult = 1.5
    enemy.dc_mod = 2
    enemy.legendary_actions = 1
    enemy.signature_ability = {"name": "Rally"}

    rehydrated = CombatState.from_dict(state.to_dict())
    re = rehydrated.get_participant("goblin_scout_1")
    assert re is not None
    assert re.role == "boss"
    assert re.attack_mod == 2
    assert re.damage_mult == 1.5
    assert re.dc_mod == 2
    assert re.legendary_actions == 1
    assert re.signature_ability == {"name": "Rally"}

    # Backward compat: a row missing the new fields falls back to the identity defaults — players
    # and pre-M4.7 enemies resolve exactly as before.
    legacy = state.to_dict()
    role_fields = ("role", "attack_mod", "damage_mult", "dc_mod", "legendary_actions", "signature_ability")
    for p in legacy["participants"]:
        for field_name in role_fields:
            p.pop(field_name, None)
    p0 = CombatState.from_dict(legacy).participants[0]
    assert p0.role == "standard"
    assert p0.attack_mod == 0
    assert p0.damage_mult == 1.0
    assert p0.dc_mod == 0
    assert p0.legendary_actions == 0
    assert p0.signature_ability is None


def test_loot_fields_roundtrip_and_default_for_legacy_rows() -> None:
    """story-002 (M4.7): a participant's loot overlay fields (category, loot_table_id) survive the
    asdict/from_dict JSONB round-trip, and a row written before they existed rehydrates to the
    empty-string defaults (players/companions and pre-story-002 enemies). Pure, no DB."""
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.category = "humanoid"
    enemy.loot_table_id = "loot_humanoid_bandit"

    re = CombatState.from_dict(state.to_dict()).get_participant("goblin_scout_1")
    assert re is not None
    assert re.category == "humanoid"
    assert re.loot_table_id == "loot_humanoid_bandit"

    # Backward compat: a row missing the loot fields falls back to "" — no loot rolled for it.
    legacy = state.to_dict()
    for p in legacy["participants"]:
        p.pop("category", None)
        p.pop("loot_table_id", None)
    p0 = CombatState.from_dict(legacy).participants[0]
    assert p0.category == ""
    assert p0.loot_table_id == ""


def _mid_combat_state(combat_id: str) -> CombatState:
    """A mid-phase CombatState built from the canonical combat fixture, then advanced into a
    state that exercises every field the round-trip must preserve: a non-default beat, populated
    phase dicts, and a fallen enemy carrying death-save counters. Reuses _make_combat_state
    (the shared two-participant builder the rest of tests/combat/ uses) so the round-trip is
    proven against the same shape as the live engine, not a parallel hand-rolled one."""
    state = _make_combat_state(player_hp=12, enemy_hp=0, enemy_fallen=True)
    state.combat_id = combat_id
    state.round_number = 4
    state.current_turn_index = 1
    state.beat = "resolution"
    state.pending_declarations = {"player_1": {"action": "attack", "target": "goblin_scout_1"}}
    state.reactions_available = {
        "player_1": reaction_spend.unspent(),
        "goblin_scout_1": reaction_spend.spend("warrior_brace_for_impact", _WINDOW, held_seq=0),
    }
    state.ac_modifiers = {"player_1": 2}  # a Defend stance in flight (M4.2, story-002)
    # is_fallen now comes from the enemy_fallen param; death-save counters aren't part of the
    # builder, so set those directly to exercise the round-trip.
    fallen = state.get_participant("goblin_scout_1")
    assert fallen is not None
    fallen.death_save_successes = 2
    fallen.death_save_failures = 1
    return state


_WINDOW = {"id": "r1-0-post_roll", "stage": "post_roll", "triggers": ["on_hit"]}


def test_a_legacy_bool_reactions_map_normalizes_on_load():
    """AC6. Every combat_instances row written before story-017 carries
    ``reactions_available`` as dict[str, bool], on the exact field story-018 reads to choose
    which held blow a reaction modifies. ``from_dict`` restored it as a raw passthrough — none of
    the reconstruction ``participants`` gets — so a live mid-combat row would deserialize bools
    into the record-shaped field and TypeError on the first ``entry["spent"]``.

    Both shapes are NAMED here, which is what makes the normalization a stated upgrade rather than
    a silent default: True was AVAILABLE, so it becomes an unspent record; False was SPENT, so it
    becomes spent-with-no-binding, and story-018 applies no modifier for it. Fault-inject by
    restoring ``data.get("reactions_available", {})``.
    """
    base = _mid_combat_state("combat_legacy_shape").to_dict()
    base["reactions_available"] = {"player_1": True, "player_2": False}

    loaded = CombatState.from_dict(base)

    assert reaction_spend.is_spent(loaded.reactions_available["player_1"]) is False
    assert loaded.reactions_available["player_2"] == {
        "spent": True,
        "ability_id": None,
        "window_id": None,
        "stage": None,
        "held_seq": None,
    }


def test_a_reaction_spend_record_roundtrips():
    """AC1's persistence half: the binding story-018 reads survives to_dict -> from_dict.

    A record that lost its ability_id or held_seq in JSONB would leave 018 knowing a reaction was
    spent but not WHICH one, against WHICH blow — the bare bool, reintroduced through the store."""
    original = _mid_combat_state("combat_record_roundtrip")

    loaded = CombatState.from_dict(json.loads(json.dumps(original.to_dict())))

    assert loaded.reactions_available == original.reactions_available
    spent = loaded.reactions_available["goblin_scout_1"]
    assert spent["ability_id"] == "warrior_brace_for_impact"
    assert spent["window_id"] == "r1-0-post_roll"
    assert spent["stage"] == "post_roll"
    assert spent["held_seq"] == 0


def test_a_pre_story_017_reaction_declaration_does_not_brick_the_round():
    """AC6's sibling field, on the same row. Until story-017 a reaction WAS a declaration, so the
    row most likely to be in flight on deploy is one whose player pre-declared one — and
    resolve_declaration no longer knows that type.

    Left as a passthrough, ``advance_combat_phase`` raises "unknown declaration type: 'reaction'"
    on every resolve_phase, and declare_phase refuses off the declaration beat: the round cannot
    be resolved or re-declared, only fled. The stale entry is dropped for the same reason the bool
    map is upgraded rather than rejected — it never resolved to a mechanical outcome, so nothing
    committed is lost. Fault-inject by restoring ``data.get("pending_declarations", {})``.
    """
    base = _mid_combat_state("combat_legacy_reaction_decl").to_dict()
    base["beat"] = "resolution"
    base["pending_declarations"] = {
        "player_1": {"type": "reaction", "action": "warrior_brace_for_impact", "trigger": "on_hit"},
        "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
    }

    loaded = CombatState.from_dict(base)

    assert "player_1" not in loaded.pending_declarations
    assert loaded.pending_declarations["goblin_scout_1"]["type"] == "attack"
    # ...and the round it belongs to still advances, which is the harm the drop prevents.
    _next_state, adv = combat_phase.advance_combat_phase(loaded)
    assert [p.actor_id for p in adv.packets] == ["goblin_scout_1"]


async def test_load_combat_state_roundtrips_mid_phase_state(dev_db_pool) -> None:
    pool = dev_db_pool
    combat_id = "combat_persist_roundtrip_story002"
    original = _mid_combat_state(combat_id)

    try:
        await db_mutations.save_combat_state(combat_id, original.to_dict(), conn=pool)
        loaded = await db_mutations.load_combat_state(combat_id, conn=pool)

        assert loaded is not None
        # Participants come back as CombatParticipant instances, not raw dicts.
        assert all(isinstance(p, CombatParticipant) for p in loaded.participants)
        # Phase fields + death-save counters survive the JSONB round-trip.
        assert loaded.beat == "resolution"
        assert loaded.pending_declarations == original.pending_declarations
        assert loaded.reactions_available == original.reactions_available
        assert loaded.ac_modifiers == {"player_1": 2}
        fallen = loaded.get_participant("goblin_scout_1")
        assert fallen is not None
        assert fallen.is_fallen is True
        assert fallen.death_save_successes == 2
        assert fallen.death_save_failures == 1
        # Whole-state deep equality via the asdict shape (inverse of from_dict).
        assert loaded.to_dict() == original.to_dict()
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)


def _mid_window_state(combat_id: str = "combat_mid_window") -> CombatState:
    """A combat paused MID-WINDOW: the ally band has committed, one enemy action is HELD with its
    roll already made, and the machine sits on the post-roll (pre-damage) window. The held roll and
    the window descriptor are built by the REAL serializer and the REAL producer, not hand-written
    dicts — a fixture that invents the shape would pass while production wrote a different one.
    ``opened`` carries both stages for the same reason: at a post-roll pause production has offered
    both, and a fixture missing the key would round-trip a shape combat_hold.pump would KeyError on."""
    state = _make_combat_state(player_hp=25)
    state.combat_id = combat_id
    state.beat = "narration"
    enemy = state.get_participant("goblin_scout_1")
    player = state.get_participant("player_1")
    assert enemy is not None and player is not None
    attack_result, effective_ac = roll_attack(enemy, enemy.action_pool[0], player, resolver=_damage_resolver(3))
    state.held_actions = [
        {
            "seq": 0,
            "actor_id": enemy.id,
            "initiative": enemy.initiative,
            "declaration": {"type": "attack", "action": "Scimitar", "target_id": player.id},
            "roll": serialize_roll(attack_result, effective_ac),
            "opened": [reaction_windows.PRE_ROLL, reaction_windows.POST_ROLL],
        }
    ]
    state.open_window = reaction_windows.open_window_for(
        round_number=state.round_number,
        seq=0,
        stage="post_roll",
        actor_id=enemy.id,
        target_id=player.id,
        triggers=reaction_windows.post_roll_triggers(enemy.action_pool[0], hit=attack_result.hit),
    )
    return state


def test_held_actions_and_open_window_round_trip_through_json() -> None:
    """AC8. A combat persisted mid-window must reload with the enemy's turn still pending and the
    window still open — the JSONB round-trip is the only thing between a pause and a lost turn."""
    state = _mid_window_state()
    assert state.open_window is not None

    reloaded = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))

    assert reloaded.to_dict() == state.to_dict()
    assert reloaded.beat == "narration"
    assert [h["actor_id"] for h in reloaded.held_actions] == ["goblin_scout_1"]
    assert reloaded.open_window is not None
    assert reloaded.open_window["stage"] == "post_roll"
    assert reloaded.open_window["id"] == state.open_window["id"]
    # The held roll rehydrates into a real AttackResult, not the dict it was stored as.
    restored, restored_ac = deserialize_roll(reloaded.held_actions[0]["roll"])
    original, original_ac = deserialize_roll(state.held_actions[0]["roll"])
    assert (restored, restored_ac) == (original, original_ac)


def test_a_row_written_before_the_hold_rehydrates_as_not_mid_pause() -> None:
    """Backward compat: a combat persisted before story-016 has no held actions and no open
    window. It is simply not paused — never a half-open window nothing can close."""
    legacy = _make_combat_state().to_dict()
    legacy.pop("held_actions", None)
    legacy.pop("open_window", None)

    loaded = CombatState.from_dict(legacy)

    assert loaded.held_actions == []
    assert loaded.open_window is None


async def test_load_combat_state_round_trips_a_mid_window_pause(dev_db_pool) -> None:
    """The same round-trip through real Postgres JSONB — the fast lane's pure test proves the
    dataclass, this proves the column (constraint 5: validate at the boundary)."""
    pool = dev_db_pool
    combat_id = "combat_persist_mid_window_story016"
    original = _mid_window_state(combat_id)

    try:
        await db_mutations.save_combat_state(combat_id, original.to_dict(), conn=pool)
        loaded = await db_mutations.load_combat_state(combat_id, conn=pool)

        assert loaded is not None
        assert loaded.to_dict() == original.to_dict()
        assert loaded.held_actions[0]["roll"] is not None
        assert loaded.open_window is not None
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)


async def test_load_combat_state_returns_none_for_unknown_id(dev_db_pool) -> None:
    assert await db_mutations.load_combat_state("combat_does_not_exist_story002", conn=dev_db_pool) is None


def _rollback_resolution_state(combat_id: str, player_id: str, enemy_id: str) -> CombatState:
    """A RESOLUTION-beat state with unique participant ids (dev DB is shared across the -n8
    fast lane, so player_id must not collide). Enemy declares an attack on the player so
    resolve_phase writes update_player_hp(player_id) inside the phase transaction."""
    return CombatState(
        combat_id=combat_id,
        participants=[
            CombatParticipant(
                id=player_id,
                name="Kael",
                type="player",
                initiative=15,
                hp_current=25,
                hp_max=25,
                ac=14,
                action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
            ),
            CombatParticipant(
                id=enemy_id,
                name="Goblin",
                type="enemy",
                initiative=12,
                hp_current=7,
                hp_max=7,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                xp_value=50,
            ),
        ],
        initiative_order=[player_id, enemy_id],
        beat="resolution",
        pending_declarations={
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": player_id},
        },
    )


async def test_resolve_phase_rolls_back_player_hp_when_save_combat_state_fails(dev_db_pool, monkeypatch) -> None:
    """A DB failure must NOT leave players.data diverged from the combat_instances SSOT.

    The enemy packet's update_player_hp now lands in the WRAP commit (M29, story-016): the ally
    band commits first, the held enemy actions and the wrap commit second. When that second
    commit's save_combat_state raises, the enemy's blow rolls back with it and the player's
    persisted HP is unchanged — while commit 1's ally results stand, which is the guarantee
    replacing the old whole-phase atomicity. Without the transaction the per-packet HP write would
    commit independently and diverge."""
    pool = dev_db_pool
    player_id = "cap_s010_rollback_player"
    combat_id = "combat_s010_rollback"

    # Seed a real player row at HP 25 (update_player_hp jsonb_set needs data.hp to exist).
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps({"player_id": player_id, "hp": {"current": 25, "max": 25}}),
    )

    # Real db_mutations except save_combat_state, which raises after the per-packet HP write.
    monkeypatch.setattr(db_mutations, "save_combat_state", AsyncMock(side_effect=RuntimeError("boom")))
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])  # no equipped items -> no durability writes
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)

    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    pre_phase_state = _rollback_resolution_state(combat_id, player_id, "cap_s010_enemy")
    ctx.userdata.combat_state = pre_phase_state

    try:
        with pytest.raises(RuntimeError, match="boom"):
            await combat_turn._resolve_phase_impl(
                ctx, queries=queries, resolver=_damage_resolver(3), concentration_break_mod=break_mod
            )
        # The enemy's 3-damage hit (25 -> 22) was rolled back with the failed save: HP is still 25.
        row = await pool.fetchrow(
            "SELECT (data->'hp'->>'current')::int AS hp FROM players WHERE player_id = $1", player_id
        )
        assert row["hp"] == 25

        # In-memory state must NOT diverge from the rolled-back DB SSOT: session.combat_state is
        # still the pristine pre-phase object (the engine deep-copies, and the post-commit
        # session.combat_state assignment is skipped on rollback), with the player at HP 25 — so a
        # retried turn proceeds from committed state, not the discarded mid-phase HP 22.
        assert ctx.userdata.combat_state is pre_phase_state
        player_part = next(p for p in ctx.userdata.combat_state.participants if p.id == player_id)
        assert player_part.hp_current == 25
    finally:
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
        await db_mutations.delete_combat_state(combat_id, conn=pool)
