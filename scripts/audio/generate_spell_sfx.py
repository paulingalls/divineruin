#!/usr/bin/env python3
"""Generate the full non-spell + spell audio inventory via ElevenLabs Text-to-Sound.

PROMPTS is the single prompt SSOT for every bundled sound in
apps/mobile/assets/sounds/ (SFX, spell SFX, music, soundscapes, textures),
guarded by apps/agent/tests/test_generate_spell_sfx.py for full asset parity.
The original 7-key spell-cast palette (M17, story-002) is frozen within this
table — see docs/audio_sfx_pipeline.md §4. This is the ElevenLabs (.mp3)
bake-off generator, and it owns the shared PROMPTS table + _out_path helper
— the single prompt SSOT that generate_spell_sfx_stableaudio.py imports.

NOTE ON THE COMMITTED PALETTE: the shipped assets are the .wav files produced by
generate_spell_sfx_stableaudio.py (Stable Audio 3.0 Small SFX), the vendor that
won the story-002 bake-off. To REGENERATE the committed palette, run that script,
not this one. Use this ElevenLabs generator for A/B comparison or as the
alternative engine — both share the frozen prompts, so they stay comparable ("Audio
Must Be Generatable"; regeneration is generative, not byte-for-byte).

Stdlib only (urllib) — no third-party deps. Reads ELEVEN_LABS_API_KEY from the
environment (fail-loud), the only external input.

Usage:
    export ELEVEN_LABS_API_KEY=...            # or `source ~/.zprofile`
    python scripts/audio/generate_spell_sfx.py --out-dir apps/audio/spell_sfx
    python scripts/audio/generate_spell_sfx.py --out-dir /tmp/bakeoff --variants 2
    python scripts/audio/generate_spell_sfx.py --keys spell_nature spell_radiant
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# The full bundled-audio prompt SSOT. The first 7 keys are the frozen M17
# spell-cast palette (prompts for the four "direct" keys carry the
# CMB-006/007/008/009 language from the prior harness
# ~/src/clones/stable-audio-tools/generate_divine_ruin.py; the last three are
# new casts (radiant/nature/generic) that had no prior prompt) — each tuned as a
# short, dry, punchy game SFX so it lands in the gaps between DM narration. The
# remaining keys (story-001, M22) extend the table to every other bundled
# stem: top-level SFX and textures/ stay dry one-shots; sting stems are
# melodic musical flourishes exempt from the dry style; music/ and
# soundscapes/ are tonal loops/beds, not dry SFX.
PROMPTS: dict[str, str] = {
    "spell_fire": (
        "Fantasy fire spell being cast and released. A soft inward whoosh as energy "
        "gathers, then a sharp ignition crack and a brief roar of expanding flame that "
        "fades to a dissipating crackle. Explosive magical release, not a sustained "
        "burn. Short, punchy game sound effect, dry, no music."
    ),
    "spell_ice": (
        "Fantasy ice spell being cast and released. A high glassy hiss as the air "
        "freezes, a sharp crystalline crack like rich shattering glass, then a brittle "
        "scatter of ice shards. High and bright, cold and precise. Short, punchy game "
        "sound effect, dry, no music."
    ),
    "spell_arcane_force": (
        "Fantasy arcane force spell being discharged. A low subsonic hum building "
        "rapidly in pitch, releasing as a concussive low-frequency thump felt in the "
        "chest, then a brief whoosh of displaced air. Heavy, low-mid, it pushes rather "
        "than crackles. Short, punchy game sound effect, dry, no music."
    ),
    "spell_heal": (
        "Fantasy healing spell activating. Soft and warm: a gentle rising tone like a "
        "quiet choir note from silence, releasing into a warm chime with a resonant "
        "shimmering tail. High-mid, no bass, kind and relieving. Short game sound "
        "effect, dry, no music."
    ),
    "spell_radiant": (
        "Fantasy divine radiant spell being cast, a smite of holy light. A warm "
        "ascending cathedral-like chime with a golden shimmer, releasing as a clean "
        "resonant burst of radiance. Authoritative and holy, not a heal. Short, punchy "
        "game sound effect, dry, no music."
    ),
    "spell_nature": (
        "Fantasy primal nature spell being cast. Sudden organic growth: rustling earth, "
        "cracking wood, and whipping vines and thorns erupting, with a green living "
        "texture. Earthy and alive. Short, punchy game sound effect, dry, no music."
    ),
    "spell_generic": (
        "A generic fantasy magic spell being cast. A neutral arcane shimmer and whoosh "
        "with a soft chime as energy gathers and releases, no specific element. Short "
        "game sound effect, dry, no music."
    ),
    # --- SFX (top-level, story-001 M22 extension) ---
    # Sting stems (level_up, success, fail, quest, critical_hit, god_whisper) are
    # idiomatically melodic musical flourishes, not dry SFX — no "no music" guard.
    "dice_roll": (
        "Several polyhedral tabletop dice tumbling and clattering across a wooden table, "
        "hard plastic clicks with a final settling rattle. Short, dry, no music."
    ),
    "sword_clash": (
        "Two steel sword blades clashing together in combat, a sharp ringing metallic "
        "clang with a brief bright resonant tail. Short, punchy game sound effect, dry, "
        "no music."
    ),
    "tavern": (
        "A single warm tavern door chime, a soft wooden clunk with a small brass bell "
        "tap as it swings. Short, dry, no music."
    ),
    "quest_sting": (
        "A short heroic musical fanfare marking a new quest accepted. A bright rising "
        "brass and string flourish resolving to a confident major chord, uplifting and "
        "purposeful. Brief tonal stinger."
    ),
    "level_up_sting": (
        "A triumphant short musical stinger for a character leveling up. An ascending "
        "arpeggio of bright bell and chime tones resolving into a glowing major chord, "
        "rewarding and celebratory. Brief tonal stinger."
    ),
    "item_pickup": (
        "A small item being picked up, a soft high pitched twinkling chime with a "
        "quick upward pop. Short, dry, no music."
    ),
    "notification": (
        "A gentle UI notification alert, a clean two-tone soft chime, polite and unobtrusive. Short, dry, no music."
    ),
    "success_sting": (
        "A short satisfying musical stinger marking a successful action. A quick "
        "bright ascending three-note chime landing on a warm resolved tone, positive "
        "and light. Brief tonal stinger."
    ),
    "fail_sting": (
        "A short musical stinger marking a failed action. A brief descending minor "
        "phrase on low muted tones, deflating but not harsh. Brief tonal stinger."
    ),
    "menu_open": (
        "A UI menu opening, a soft airy whoosh with a light upward pop, unobtrusive "
        "interface sound. Short, dry, no music."
    ),
    "menu_close": (
        "A UI menu closing, a soft airy whoosh with a light downward pop, unobtrusive "
        "interface sound. Short, dry, no music."
    ),
    "arrow_loose": (
        "A bow being drawn and an arrow loosed, a taut string creak releasing into a "
        "sharp elastic thwip and fading air-cutting whistle. Short, punchy game sound "
        "effect, dry, no music."
    ),
    "hit_taken": (
        "A character taking a physical hit in combat, a dull heavy thud impact with a "
        "short pained grunt undertone. Short, punchy game sound effect, dry, no music."
    ),
    "critical_hit_sting": (
        "An emphatic musical stinger marking a critical hit. A sharp bright orchestral "
        "hit accented with a fast rising brass swell, dramatic and forceful. Brief "
        "tonal stinger."
    ),
    "spell_cast": (
        "A generic magic spell being cast, a rising arcane shimmer with a soft "
        "whooshing release, no specific element. Short, punchy game sound effect, "
        "dry, no music."
    ),
    "shield_block": (
        "A raised shield absorbing a blow, a solid metallic clank with a brief low "
        "resonant thud. Short, punchy game sound effect, dry, no music."
    ),
    "potion_use": (
        "A potion bottle being uncorked and drunk, a soft glass clink, a light liquid "
        "gulp, and a satisfied exhale. Short, dry, no music."
    ),
    "door_creak": (
        "A heavy wooden door creaking open on old hinges, a slow groaning wood and metal strain. Short, dry, no music."
    ),
    "discovery_chime": (
        "A moment of discovery, a bright sparkling ascending chime with a light "
        "shimmering tail, curious and rewarding. Short, dry, no music."
    ),
    "god_whisper_stinger": (
        "An eerie musical stinger for a god's whisper reaching the player. A low "
        "sustained choir drone swelling with a faint dissonant shimmer, reverent and "
        "unsettling. Brief tonal stinger."
    ),
    # --- MUSIC (music/, short loop or stinger, tonal — NOT "no music") ---
    "exploration": (
        "A calm exploration music loop for wandering a fantasy world. Gentle acoustic "
        "strings and soft woodwind melody over a light steady pulse, curious and "
        "unhurried. Seamless short musical loop."
    ),
    "tension": (
        "A tense underscore music loop for a suspenseful moment. Low sustained strings "
        "with a slow uneasy pulse and sparse dissonant accents, wary and watchful. "
        "Seamless short musical loop."
    ),
    "combat_standard": (
        "A driving combat music loop for a standard fantasy battle. Fast percussive "
        "strings and brass stabs over an urgent rhythmic pulse, aggressive and "
        "propulsive. Seamless short musical loop."
    ),
    "combat_boss": (
        "An intense boss battle music loop. Heavy low brass and pounding percussion "
        "with a dramatic rising motif, epic and menacing. Seamless short musical loop."
    ),
    "wonder": (
        "A music loop evoking awe and wonder at a marvel of the world. Shimmering "
        "high strings and soft choir swelling gently, expansive and luminous. Seamless "
        "short musical loop."
    ),
    "sorrow": (
        "A somber music loop for a moment of loss or grief. A slow mournful solo "
        "string melody over sparse low sustained tones, quiet and aching. Seamless "
        "short musical loop."
    ),
    "hollow_dissolution": (
        "An unsettling music loop for the Hollow's reality-warping intrusion. Detuned "
        "sustained tones sliding out of tune beneath a faint broken melodic fragment, "
        "wrong and dissonant. Seamless short musical loop."
    ),
    "title": (
        "A short heroic title theme stinger for the game's opening. A bold rising "
        "orchestral fanfare of brass and strings resolving into a grand sustained "
        "chord, epic and inviting. Brief tonal stinger."
    ),
    # --- SOUNDSCAPES (soundscapes/, seamless layered ambient bed) ---
    "market_bustle": (
        "A bustling fantasy market square. Overlapping distant vendor chatter, "
        "footsteps on cobblestone, and the occasional clink of coins and creak of "
        "wooden stalls. Seamless layered ambient bed."
    ),
    "harbor_quiet": (
        "A quiet fantasy harbor at rest. Gentle lapping water against wooden hulls, "
        "distant creaking ropes, and a soft sea breeze. Seamless layered ambient bed."
    ),
    "harbor_activity": (
        "A busy fantasy harbor at work. Overlapping dockworker shouts, creaking ship "
        "rigging, lapping water, and crates being dragged over wood. Seamless layered "
        "ambient bed."
    ),
    "rural_town_uneasy": (
        "A small rural town under quiet unease. Sparse distant voices, a slow wind "
        "through empty streets, and an occasional wary silence. Seamless layered "
        "ambient bed."
    ),
    "dungeon_ancient_hum": (
        "A deep ancient dungeon chamber. A low sustained stone resonance, distant "
        "dripping water, and a faint echoing hum from unseen depths. Seamless layered "
        "ambient bed."
    ),
    "dungeon_resonance_deep": (
        "A vast deep dungeon cavern. A heavy low resonant drone, distant echoing "
        "drips, and faint far-off stone settling. Seamless layered ambient bed."
    ),
    "hollow_wrongness": (
        "A space touched by the Hollow's wrongness. A faint detuned drone beneath "
        "silence, occasional inverted echoes, and an unnatural absence of expected "
        "sound. Seamless layered ambient bed."
    ),
    "guild_hall_bustle": (
        "A busy adventurers' guild hall. Overlapping conversation, the clink of "
        "tankards, shuffling parchment, and a crackling hearth fire. Seamless layered "
        "ambient bed."
    ),
    "temple_row_chanting": (
        "A row of temples with distant devotional chanting. Layered low choral "
        "murmurs, soft echoing stone acoustics, and the faint ring of a temple bell. "
        "Seamless layered ambient bed."
    ),
    "tavern_busy": (
        "A lively crowded tavern. Overlapping laughter and chatter, clinking mugs, a "
        "creaking floor, and a faint background lute melody. Seamless layered ambient "
        "bed."
    ),
    "wind_ruins": (
        "Wind moving through ancient crumbling ruins. A steady hollow wind whistling "
        "through broken stone, with occasional loose debris shifting. Seamless "
        "layered ambient bed."
    ),
    # --- TEXTURES (textures/, short dry foley one-shots) ---
    "bird_call_01": (
        "A single bright songbird call in a forest, a short clear chirping trill. Short, dry, no music."
    ),
    "bird_call_02": (
        "A single distinct songbird call, a short warbling two-note whistle. Short, dry, no music."
    ),
    "bird_call_03": (
        "A single distant songbird call, a short soft fluting chirp. Short, dry, no music."
    ),
    "cart_wheel": (
        "A wooden cart wheel creaking and rolling over a rutted dirt road, a rhythmic "
        "wood and axle groan. Short, dry, no music."
    ),
    "water_drip": (
        "A single water droplet falling and landing in a still pool, a small clear "
        "plink with a faint echo. Short, dry, no music."
    ),
    "footstep_stone": (
        "A single footstep on a hard stone floor, a crisp solid footfall tap. Short, dry, no music."
    ),
    "wind_gust": (
        "A sudden gust of wind sweeping past, a short rushing air whoosh rising and fading. Short, dry, no music."
    ),
    "dog_bark_distant": (
        "A dog barking from far away, a short muffled distant bark with a faint echo. Short, dry, no music."
    ),
    "insect_buzz": (
        "A single insect buzzing past close by, a brief high-pitched droning flutter. Short, dry, no music."
    ),
    "fire_crackle": (
        "A small campfire crackling, a short burst of wood pops and a soft crackling hiss. Short, dry, no music."
    ),
    "branch_crack": (
        "A dry tree branch snapping underfoot, a single sharp brittle wood crack. Short, dry, no music."
    ),
}

_API_URL = "https://api.elevenlabs.io/v1/sound-generation"
_MODEL_ID = "eleven_text_to_sound_v2"
_OUTPUT_FORMAT = "mp3_44100_128"
_ENV_KEY = "ELEVEN_LABS_API_KEY"


def _require_api_key() -> str:
    key = os.environ.get(_ENV_KEY, "").strip()
    if not key:
        sys.exit(
            f"{_ENV_KEY} is not set. `source ~/.zprofile` (or export it) before running."
        )
    return key


def _generate_one(
    text: str, *, duration: float, prompt_influence: float, loop: bool, api_key: str
) -> bytes:
    """POST one prompt to ElevenLabs and return the MP3 bytes. Fail-loud on any HTTP error."""
    body = json.dumps(
        {
            "text": text,
            "duration_seconds": duration,
            "prompt_influence": prompt_influence,
            "loop": loop,
            "model_id": _MODEL_ID,
        }
    ).encode()
    req = urllib.request.Request(
        f"{_API_URL}?output_format={_OUTPUT_FORMAT}",
        data=body,
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"ElevenLabs HTTP {e.code} for prompt: {text[:60]!r}...\n{detail}")


def out_path(
    out_dir: Path, key: str, variant: int, total_variants: int, ext: str = ".mp3"
) -> Path:
    """Shared palette-file namer. ext is the engine's format (.mp3 here, .wav for Stable Audio)."""
    name = f"{key}{ext}" if total_variants == 1 else f"{key}_v{variant}{ext}"
    return out_dir / name


def generate(
    keys: list[str],
    out_dir: Path,
    *,
    variants: int,
    duration: float,
    prompt_influence: float,
    loop: bool,
) -> list[Path]:
    """Generate the requested palette keys into out_dir. Idempotent: skips existing files."""
    api_key = _require_api_key()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for key in keys:
        prompt = PROMPTS[key]
        for v in range(1, variants + 1):
            path = out_path(out_dir, key, v, variants)
            if path.exists():
                print(f"skip (exists): {path}")
                continue
            audio = _generate_one(
                prompt,
                duration=duration,
                prompt_influence=prompt_influence,
                loop=loop,
                api_key=api_key,
            )
            path.write_bytes(audio)
            print(f"wrote {path} ({len(audio)} bytes)")
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the full bundled audio prompt inventory."
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--keys",
        nargs="*",
        default=sorted(PROMPTS),
        help=f"subset of palette keys (default: all {len(PROMPTS)})",
    )
    parser.add_argument(
        "--variants", type=int, default=1, help="takes per key (default 1)"
    )
    parser.add_argument("--duration", type=float, default=2.0, help="seconds, 0.5-30")
    parser.add_argument("--prompt-influence", type=float, default=0.5)
    parser.add_argument("--loop", action="store_true", help="request a seamless loop")
    args = parser.parse_args(argv)

    unknown = [k for k in args.keys if k not in PROMPTS]
    if unknown:
        parser.error(f"unknown keys: {unknown}. Valid: {sorted(PROMPTS)}")

    generate(
        args.keys,
        args.out_dir,
        variants=args.variants,
        duration=args.duration,
        prompt_influence=args.prompt_influence,
        loop=args.loop,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
