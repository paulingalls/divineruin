"""Capstone E2E (story-002, M23): the reputation writer flips a stance-gated encounter from
hostile to allied, against a real Postgres testcontainer (auto-marked `acceptance`).

Closes risk f3af7b633b44 / debt 6e8c1e79a775: player_reputation had a reader
(get_player_faction_reputation, consumed by combat_init's stance gate) but no writer, so every
stance-gated encounter resolved HOSTILE at the neutral-0 default. This proves the full production
chain — db_mutations_reputation.adjust_player_faction_reputation writes standing, combat_init reads
it, and resolve_encounter_stance flips the Ashmark Patrol (stance_gate faction=thornwatch,
allied_at_or_above=friendly, threshold 5) to ALLIED once reputation crosses that threshold.

Two distinct player_ids (the testcontainer DB is shared) isolate the before/after so neither call
reuses combat state.
"""

from __future__ import annotations

import json

from acceptance.seeds import seed_player
from sample_fixtures import make_context

import combat_init
import db
import db_mutations_reputation

_WEAPON = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


async def _seed_armed_player(pool, player_id: str) -> None:
    # An equipped weapon lets combat_init synthesize the player's action_pool on the hostile
    # build path (it reads equipment entries carrying `damage`).
    await seed_player(pool, player_id=player_id, location_id="accord_guild_hall")
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{equipment}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"main_hand": _WEAPON}),
    )


async def test_reputation_above_threshold_flips_stance_to_allied(reset_db_pool: str) -> None:
    pool = await db.get_pool()

    # Baseline — a player with no reputation (neutral 0 < friendly threshold 5): the Ashmark
    # Patrol stance gate resolves HOSTILE and combat begins (the always-hostile behavior the risk
    # named). A hostile encounter hands off to the combat agent as a tuple.
    hostile_pid = "cap_s002_rep_hostile"
    await _seed_armed_player(pool, hostile_pid)
    hostile = await combat_init._start_combat_impl(
        make_context(hostile_pid), "ashmark_patrol", "A Thornwatch patrol blocks the road."
    )
    assert isinstance(hostile, tuple), "neutral reputation -> hostile stance -> combat handoff"

    # A player whose reputation the production writer raised to the friendly threshold: the SAME
    # stance gate now resolves ALLIED, averting combat (a narration string, not a handoff).
    allied_pid = "cap_s002_rep_allied"
    await seed_player(pool, player_id=allied_pid, location_id="accord_guild_hall")
    new_value = await db_mutations_reputation.adjust_player_faction_reputation(
        allied_pid, "thornwatch", 5, "completed_faction_quest"
    )
    assert new_value == 5

    allied = await combat_init._start_combat_impl(make_context(allied_pid), "ashmark_patrol", "The patrol approaches.")
    assert isinstance(allied, str), "reputation >= friendly threshold -> allied stance -> combat averted"
    assert "stands down" in allied.lower()
