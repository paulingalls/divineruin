"""Capstone: M17 spell-SFX chain end-to-end (cast -> registry-valid key -> bundled asset).

M17 shipped the spell-audio pipeline across stories 001-004: a machine-playable
``sound_id`` on every ``content/spells.json`` row (strict Python loader,
``spells.SPELL_SOUND_KEYS``), the 7-key ``.mp3`` palette committed to
``apps/mobile/assets/sounds/``, the cross-language sound registry
(``apps/mobile/src/audio/sound-registry.ts``), and a deterministic
``PLAY_SOUND(sound_id)`` emit at cast resolution
(``spell_casting._resolve_cast``, story-004).

This capstone proves those seams hold TOGETHER against a real Postgres
testcontainer (auto-marked ``acceptance`` by tests/acceptance/conftest.py):

  1. Every seeded catalog spell maps to a registry-valid ``sound_id`` whose
     bundled ``.mp3`` asset exists on disk (no orphan key, no missing file).
  2. The TS registry itself resolves every catalog ``sound_id`` to a bundled
     asset -- run in-band via the story-003 cross-language guard under ``bun``.
  3. A REAL cast (the entry point ``cast_spell`` delegates to) deterministically
     emits exactly one ``PLAY_SOUND`` carrying the spell's registry-valid
     ``sound_id``, with no LLM in the path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sample_fixtures import make_context, make_mock_room, published_payloads

import db
import event_types as E
import spells
from spell_casting import _cast_spell_impl

# tests/acceptance/<this file> -> parents[3] is the repo's apps/ dir.
_APPS_DIR = Path(__file__).resolve().parents[3]
_SOUNDS_DIR = _APPS_DIR / "mobile" / "assets" / "sounds"  # bundled copy the app loads
_AUDIO_SRC_DIR = _APPS_DIR / "audio" / "spell_sfx"  # committed source palette (regenerate target)
_MOBILE_DIR = _APPS_DIR / "mobile"

# One clean cantrip per spell source (focus_cost 0, non-concentration) so the real
# cast resolves without a target/gate; together they exercise the ice/radiant/nature
# palette families across arcane/divine/primal.
_CANTRIPS_BY_SOURCE = ("arcane_frost_touch", "divine_sacred_flame", "primal_thorn_whip")


async def _seed_player(pool, player_id: str, **overrides) -> None:
    """Upsert a living players.data row with a full Focus pool (mirrors the M11 capstone)."""
    data = {"player_id": player_id, "class": "cleric", "level": 5, "focus": {"current": 10, "max": 10}}
    data.update(overrides)
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


def _all_spells() -> list[spells.Spell]:
    """The full loaded catalog, flattened across the closed source vocabulary."""
    return [s for src in ("arcane", "divine", "primal") for s in spells.get_spells_by_source(src)]


# --- 1. Every spell -> registry-valid key -> committed bundled asset on disk (AC1) ---


async def test_every_spell_maps_to_registry_key_and_bundled_asset(reset_db_pool: str) -> None:
    await spells.load_spells()
    catalog = _all_spells()
    assert catalog, "spell catalog is empty -- seed_content.seed() did not run"

    for spell in catalog:
        assert spell.sound_id in spells.SPELL_SOUND_KEYS, (
            f"{spell.id}: sound_id {spell.sound_id!r} is not a registry key"
        )
        asset = _SOUNDS_DIR / f"{spell.sound_id}.mp3"
        assert asset.exists(), f"{spell.id}: bundled asset missing at {asset}"


# --- 1b. The source palette and the bundled copy stay byte-identical (AC1, no stale-audio drift) ---


def test_source_and_bundled_palette_are_byte_identical() -> None:
    """apps/audio/spell_sfx (source SSOT) and apps/mobile/assets/sounds (bundled) must match.

    They are committed as byte-identical copies; nothing else asserts they stay in sync, so a
    regeneration that updates the source and forgets the bundled copy (or vice versa) would ship
    stale audio while every other lane stays green. This guard fails loud on that drift."""
    for key in sorted(spells.SPELL_SOUND_KEYS):
        src = _AUDIO_SRC_DIR / f"{key}.mp3"
        bundled = _SOUNDS_DIR / f"{key}.mp3"
        assert src.exists(), f"source asset missing: {src}"
        assert bundled.exists(), f"bundled asset missing: {bundled}"
        assert src.read_bytes() == bundled.read_bytes(), (
            f"{key}.mp3 differs between source ({src}) and bundled ({bundled}) -- regenerate both"
        )


# --- 2. The TS registry resolves every catalog sound_id to a bundled asset (AC1, "against the registry") ---


def test_registry_resolves_every_catalog_sound_id_via_bun() -> None:
    """Run the story-003 cross-language guard in-band so the capstone exercises the real
    TS registry->asset require() resolution, not just the Python SPELL_SOUND_KEYS mirror."""
    bun = shutil.which("bun")
    if bun is None:
        pytest.skip("bun not on PATH; the sound-registry.test.ts guard also runs in `bun run test:all`")
    result = subprocess.run(
        [bun, "test", "src/__tests__/sound-registry.test.ts"],
        cwd=_MOBILE_DIR,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"TS registry<->catalog guard failed:\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


# --- 3. A real cast deterministically emits PLAY_SOUND with a registry-valid key, no LLM (AC2 + E2E) ---


@pytest.mark.parametrize("spell_id", _CANTRIPS_BY_SOURCE)
async def test_real_cast_emits_deterministic_play_sound(reset_db_pool: str, spell_id: str) -> None:
    pool = await db.get_pool()
    caster_id = f"cap_m17_{spell_id}"
    await _seed_player(pool, caster_id)
    await spells.load_spells()
    spell = spells.get_spell(spell_id)

    ctx = make_context(player_id=caster_id, room=make_mock_room())
    # The real cast entry point cast_spell delegates to -- no spells_mod injection, no LLM.
    await _cast_spell_impl(ctx, spell_id)

    play_sounds = [p for p in published_payloads(ctx.userdata.room) if p["type"] == E.PLAY_SOUND]
    assert len(play_sounds) == 1, (
        f"expected exactly one PLAY_SOUND for {spell_id}, "
        f"got types {[p['type'] for p in published_payloads(ctx.userdata.room)]}"
    )
    emitted = play_sounds[0]["sound_name"]
    # The whole chain ties here: cast -> emit -> registry-valid key -> committed asset.
    assert emitted == spell.sound_id
    assert emitted in spells.SPELL_SOUND_KEYS
    assert (_SOUNDS_DIR / f"{emitted}.mp3").exists()
