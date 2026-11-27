"""Wild Shape through the seeded catalog and registered gameplay tools."""

import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells

import db
import db_queries
import event_types
import spells
from activate_tools import activate

SPELL = "primal_wild_shape"
ABILITY = "druid_wild_shape"
ROOT = Path(__file__).resolve().parents[4]
PROFILE = {
    "stamina_cost": 3,
    "forms": [
        {"creature_id": creature, "min_level": level}
        for creature, level in [("grey_wolf", 5), ("wild_boar", 5), ("steppe_bison", 5), ("dire_bear", 10)]
    ],
}


async def test_catalog(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    original = await pool.fetchval("SELECT data FROM spells WHERE id=$1", SPELL)
    registry = spells._spells.copy()
    original_data = json.loads(original)
    bad_rows = []
    for form, diagnostic in [
        ({"creature_id": "missing_beast", "min_level": 5}, "missing_beast"),
        ({"creature_id": "bandit", "min_level": 5}, "bandit"),
        ({"creature_id": "grey_wolf", "min_level": 0}, "min_level"),
        ({"creature_id": "grey_wolf", "min_level": 5.5}, "min_level"),
        (None, "forms"),
    ]:
        bad_rows.append(
            (dict(original_data, wild_shape={"stamina_cost": 3, "forms": [form] if form else []}), diagnostic)
        )
    bad_rows.append((dict(original_data, wild_shape={"stamina_cost": 3}), "forms"))
    missing = deepcopy(original_data)
    missing.pop("wild_shape", None)
    bad_rows.append((missing, "wild_shape"))
    try:
        await spells.load_spells()
        assert asdict(spells.get_spell(SPELL))["wild_shape"] == PROFILE
        for form in PROFILE["forms"]:
            raw = await pool.fetchval("SELECT data FROM creatures WHERE id=$1", form["creature_id"])
            assert json.loads(raw)["category"] == "beast"
        for malformed, diagnostic in bad_rows:
            await pool.execute("UPDATE spells SET data=$2 WHERE id=$1", SPELL, json.dumps(malformed))
            with pytest.raises(ValueError, match=f"{SPELL}.*{diagnostic}"):
                await spells.load_spells()
            assert spells.get_spell(SPELL).wild_shape == PROFILE
    finally:
        await pool.execute("UPDATE spells SET data=$2 WHERE id=$1", SPELL, original)
        spells.set_spells(registry)

    process = await asyncio.create_subprocess_exec(
        "bun",
        "--no-env-file",
        "-e",
        """
        import { loadSpells, getSpell } from "./apps/server/src/spells.ts";
        import { sql } from "./apps/server/src/db.ts";
        const { original_data, bad_rows, id } = await Bun.stdin.json();
        try {
          await loadSpells();
          console.log(JSON.stringify(getSpell(id).wild_shape));
          for (const [row, diagnostic] of bad_rows) {
            await sql`UPDATE spells SET data=${JSON.stringify(row)}::text::jsonb WHERE id=${id}`;
            let refusal;
            try { await loadSpells(); } catch (error) { refusal = error.message; }
            if (!refusal?.includes(id) || !refusal.includes(diagnostic)) {
              throw new Error(`Expected ${id} and ${diagnostic}, got ${refusal}`);
            }
          }
        } finally {
          await sql`UPDATE spells SET data=${JSON.stringify(original_data)}::text::jsonb WHERE id=${id}`;
          await sql.close();
        }
        """,
        cwd=ROOT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(
        json.dumps(dict(original_data=original_data, bad_rows=bad_rows, id=SPELL)).encode()
    )
    assert process.returncode == 0, stderr.decode()
    loaded = next(line for line in stdout.splitlines() if line.startswith(b"{"))
    assert json.loads(loaded) == PROFILE


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


@pytest.fixture
async def walk(reset_db_pool: str) -> AsyncIterator[MawlingHarness]:
    harness = MawlingHarness()
    try:
        await harness.prepare((5,), companion=None, tools=(activate,))
        harness.encounter_id = "bandit_ambush"
        yield harness
    finally:
        await harness.close()


async def prepare(walk: MawlingHarness, archetype: str, level: int = 5, focus: int = 4, stamina: int = 3) -> str:
    pid = walk.players[0]
    row = await db_queries.get_player(pid)
    assert row is not None
    row["class"] = archetype
    row.update(level=level, focus={"current": focus, "max": 10}, stamina={"current": stamina, "max": 10})
    await walk.pool.execute("UPDATE players SET data=$2 WHERE player_id=$1", pid, json.dumps(row))
    if archetype != "druid":
        await seed_known_spells(walk.pool, pid, (SPELL,))
    return pid


async def enter(walk: MawlingHarness) -> None:
    await walk.command("enter_mode", {"mode": "combat", "encounter_id": walk.encounter_id})


async def declare(walk: MawlingHarness, action: str, form: str, *, error: bool = False):
    state = await walk.reload()
    pid = walk.players[0]
    return await walk.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "ability",
                    "actor_id": pid,
                    "action": action,
                    "targets": [],
                    "argument_type": form,
                    "reshape": [],
                },
                *({"kind": "defend", "actor_id": p.id, "reshape": []} for p in state.participants if p.id != pid),
            ]
        },
        error=error,
    )


def updates(walk: MawlingHarness) -> list[dict]:
    room = walk.sd.room
    assert room is not None
    publish = room.local_participant.publish_data
    assert isinstance(publish, AsyncMock)
    return [
        event
        for call in publish.call_args_list
        if (event := json.loads(call.args[0]))["type"] == event_types.COMBAT_UI_UPDATE
    ]


async def crossbow_receipt(walk: MawlingHarness, monkeypatch: pytest.MonkeyPatch, pid: str) -> dict:
    state = await walk.reload()
    attack = {
        "kind": "attack",
        "actor_id": "bandit_1",
        "target_id": pid,
        "action": "Light Crossbow",
        "held_item_id": "",
        "rider": "",
        "quick_fingers_mode": "",
        "quick_fingers_item": "",
        "reshape": [],
    }
    await walk.command(
        "declare_phase",
        {
            "declarations": [
                attack,
                *(
                    {"kind": "defend", "actor_id": p.id, "reshape": []}
                    for p in state.participants
                    if p.id not in (pid, "bandit_1")
                ),
            ]
        },
    )
    with monkeypatch.context() as patch:
        patch.setattr("check_resolution.dice_roll", lambda *_, **__: _d20(8))
        enemy_packets = await walk.drain()
    enemy = next(p for p in enemy_packets if p["actor_id"] == "bandit_1")
    return enemy


@pytest.mark.parametrize(
    ("archetype", "level", "form", "hp", "ac", "name"),
    [
        ("druid", 5, "grey_wolf", 11, 12, "Grey Wolf"),
        ("druid", 10, "dire_bear", 60, 14, "Dire Bear"),
        ("beastcaller", 5, "steppe_bison", 28, 11, "Steppe Bison"),
        ("warden", 5, "steppe_bison", 28, 11, "Steppe Bison"),
    ],
)
async def test_transform(
    walk: MawlingHarness,
    monkeypatch: pytest.MonkeyPatch,
    archetype: str,
    level: int,
    form: str,
    hp: int,
    ac: int,
    name: str,
) -> None:
    pid = await prepare(walk, archetype, level)
    await enter(walk)
    initial = await walk.reload()
    before = initial.get_participant(pid)
    assert before is not None
    if form == "grey_wolf":
        ordinary = await crossbow_receipt(walk, monkeypatch, pid)
        assert (ordinary["hit"], ordinary["attack_total"], ordinary["target_ac"]) == (False, 12, before.ac)
        initial = await walk.reload()
    action = ABILITY if archetype == "druid" else SPELL
    catalog = await walk.command("get_spell_info", {"spell_id": SPELL})
    if isinstance(catalog, str):
        catalog = json.loads(catalog)
    assert any(option["creature_id"] == form for option in catalog["wild_shape"]["forms"])
    await declare(walk, action, form)
    first = await walk.command("resolve_phase", {})
    row = await db_queries.get_player(pid)
    assert row is not None
    assert (row["focus"]["current"], row["stamina"]["current"]) == (0, 0)
    assert row["hp"]["current"] == before.hp_current
    allied = await walk.reload()
    assert [p for p in allied.participants if not p.is_ally] == [p for p in initial.participants if not p.is_ally]
    packets = first["packets"] + await walk.drain()
    packet = next(p for p in packets if p["actor_id"] == pid)
    assert packet["wild_shape"] == {"form_id": form, "name": name, "hp_current": hp, "hp_max": hp}
    if action == SPELL:
        assert packet["cast"]["resonance_generated"] > 0
    else:
        assert packet["effect"] and packet["narration_cue"]
    assert any(
        p.get("wildShape") == {"formId": form, "name": name, "hpCurrent": hp, "hpMax": hp}
        for event in updates(walk)
        for p in event["combatants"]
        if p["id"] == pid
    )
    state = await walk.reload()
    raw = json.loads(await walk.pool.fetchval("SELECT data FROM combat_instances WHERE combat_id=$1", state.combat_id))
    saved = next(p for p in raw["participants"] if p["id"] == pid)
    assert saved["wild_shape"] == {
        "form_id": form,
        "name": name,
        "hp_current": hp,
        "hp_max": hp,
        "original_ac": before.ac,
        "original_action_pool": before.action_pool,
        "original_deferred_effects": before.deferred_effects,
    }
    participant = state.get_participant(pid)
    assert participant is not None
    assert participant.wild_shape == saved["wild_shape"]
    assert participant.ac == ac and participant.hp_current == before.hp_current
    row = await db_queries.get_player(pid)
    assert row is not None
    assert (row["focus"]["current"], row["stamina"]["current"]) == (0, 0)

    if form == "grey_wolf":
        assert before.ac > 12
        enemy = await crossbow_receipt(walk, monkeypatch, pid)
        assert (enemy["hit"], enemy["attack_total"], enemy["target_ac"]) == (True, 12, 12)
        reloaded = (await walk.reload()).get_participant(pid)
        assert reloaded is not None and reloaded.wild_shape == saved["wild_shape"]


@pytest.mark.parametrize("archetype", ["druid", "warden"])
async def test_activate_is_combat_only(walk: MawlingHarness, archetype: str) -> None:
    pid = await prepare(walk, archetype)
    before = await db_queries.get_player(pid)
    action = ABILITY if archetype == "druid" else SPELL
    assert "combat-only" in await walk.command("activate", {"id": action}, error=True)
    assert await db_queries.get_player(pid) == before
    await enter(walk)
    before = await db_queries.get_player(pid)
    assert "declare_phase" in await walk.command("activate", {"id": action}, error=True)
    assert await db_queries.get_player(pid) == before
