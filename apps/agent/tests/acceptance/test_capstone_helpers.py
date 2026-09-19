from uuid import uuid4

from acceptance import _capstone_helpers
from acceptance._capstone_helpers import _build_state, _enemy
from sample_fixtures import make_context

import db
import db_mutations
import db_queries


async def test_start_combat_uses_seeded_level_for_reaction_offers(reset_db_pool: str, monkeypatch) -> None:
    pool = await db.get_pool()
    suffix = uuid4().hex
    player_id = f"cap_helper_mage_{suffix}"
    combat_id = f"combat_cap_helper_mage_{suffix}"
    state = _build_state(combat_id, player_id, [_enemy(f"helper_foe_{suffix}", hp=10)])
    context = make_context(player_id)
    seed_player = _capstone_helpers.seed_player_with_pools

    async def seed_level_three(*args, **kwargs):
        await seed_player(*args, **kwargs)
        await args[0].execute(
            "UPDATE players SET data = jsonb_set(data, '{level}', '3'::jsonb) WHERE player_id = $1",
            kwargs["player_id"],
        )

    monkeypatch.setattr(_capstone_helpers, "seed_player_with_pools", seed_level_three)
    try:
        await _capstone_helpers._start_combat(pool, player_id, state, context, player_class="mage")
        row = await db_queries.get_player(player_id, conn=pool)
        assert row is not None
        participant = state.get_participant(player_id)
        assert participant is not None

        assert row["level"] == 3
        assert participant.level == row["level"]
        assert "mage_counterspell" in participant.reaction_ids
        assert participant.has_reaction_ability is True
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=pool)
        await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
