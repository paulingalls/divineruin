"""Durable Self-Reliance rewards through registered DM commands."""

import pytest
from _unbound_path_fixtures import MilestoneWalk

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
