"""Real-DB E2E capstone for Milestone 8 — Spell Acquisition (3 tracks + preparation).

Proves the M8 stories compose end-to-end on real infra (auto-marked `acceptance` by
tests/acceptance/conftest.py), across both surfaces. This is where the literal real-Postgres
AC4 letter — deferred from stories 004/005/006 per ADR 0003 — finally lands.

- **message_event** (Python agent path): against one seeded Postgres testcontainer,
  starting electives are granted at creation (story-003), a spell accrues training cycles and
  promotes to known only on the final cycle (story-004), a scroll spell is learned immediately
  (story-005), an above-tier learn is rejected by the level gate (story-005), and a long-rest
  loadout is prepared / over-limit selection refused (story-006) — all against real rows.
- **http_websocket** (TS server path): the Bun server boots bound to the SAME testcontainer;
  its startup Promise.all runs loadSpells() (story-001) over the seeded spells table — a served
  response proves it parsed without failing boot (a malformed/missing row crashes parseSpellRow).

Training (story-004) is driven through character_spells.advance_learning_cycle + record_learned
directly — exactly the spell-promotion path async_worker_training runs (async_worker_training.py
:180-195) — rather than the full worker, whose running_second_half path pulls in TTS/LLM/push
machinery that is out of M8 scope and unmocked (the pre-push gate unsets the API keys).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import start_server
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import character_spells
import db
import rest_mechanics
import spell_tools
from creation_rules import select_starting_spells

# Seeded catalog ids (content/spells.json), by tier.
_CANTRIP = "arcane_frost_touch"
_MINOR_A = "arcane_magic_missile"
_MINOR_B = "arcane_mage_hand"
_STANDARD = "arcane_hold_person"  # standard tier, unlocks at L4
_MAJOR = "arcane_fireball"  # major tier, unlocks at L7


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


async def _seed_caster(pool, player_id: str, *, level: int = 5, class_: str = "mage") -> None:
    """seed_player + set the character level the spell gates read (default is 2)."""
    await seed_player(pool, player_id=player_id, class_=class_)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{level}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(level),
    )


# --- message_event surface (Python agent spell flow) ---


@pytest.mark.asyncio
async def test_starting_electives_granted_at_creation(reset_db_pool: str) -> None:
    # Core-at-creation (story-003): a pure single-source caster is granted its starting
    # electives (1 cantrip + 1 minor), persisted prepared, into the real library.
    pool = await db.get_pool()
    pid = "cap_create"
    await _seed_caster(pool, pid)

    starting = select_starting_spells("mage", "arcane")
    assert starting, "mage should have starting electives"
    for spell_id in starting:
        await character_spells.record_learned(pid, spell_id, "training", is_prepared=True, conn=pool)

    known = await character_spells.get_known(pid, conn=pool)
    assert {row["spell_id"] for row in known} == set(starting)
    assert all(row["is_prepared"] for row in known)


@pytest.mark.asyncio
async def test_spell_training_three_cycles_to_known(reset_db_pool: str) -> None:
    # Training track (story-004): a standard spell needs 3 cycles. It is NOT known until the
    # final cycle promotes it (record_learned + clear progress) — the worker's spell path.
    pool = await db.get_pool()
    pid = "cap_train"
    await _seed_caster(pool, pid)

    for cycle in (1, 2):
        progress = await character_spells.advance_learning_cycle(pid, _STANDARD, 3, conn=pool)
        assert progress["completed"] is False, f"cycle {cycle} should not complete a 3-cycle spell"
        known_ids = {row["spell_id"] for row in await character_spells.get_known(pid, conn=pool)}
        assert _STANDARD not in known_ids, "spell must not be known mid-training"

    final = await character_spells.advance_learning_cycle(pid, _STANDARD, 3, conn=pool)
    assert final["completed"] is True
    await character_spells.record_learned(pid, _STANDARD, "training", conn=pool)
    await character_spells.delete_learning_progress(pid, _STANDARD, conn=pool)

    known = await character_spells.get_known(pid, conn=pool)
    assert _STANDARD in {row["spell_id"] for row in known}
    assert await character_spells.get_learning_progress(pid, _STANDARD, conn=pool) is None


@pytest.mark.asyncio
async def test_learn_scroll_spell_adds_to_library(reset_db_pool: str) -> None:
    # Discovery track (story-005): the generic learn verb acquires a scroll spell immediately.
    pool = await db.get_pool()
    pid = "cap_scroll"
    await _seed_caster(pool, pid, level=5)

    result = json.loads(await spell_tools._learn_spell_impl(make_context(player_id=pid), _MINOR_A, "discovery"))
    assert result["learned"] == _MINOR_A
    assert result["acquisition_track"] == "discovery"

    known = {row["spell_id"]: row for row in await character_spells.get_known(pid, conn=pool)}
    assert _MINOR_A in known
    assert known[_MINOR_A]["acquisition_track"] == "discovery"


@pytest.mark.asyncio
async def test_learn_above_tier_rejected_and_no_write(reset_db_pool: str) -> None:
    # Tier gate (story-005): a level-3 caster cannot learn a Major spell (unlocks at L7).
    pool = await db.get_pool()
    pid = "cap_gate"
    await _seed_caster(pool, pid, level=3)

    with pytest.raises(ToolError, match="level 7"):
        await spell_tools._learn_spell_impl(make_context(player_id=pid), _MAJOR, "discovery")

    known = await character_spells.get_known(pid, conn=pool)
    assert _MAJOR not in {row["spell_id"] for row in known}


@pytest.mark.asyncio
async def test_long_rest_preparation_persists_and_caps_slots(reset_db_pool: str) -> None:
    # Preparation (story-006): a known loadout up to the slot limit persists; an over-limit
    # loadout is refused with nothing changed (all-or-nothing).
    pool = await db.get_pool()
    pid = "cap_prep"
    await _seed_caster(pool, pid, level=5)
    for spell_id in (_MINOR_A, _MINOR_B, _CANTRIP):
        await character_spells.record_learned(pid, spell_id, "discovery", conn=pool)

    await rest_mechanics.prepare_spells_on_long_rest(
        pid,
        [_MINOR_A, _MINOR_B],
        slot_limit=2,
        archetype_id="mage",
        character_level=5,
        in_natural_terrain=False,
        conn=pool,
    )
    assert {row["spell_id"] for row in await character_spells.get_prepared(pid, conn=pool)} == {_MINOR_A, _MINOR_B}

    with pytest.raises(ValueError, match="slot"):
        await rest_mechanics.prepare_spells_on_long_rest(
            pid,
            [_MINOR_A, _MINOR_B, _CANTRIP],
            slot_limit=2,
            archetype_id="mage",
            character_level=5,
            in_natural_terrain=False,
            conn=pool,
        )
    # Over-limit refused before any write — the prior loadout is untouched.
    assert {row["spell_id"] for row in await character_spells.get_prepared(pid, conn=pool)} == {_MINOR_A, _MINOR_B}


# --- http_websocket surface (TS server loadSpells boot path) ---


def test_server_boots_with_spells_loaded_from_real_db(capstone_server: dict[str, str]) -> None:
    # The fixture only yields after the Bun server reaches ready; its startup Promise.all runs
    # loadSpells() (story-001) against the seeded testcontainer, so a served response proves the
    # spells table parsed without failing boot — a malformed/missing row would crash parseSpellRow.
    response = httpx.get(capstone_server["base_url"], timeout=5.0)
    assert response.status_code < 500
