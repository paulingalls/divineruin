"""Durable Self-Reliance rewards through registered DM commands."""

from collections.abc import Iterator

import pytest
from _unbound_path_fixtures import MilestoneWalk
from _unbound_path_fixtures import world as world

SAVES = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
SAVE_IDS = [f"unbound_self_reliant_{save}" for save in SAVES]
IMMUNITY = "unbound_divine_immunity"
MASTERY = "unbound_veil_mastery"
TIERS = ("Self-Reliant", "Self-Forged", "Sovereign")


@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.parametrize("patron", [None, "none", "absent"])
async def test_discovery(dev_db_pool, tier, patron):
    async with MilestoneWalk(dev_db_pool) as w:
        favor = {"level": 0, "max": 100}
        if patron != "absent":
            favor["patron"] = patron
        await w.patch(
            divine_favor=favor,
            unbound_autonomy={"level": 1, "max": 100, "tier": tier},
            saving_throw_proficiencies=["strength", "Dexterity"],
        )
        result = await w.command("query_info", {"kind": "patron"})
        assert result["abilities"] == []
        autonomy = result["autonomy"]
        assert (autonomy["level"], autonomy["tier"]) == (1, tier)
        rows = {m["id"]: m for m in autonomy["milestones"]}
        assert set(rows) == {*SAVE_IDS, IMMUNITY, MASTERY}
        for token, m in rows.items():
            required = 0 if token in SAVE_IDS else 1 if token == IMMUNITY else 2
            assert m["name"] and m["tier"] == TIERS[required]
            assert m["reached"] is (TIERS.index(tier) >= required)
            if not m["reached"]:
                assert m["tier"] in m["rule"]
            elif token in SAVE_IDS[:2]:
                assert "proficient" in m["rule"]
            elif token != MASTERY:
                assert f"activate(id='{token}')" in m["rule"]
            else:
                assert "Automatic" in m["rule"]
        for save, token in zip(SAVES, SAVE_IDS, strict=True):
            assert rows[token]["proficient"] is (save in SAVES[:2])
            assert rows[token]["chosen"] is False
        assert rows[IMMUNITY]["spent"] is False
        assert "Sovereign" in result["capabilities"][2]["rule"]


async def test_legacy_default(dev_db_pool):
    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "none", "level": 0, "max": 100})
        result = await w.command("query_info", {"kind": "patron"})
        assert result["autonomy"]["level"] == 0
        assert result["autonomy"]["tier"] == TIERS[0]


@pytest.mark.parametrize("save,token", list(zip(SAVES, SAVE_IDS, strict=True)))
async def test_save_choice_is_durable_and_one_time(dev_db_pool, save, token):
    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "none", "level": 0, "max": 100},
            unbound_autonomy={"level": 0, "max": 100, "tier": TIERS[0], "extra": "keep"},
            saving_throw_proficiencies=[],
        )
        result = await w.use(token)
        assert save in str(result)
        player = await w.row()
        assert player["unbound_autonomy"]["save_proficiency"] == save
        assert player["unbound_autonomy"]["extra"] == "keep"
        assert player["saving_throw_proficiencies"] == [save]
        assert player["keepsake"] == "unchanged"
        await w.connect()
        assert "choice" in await w.use(SAVE_IDS[(SAVES.index(save) + 1) % 6], error=True)
        assert await w.row() == player


async def test_save_changes_next_roll_and_survives_deed_judgment(dev_db_pool):
    from types import SimpleNamespace
    from unittest.mock import patch

    import db
    import patron_deeds

    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "none", "level": 0, "max": 100},
            level=14,
            attributes={save: 10 for save in SAVES},
            saving_throw_proficiencies=["Strength", "dexterity"],
        )
        before = await w.row()
        assert "proficient" in await w.use(SAVE_IDS[0], error=True)
        assert await w.row() == before
        args = {"roll": {"kind": "save", "save_type": "wisdom", "dc": 12, "effect_on_fail": "fear"}}
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=10)):
            initial = await w.command("check", args)
            assert initial["total"] == 10 and initial["modifier"] == 0 and initial["outcome"] == "failure"
            await w.use(SAVE_IDS[4])
            result = await w.command("check", args)
            assert result["total"] == 13 and result["modifier"] == 3 and result["outcome"] == "success"
        async with db.transaction() as conn:
            await patron_deeds.record_deed(w.player, "succeeded_alone", conn=conn)
            await patron_deeds.judge_pending_deeds(w.player, conn=conn, pending_events=[])
        player = await w.row()
        assert player["unbound_autonomy"]["save_proficiency"] == "wisdom"
        assert player["saving_throw_proficiencies"] == ["Strength", "dexterity", "wisdom"]
        rows = (await w.command("query_info", {"kind": "patron"}))["autonomy"]["milestones"]
        for m in rows[:6]:
            assert "wisdom" in m["rule"] and "choice" in m["rule"]
            assert m["chosen"] is (m["id"] == SAVE_IDS[4])
        assert rows[4]["proficient"]


@pytest.mark.parametrize("token", [*SAVE_IDS, IMMUNITY, MASTERY])
async def test_follower_cannot_activate_milestones(dev_db_pool, token):
    async with MilestoneWalk(dev_db_pool) as w:
        before, abilities = await w.row(), await w.abilities()
        await w.use(token, error=True)
        assert await w.row() == before
        assert await w.abilities() == abilities


@pytest.mark.parametrize("tier", TIERS[1:])
async def test_immunity_spend_and_long_rest(dev_db_pool, tier):
    from session_hydration import hydrate_patron_ability_session

    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "none", "level": 0, "max": 100})
        before = await w.row()
        assert "Self-Forged" in await w.use(IMMUNITY, error=True)
        assert await w.row() == before
        await w.patch(unbound_autonomy={"level": 40, "max": 100, "tier": tier})
        await w.use(SAVE_IDS[4])
        choice = (await w.row())["unbound_autonomy"]
        profs = (await w.row())["saving_throw_proficiencies"]
        result = await w.use(IMMUNITY)
        assert "divine ability" in result["effect"] and "narrate" in result["dm_cue"].lower()
        assert (await w.row())["patron_gifts"] == {"other": {"x": 1}, IMMUNITY: {"spent": True}}
        await w.connect()
        assert "long rest" in await w.use(IMMUNITY, error=True)
        w.sd.member_state(w.player).unbound_veil_mastery_used = True
        await w.command("rest", {"rest_type": "short", "use_song_of_rest": False})
        await hydrate_patron_ability_session(w.sd, w.player, conn=w.pool)
        assert (await w.row())["patron_gifts"][IMMUNITY]["spent"]
        assert w.sd.member_state(w.player).unbound_veil_mastery_used
        await w.command("rest", {"rest_type": "long", "use_song_of_rest": False})
        rows = (await w.command("query_info", {"kind": "patron"}))["autonomy"]["milestones"]
        assert next(m for m in rows if m["id"] == IMMUNITY)["spent"] is False
        await w.use(IMMUNITY)
        assert (await w.row())["unbound_autonomy"] == choice
        assert (await w.row())["saving_throw_proficiencies"] == profs


async def test_running_combat_save_and_lock(dev_db_pool):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    import db_mutations

    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "none", "level": 0, "max": 100},
            level=14,
            attributes={save: 10 for save in SAVES},
            saving_throw_proficiencies=[],
        )
        state = await w.encounter()
        before = await w.row()
        import unbound_tools

        entered = asyncio.Event()
        activate = unbound_tools.activate_milestone

        async def enter(*args, **kwargs):
            entered.set()
            return await activate(*args, **kwargs)

        with patch.object(unbound_tools, "activate_milestone", enter):
            async with w.sd.combat_state_lock:
                task = asyncio.create_task(w.use(SAVE_IDS[4]))
                await asyncio.wait_for(entered.wait(), timeout=2)
                assert not task.done()
                assert await w.row() == before
            await task
        for snapshot in (w.sd.combat_state, await db_mutations.load_combat_state(state.combat_id)):
            assert snapshot is not None
            participant = snapshot.get_participant(w.player)
            assert participant is not None
            assert participant.saving_throw_proficiencies == ["wisdom"]
        await w.command(
            "declare_phase",
            {
                "declarations": [
                    {"reshape": [], "kind": "defend", "actor_id": w.player},
                    {
                        "reshape": [],
                        "kind": "attack",
                        "actor_id": "enemy",
                        "action": "Dread",
                        "target_id": w.player,
                        "held_item_id": "",
                        "rider": "",
                    },
                ]
            },
        )
        packets = []
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=10)):
            for _ in range(8):
                packet = await w.command("resolve_phase", {})
                packets.append(packet)
                if "save_total" in str(packet):
                    break

        def saves(value) -> Iterator[dict]:
            if isinstance(value, dict):
                if "save_total" in value:
                    yield value
                for child in value.values():
                    yield from saves(child)
            elif isinstance(value, list):
                for child in value:
                    yield from saves(child)

        results = list(saves(packets))
        assert len(results) == 1, packets
        assert (results[0]["save_roll"], results[0]["save_total"], results[0]["save_success"]) == (10, 13, True)
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert saved is not None
        participant = saved.get_participant(w.player)
        assert participant is not None
        assert participant.saving_throw_proficiencies == ["wisdom"]


@pytest.mark.parametrize("tier", [None, "Self-Forged"])
@pytest.mark.parametrize("route", ["cast", "phase"])
async def test_pre_sovereign_echo_is_real_for_acting_member(world, tier, route):
    from _unbound_path_fixtures import cast, encounter, phase
    from sample_fixtures import published_payloads

    w = world
    if tier is None:
        await w.pool.execute("UPDATE players SET data=data - 'unbound_autonomy' WHERE player_id=$1", w.ids[1])
    else:
        await w.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{unbound_autonomy}', $2::jsonb) WHERE player_id=$1",
            w.ids[1],
            '{"level":40,"max":100,"tier":"Self-Forged"}',
        )
    if route == "phase":
        encounter(w)
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        packet = await cast(w) if route == "cast" else await phase(w)
    assert "breach" in str(packet), packet
    assert "veil_mastery" not in str(packet)
    assert not w.ctx.userdata.member_state(w.ids[1]).unbound_veil_mastery_used
    echoes = [p for p in published_payloads(w.ctx.userdata.room) if p["type"] == "hollow_echo_result"]
    assert [p["band"] for p in echoes] == ["breach"]


@pytest.mark.parametrize("invalid", [{"level": True}, {"max": 0}, {"tier": "unknown"}, {"save_proficiency": "WIS"}])
async def test_malformed_autonomy_cannot_reopen_choice(dev_db_pool, invalid):
    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "none", "level": 0, "max": 100},
            unbound_autonomy={"level": 0, "max": 100, "tier": TIERS[0], **invalid},
            saving_throw_proficiencies=[],
        )
        before = await w.row()
        await w.use(SAVE_IDS[4], error=True)
        await w.command("query_info", {"kind": "patron"}, error=True)
        assert await w.row() == before


async def test_locked_immunity_reports_durable_spend(dev_db_pool):
    async with MilestoneWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "none", "level": 0, "max": 100}, patron_gifts={IMMUNITY: {"spent": True}})
        rows = (await w.command("query_info", {"kind": "patron"}))["autonomy"]["milestones"]
        immunity = next(m for m in rows if m["id"] == IMMUNITY)
        assert not immunity["reached"] and immunity["spent"]
