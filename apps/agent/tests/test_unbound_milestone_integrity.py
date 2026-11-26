"""One-time reward writes and combat adoption survive transaction failures."""

from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import MilestoneWalk
from sample_fixtures import published_payloads

import db
import db_mutations
import db_queries

WISDOM = "unbound_self_reliant_wisdom"
IMMUNITY = "unbound_divine_immunity"


@pytest.mark.parametrize("operation", ["save", "combat", "spend", "rest"])
async def test_reward_commit_is_atomic(dev_db_pool, operation):
    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "none", "level": 0, "max": 100},
            unbound_autonomy={"level": 40, "max": 100, "tier": "Self-Forged"},
            saving_throw_proficiencies=["strength"],
        )
        if operation == "combat":
            await w.encounter()
        if operation == "rest":
            await w.use(WISDOM)
            await w.use(IMMUNITY)
        before = await w.row()
        live = deepcopy(w.sd.combat_state)
        saved = await db_mutations.load_combat_state(live.combat_id) if live else None
        events = deepcopy(published_payloads(w.sd.room))
        transaction = db.transaction
        reached = False

        @asynccontextmanager
        async def fail_commit():
            nonlocal reached
            async with transaction() as conn:
                yield conn
                inside = await db_queries.get_player(w.player, conn=conn)
                assert inside is not None
                if operation in ("save", "combat"):
                    assert inside["unbound_autonomy"]["save_proficiency"] == "wisdom"
                    assert inside["saving_throw_proficiencies"] == ["strength", "wisdom"]
                    if operation == "combat":
                        assert live is not None
                        pending = await db_mutations.load_combat_state(live.combat_id, conn=conn)
                        assert pending is not None
                        participant = pending.get_participant(w.player)
                        assert participant is not None
                        assert participant.saving_throw_proficiencies == ["strength", "wisdom"]
                else:
                    assert inside["patron_gifts"][IMMUNITY] == {"spent": operation == "spend"}
                reached = True
                raise RuntimeError("injected reward commit failure")

        async def run(error=False):
            if operation == "rest":
                return await w.command("rest", {"rest_type": "long", "use_song_of_rest": False}, error=error)
            return await w.use(IMMUNITY if operation == "spend" else WISDOM, error=error)

        with patch.object(db, "transaction", fail_commit):
            await run(error=True)
        assert reached, "refusal before the durable writes is not rollback coverage"
        assert await w.row() == before
        assert w.sd.combat_state == live
        assert published_payloads(w.sd.room) == events
        if live:
            assert await db_mutations.load_combat_state(live.combat_id) == saved
        await run()
        assert await w.row() != before


@pytest.mark.parametrize("token", [WISDOM, IMMUNITY])
async def test_revoked_actor_cannot_write_rewards(dev_db_pool, token):
    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "none", "level": 0, "max": 100},
            unbound_autonomy={"level": 40, "max": 100, "tier": "Self-Forged"},
            saving_throw_proficiencies=[],
        )
        before = await w.row()
        real_get = db_queries.get_player
        authorized = True
        reached = False

        async def lock_then_revoke(*args, **kwargs):
            nonlocal authorized, reached
            result = await real_get(*args, **kwargs)
            if kwargs.get("for_update"):
                reached = True
                authorized = False
            return result

        def validate(*_):
            if not authorized:
                raise RuntimeError("stale authenticated actor")

        w.validator = validate
        with patch.object(db_queries, "get_player", lock_then_revoke):
            await w.use(token, error=True)
        assert reached
        assert await w.row() == before
        assert not published_payloads(w.sd.room)
