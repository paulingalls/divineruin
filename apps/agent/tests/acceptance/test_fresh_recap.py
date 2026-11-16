"""Re-entry follows the producer's committed outcome over real PG/Valkey/LiveKit."""

import asyncio
import json
import logging
import time
from unittest.mock import patch

from acceptance.fresh_recap_harness import RecapHarness

import agent
import db
import db_mutations
import db_queries
import session_outcome
from session_end import run_guest_departure

STALE = "Stale gulls cried."
FRESH = "Fresh bells rang."


async def outcome(pid):
    redis = await db.get_redis()
    raw = await redis.get(f"session_outcome:{pid}")
    return json.loads(raw) if raw else None


async def seed(pid, state, sid="older", *, row=True):
    if row:
        await db_mutations.save_session_summary(pid, sid, {"summary": STALE})
    redis = await db.get_redis()
    if state:
        await redis.set(f"session_outcome:{pid}", json.dumps({"session_id": sid, "state": state}), ex=7200)


async def overlapping(server, caplog, failure):
    async with RecapHarness(server) as harness:
        pid = await harness.player()
        await seed(pid, None)
        first = await harness.start(pid)
        sd = await first.wait()
        assert await outcome(pid) == {"session_id": sd.session_id, "state": "live"}
        redis = await db.get_redis()
        assert 7100 < await redis.ttl(f"session_outcome:{pid}") <= 7200
        entered, release = asyncio.Event(), asyncio.Event()
        generate = __import__("session_end").generate_session_summary
        save = db_mutations.save_session_summary
        saved, built, terminal = [], [], []
        complete = session_outcome.complete
        build = agent._build_recap_instruction

        async def generation(state, *args, **kwargs):
            if state is sd:
                entered.set()
                await release.wait()
                if failure == "generation":
                    raise RuntimeError("injected generation failure")
            return await generate(state, *args, **kwargs)

        async def saving(player, sid, payload):
            if sid == sd.session_id and failure == "save":
                raise RuntimeError("injected save failure")
            await save(player, sid, payload)
            saved.append(sid)

        async def completion(player, sid, state, **kwargs):
            await complete(player, sid, state, **kwargs)
            terminal.append((sid, await outcome(player), await redis.ttl(f"session_outcome:{player}")))

        def recap(row):
            built.append((row, list(saved)))
            return build(row)

        caplog.clear()
        try:
            with (
                patch("session_end.generate_session_summary", side_effect=generation),
                patch("db_mutations.save_session_summary", side_effect=saving),
                patch("session_outcome.complete", side_effect=completion),
                patch("agent._build_recap_instruction", side_effect=recap),
            ):
                await first.delete_room()
                async with asyncio.timeout(10):
                    await entered.wait()
                second = await harness.start(pid)
                await asyncio.sleep(0.2)
                assert not second.greetings and not built
                prior = await db_queries.get_last_session_summary(pid)
                assert prior is not None and prior["session_id"] == "older"
                started = time.monotonic()
                if failure != "timeout":
                    release.set()
                second_sd = await second.wait()
                assert second_sd.location_id == "accord_guild_hall"
                greeting = second.greetings[0]
                assert STALE not in greeting
                if failure:
                    assert FRESH not in greeting and "Last session:" not in greeting
                    assert built[0][0] is None
                    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
                    assert any(
                        pid in w and sd.session_id in w and ("timed out" if failure == "timeout" else "failed") in w
                        for w in warnings
                    )
                    if failure != "timeout":
                        assert time.monotonic() - started < 10
                    else:
                        assert time.monotonic() - started >= 14
                else:
                    assert all(
                        text in greeting for text in (FRESH, "Found a sword", "Spared the chief", "Deeper ruins await")
                    )
                    assert built[0][0]["session_id"] == sd.session_id
                    assert sd.session_id in built[0][1]
                if failure != "timeout":
                    expected = "failed" if failure else "saved"
                    assert any(
                        sid == sd.session_id and record == {"session_id": sid, "state": expected} and 7000 < ttl <= 7200
                        for sid, record, ttl in terminal
                    )
                assert await outcome(pid) == {"session_id": second_sd.session_id, "state": "live"}
                release.set()
                async with asyncio.timeout(35):
                    await asyncio.shield(first.task)
                assert await outcome(pid) == {"session_id": second_sd.session_id, "state": "live"}
        finally:
            release.set()


async def compatibility(server, caplog):
    cases = [
        ("saved", "accord_guild_hall", True, True),
        ("failed", "accord_guild_hall", True, False),
        (None, "accord_guild_hall", True, True),
        ("mismatch", None, True, False),
        ("missing", "accord_guild_hall", False, False),
        (None, "accord_guild_hall", False, False),
        (None, None, True, True),
        (None, None, False, False),
    ]
    for state, location, history, recap in cases:
        async with RecapHarness(server) as harness:
            pid = await harness.player(location=location)
            await seed(pid, "saved" if state in ("mismatch", "missing") else state, row=history)
            if state == "mismatch":
                await db_mutations.save_session_summary(pid, "different", {"summary": STALE, "session_id": "older"})
            caplog.clear()
            with patch("session_outcome.asyncio.sleep", wraps=asyncio.sleep) as sleep:
                job = await harness.start(pid)
                sd = await job.wait()
            # There is no predecessor polling for an already terminal or absent record.
            assert not any(call.args == (0.05,) for call in sleep.call_args_list)
            assert (STALE in job.greetings[0]) == recap
            assert "Key events" not in job.greetings[0]
            returning = bool(location or history)
            assert ("returns to the world" in job.greetings[0]) == returning
            assert sd.location_id == (location or (agent.START_LOCATION if history else "accord_market_square"))
            assert any("Recap skipped" in r.getMessage() for r in caplog.records) == (
                state in ("failed", "mismatch", "missing")
            )


async def early_close(server):
    for create, beat in ((False, "complete"), (True, 3)):
        async with RecapHarness(server) as harness:
            pid = await harness.player(create=create, beat=beat)
            with patch("session_outcome.asyncio.sleep", wraps=asyncio.sleep) as sleep:
                job = await harness.start(pid)
                sd = await job.wait()
            assert not any(call.args == (0.05,) for call in sleep.call_args_list)
            assert job.started_agent == ("PrologueAgent" if not create else "OnboardingAgent")
            assert sd.background is None
            with patch("session_end.generate_session_summary", side_effect=AssertionError("no gameplay summary")):
                await job.delete_room()
                async with asyncio.timeout(35):
                    await asyncio.shield(job.task)
            assert await outcome(pid) == {"session_id": sd.session_id, "state": "failed"}
            assert await db_queries.get_last_session_summary(pid) is None


async def guest_recap(server):
    async with RecapHarness(server) as harness:
        host, guest = await harness.player(), await harness.player()
        await seed(guest, "saved")
        job = await harness.start(host)
        sd = await job.wait()
        # Use the real departure/save path; room removal and promotion are owned seams.
        from party_state import PartyState

        sd.party.members.extend(PartyState.solo(guest).members)
        sd.departing_player_id = guest
        with patch("room_admin.remove_player"):
            await run_guest_departure(sd, guest, job.episode.session)
        assert await outcome(guest) == {"session_id": sd.session_id, "state": "saved"}
        solo = await harness.start(guest)
        await solo.wait()
        assert FRESH in solo.greetings[0]
        sd.party.members.extend(PartyState.solo(guest).members)
        sd.departing_player_id = guest
        with patch("room_admin.remove_player"):
            await run_guest_departure(sd, guest, job.episode.session)
        current = await outcome(guest)
        assert current is not None and current["session_id"] == solo.episode.session.userdata.session_id
        promoted = await harness.player()
        await seed(promoted, "saved")
        sd.party.members.extend(PartyState.solo(promoted).members)
        sd.handoff_primary(host)
        await job.delete_room()
        async with asyncio.timeout(35):
            await asyncio.shield(job.task)
        assert await outcome(promoted) == {"session_id": sd.session_id, "state": "saved"}
        returning = await harness.start(promoted)
        await returning.wait()
        assert FRESH in returning.greetings[0]


async def startup_failures(server):
    import pytest

    async with RecapHarness(server) as harness:
        pid = await harness.player()
        resolve = session_outcome.resolve_predecessor

        async def interrupted(player):
            predecessor = await resolve(player)
            await seed(player, "live", "third-owner", row=False)
            return predecessor

        with patch("session_outcome.resolve_predecessor", side_effect=interrupted):
            job = await harness.start(pid)
            with pytest.raises(RuntimeError, match="owner changed"):
                await job.wait()
        assert await outcome(pid) == {"session_id": "third-owner", "state": "live"}

    async with RecapHarness(server) as harness:
        pid = await harness.player()
        with patch("session_hydration.hydrate_session_state", side_effect=RuntimeError("startup interrupted")):
            job = await harness.start(pid)
            with pytest.raises(RuntimeError, match="startup interrupted"):
                await job.wait()
        current = await outcome(pid)
        assert current is not None and current["state"] == "failed"


async def test_fresh_recap(livekit_server, reset_db_pool, caplog):
    for failure in (None, "generation", "save", "timeout"):
        await overlapping(livekit_server, caplog, failure)
    await compatibility(livekit_server, caplog)
    await early_close(livekit_server)
    await guest_recap(livekit_server)
    await startup_failures(livekit_server)
