# Audio SFX Pipeline — Spell Cast Sound Effects (M17)

## 1. Goal & Principle

Combat already emits `PLAY_SOUND` deterministically for weapon/status effects
(`apps/agent/combat_support.py` `_publish_sounds`). Spell casts emit nothing — the
biggest audio gap in the game today, since ~half of all combat actions in a
level-appropriate party are spellcasting. M17 closes this gap: every spell cast
plays a real SFX, wired through a deterministic engine-emitted `PLAY_SOUND` (rules
engine decides *that* a sound plays; no LLM judgment call).

Per `docs/audio_design.md`'s Fifth Principle ("Audio Must Be Generatable", L42-48),
every asset must be reproducible from a written prompt — no one-off studio
recordings. This doc decides *how* spell SFX get generated and freezes the
`sound_id` keying scheme that story-002 (asset filenames) and story-003 (registry +
per-spell key assignment) both consume.

Out of scope for this doc: writing `content/spells.json`, the registry, or any
code. Purely research + contract.

## 2. Service Evaluation

Evaluated four options. Figures below were pulled from the vendors' live pages on
2026-07-05 except where noted.

| | **ElevenLabs SFX V2** | **Stability Stable Audio 3.0** | **Meta AudioGen/AudioCraft** | **Stdlib procedural synth** |
|---|---|---|---|---|
| API shape | REST, text prompt → SFX; returns 4 samples per prompt | REST credit API (hosted) **or** open-weight checkpoints you run yourself | Open-source, self-hosted only (research code, no hosted API) | No API — Python `wave` module, generate locally |
| Per-asset cost | Free plan: non-commercial only. Paid: Starter $6/mo (bundles pay-as-you-go SFX credits, no per-asset licensing fee once paid) | Hosted: ~1 credit = $0.01; text-to-audio generation ≈20 credits ≈ $0.20/gen (per prior evaluation — **could not re-confirm on 2026-07-05: platform.stability.ai/pricing is JS-rendered and returned no content to WebFetch; re-check before committing spend**). Self-hosted open-weight models: $0 marginal cost, just compute | $0 (self-hosted), but no production-viable path (see below) | $0 — pure computation, no network dependency |
| Commercial licensing | Free plan explicitly "non-commercial purposes." Paid plans: "no licensing fees or royalties," usable in commercial projects; cannot resell the *tool* itself | Community License: free commercial use while org revenue < $1M/yr; Stable Audio 3.0 is explicitly covered; over $1M needs an Enterprise License. Open-weight "3.0 Small SFX" ships under the same Community License and can be self-hosted | Released **research-only** — Meta's model license does not grant a clean commercial-use path. Evaluated and rejected on licensing grounds alone | Public-domain code we write; no third-party license at all |
| Output format/quality/length | 48kHz, ≤30s, supports seamless looping; strongest quality on precise text→SFX prompts (their headline use case) | Text-to-audio general purpose (music-leaning); SFX quality is decent but the product is not SFX-specialized like ElevenLabs' | Environmental/ambient sound generation; not tuned for short punchy game SFX | Deterministic tones/noise envelopes/simple waveform synthesis — good for stingers, chimes, hums, drones; not for "organic tearing" or complex textures |
| Prose→prompt fit | Excellent — built for exactly this (short descriptive prompt in, short SFX out) | Good, but tuned more for music/ambience than punchy one-shot SFX | Poor fit for combat/spell SFX cadence | N/A — the fallback doesn't consume a prose prompt, it consumes a hand-picked synth recipe (tone/noise/envelope params) *inspired* by the prose |
| Account/key required | Yes — ElevenLabs account + API key, ~$6/mo minimum paid tier for commercial rights | Yes for hosted API; **no** for self-hosted open-weight models (local download, no key) | N/A — no supported hosted path | No |

Sources: `elevenlabs.io/pricing/api`, `elevenlabs.io/sound-effects`, `stability.ai/license` (fetched 2026-07-05). Stability's hosted per-credit pricing page did not render for automated fetch; the $0.01/credit, ~20 credits/gen figures are carried from prior team research and are flagged above as needing a manual re-check before any purchase.

## 3. Recommendation

**Primary: ElevenLabs SFX V2, if the customer provisions an account + paid API key
(~$6/mo Starter).** It is purpose-built for exactly this pipeline — short prose
prompt in, short polished SFX out, 48kHz, seamless looping, royalty-free
commercial use on any paid tier. For ~90 spell/combat SFX generated once (not
per-session, not per-player), this is a one-time few-dollar-to-tens-of-dollars
spend, not a recurring meaningful cost. **Yes, it's worth it** — the quality gap
between a purpose-built SFX model and either open-weight alternative or hand-built
procedural synth is large for anything beyond simple tones (fire whoosh, ice
shatter, organic tearing, whip crack).

**Secondary / no-account alternative: Stability's open-weight "Stable Audio 3.0
Small SFX".** Free to download and self-host under the Community License (covers
commercial use under $1M revenue), so it's the "generatable-in-repo" option if the
customer does *not* want to provision a paid third-party key — no ongoing account,
no API cost, just local/CI compute. Lower quality ceiling than the hosted
ElevenLabs product and needs a model-serving story (weights, inference deps) this
project doesn't have yet — treat as a fallback-of-the-fallback, not the MVP path.

**Fallback (always available, zero dependency): stdlib procedural synth.** Keeps
M17 deliverable with **no account, no key, no third-party dependency at all** —
just Python's built-in `wave` module generating tones/noise/envelopes. This is
the right choice for the *sprint's* zero-dependency constraint (per the sprint's
own assumption that the pipeline must be deliverable without an account) and
remains the reference recipe below. Meta AudioGen/AudioCraft was evaluated and
rejected outright — no viable commercial license.

**Bottom line:** if/when the customer provisions the ElevenLabs key, regenerate
the palette with it for final quality; ship and test with the stdlib synth
fallback in the meantime — the keying scheme (§4) and file layout (§6) are
identical either way, only the generation step changes.

## 4. Keying Scheme (FROZEN CONTRACT for stories 002/003)

`audio_cue` (free-text, director prose + generation prompt) and `sound_id` (new
machine field, story-003) are separate. `sound_id` is keyed by **effect family**
— the acoustically distinct axis — because that's what the ear actually
distinguishes; `source` (arcane/divine/primal) is an optional timbre modifier only
where the *same* effect family sounds meaningfully different by source (none of
the 87 spells currently need a source-prefixed variant — see the "notes" column
below for the one candidate, healing, where MVP still collapses to one key).

### MVP Palette (7 keys)

| `sound_id` | Effect family | Covers |
|---|---|---|
| `spell_fire` | Fire / heat / explosive burn | Fireball, flame strike, meteor swarm, produce flame, etc. |
| `spell_ice` | Cold / crystallization / shatter | Frost touch, ice storm |
| `spell_arcane_force` | Force, arcane hum→thump, lightning/electric arcs, generic "power" builds | Arcane bolt, magic missile, chain lightning, call lightning, wall of force |
| `spell_heal` | Warm rising tone + gentle chime, restorative | Heal wounds, healing touch, mass heal, regenerate, greater restoration |
| `spell_radiant` | Divine light, choral, holy-authority tones (non-healing divine effects) | Sacred flame, bless, holy aura, divine judgment |
| `spell_nature` | Organic growth/decay, wind, water, animal, earth — primal's non-elemental texture | Entangle, wild shape, thorn whip, earthquake, tsunami |
| `spell_generic` | Everything else: shimmers, whooshes, locks, silence beats, utility cantrips, out-of-family narrative effects (deity voice cues, Veil distortion) | Prestidigitation, mist step, counterspell, teleport, time stop |

This is the **frozen contract**: story-002 names asset files after these 7 keys
(one .wav/.mp3 per key, or numbered variants per key — e.g. `spell_fire_01.wav`),
and story-003 assigns each spell's `sound_id` field to one of these 7 literals.
Do not rename these keys without updating both downstream stories.

### Authoring Table — all 87 spells → palette key

**Arcane (30)**

| Spell id | audio_cue | `sound_id` |
|---|---|---|
| arcane_frost_touch | CMB-007 | spell_ice |
| arcane_bolt | CMB-008 | spell_arcane_force |
| arcane_spark | CMB-008 variant | spell_arcane_force |
| arcane_prestidigitation | Faint shimmer + soft chime | spell_generic |
| arcane_mage_light | Soft chime | spell_generic |
| arcane_shield_spell | CMB-008 (soft) | spell_arcane_force |
| arcane_detect_magic | Subtle shimmer | spell_generic |
| arcane_mage_hand | Soft hum | spell_generic |
| arcane_magic_missile | CMB-008 (triple) | spell_arcane_force |
| arcane_mist_step | Displacement whoosh | spell_generic |
| arcane_arcane_lock | Lock + magic hum | spell_generic |
| arcane_elemental_burst | CMB-006/7/8 (chosen at cast time) | spell_arcane_force *(default; engine may instead route by chosen element to spell_fire/spell_ice/spell_arcane_force — see note below)* |
| arcane_hold_person | Low thrum + lock | spell_generic |
| arcane_counterspell | Sharp crack + silence | spell_generic |
| arcane_dispel_magic | Reverse shimmer | spell_generic |
| arcane_fly | Rising wind | spell_generic |
| arcane_invisibility | Displacement hiss | spell_generic |
| arcane_fireball | CMB-006 (powerful) | spell_fire |
| arcane_lightning_bolt | CMB-008 (sustained) | spell_arcane_force |
| arcane_wall_of_force | Deep resonant hum | spell_arcane_force |
| arcane_haste | Accelerating pulse | spell_generic |
| arcane_slow | Decelerating tone | spell_generic |
| arcane_arcane_eye | Soft hum | spell_generic |
| arcane_chain_lightning | CMB-008 + arcs | spell_arcane_force |
| arcane_disintegrate | Charge then silence | spell_generic |
| arcane_teleport | Reality bending | spell_generic |
| arcane_power_word_stun | Subsonic pulse | spell_generic |
| arcane_maze | Spatial distortion | spell_generic |
| arcane_meteor_swarm | Whistle then quad detonation | spell_fire |
| arcane_time_stop | All sound ceases then heartbeat | spell_generic |

**Divine (28)**

| Spell id | audio_cue | `sound_id` |
|---|---|---|
| divine_sacred_flame | CMB-009 variant (offensive radiance) | spell_radiant |
| divine_guiding_light | Soft radiant chime | spell_radiant |
| divine_mend | Quiet crystalline tone | spell_generic |
| divine_sacred_word | Resonant spoken tone + radiant pulse | spell_radiant |
| divine_heal_wounds | CMB-009 (healing) | spell_heal |
| divine_shield_of_faith | CMB-009 variant + deflection | spell_radiant |
| divine_bless | Ascending choral tone | spell_radiant |
| divine_sanctuary | Soft bell tone | spell_generic |
| divine_detect_hollow | Low harmonic drone | spell_generic |
| divine_command | Resonant authoritative tone | spell_radiant |
| divine_turn_undead_hollow | Radiant surge + creature recoil | spell_radiant |
| divine_spiritual_weapon | Weapon SFX + radiant shimmer | spell_radiant |
| divine_dispel_corruption | Reverse Hollow audio — wrongness unwinding | spell_generic |
| divine_zone_of_truth | Subtle bell + low harmonic | spell_generic |
| divine_prayer_of_healing | Extended gentle choral tone | spell_heal |
| divine_beacon_of_hope | Warm sustained tone | spell_radiant |
| divine_mass_heal | CMB-009 (powerful, wide) | spell_heal |
| divine_divine_ward | Heavy radiant impact absorption | spell_radiant |
| divine_flame_strike | Descending fire + radiant harmonic | spell_fire |
| divine_veil_ward | Deep stabilizing harmonic | spell_generic |
| divine_revivify | Silence then heartbeat then breath | spell_generic |
| divine_commune | STG-006 (god whisper) + deity voice | spell_generic *(deity-voice asset is a separate STG- family, not a spell SFX; sound_id only covers the spell-cast beat)* |
| divine_banishment | Veil tearing (controlled) | spell_generic |
| divine_greater_restoration | Deep healing tone + radiant surge | spell_heal |
| divine_resurrection | Silence then STG-006 (Mortaen) then heartbeat | spell_generic |
| divine_holy_aura | Sustained radiant harmonic | spell_radiant |
| divine_divine_judgment | STG-006 (patron) then radiant detonation | spell_radiant |
| divine_miracle | Full STG-006 then deity audio then effect audio | spell_generic |

**Primal (29)**

| Spell id | audio_cue | `sound_id` |
|---|---|---|
| primal_thorn_whip | Whip crack + organic tearing | spell_nature |
| primal_druidcraft | Soft rustle + gentle nature whisper | spell_nature |
| primal_produce_flame | Soft ignition + crackling | spell_fire |
| primal_shillelagh | Wood resonance hum | spell_nature |
| primal_gust | Sharp wind gust | spell_nature |
| primal_healing_touch | CMB-009 variant (organic) | spell_heal |
| primal_bark_skin | Crackling organic armor | spell_nature |
| primal_entangle | Erupting vegetation | spell_nature |
| primal_speak_with_animals | Nature ambient shift | spell_nature |
| primal_goodberry | Soft organic growth chime | spell_nature |
| primal_faerie_fire | Shimmering bioluminescent hum | spell_nature |
| primal_call_lightning | Atmospheric charge then targeted strike | spell_arcane_force |
| primal_plant_growth | Deep organic growth rumble | spell_nature |
| primal_conjure_animals | Animal calls (species-appropriate) | spell_nature |
| primal_protection_from_hollow | Stabilizing hum + Hollow receding | spell_generic |
| primal_water_breathing | Water bubble + breath shift | spell_nature |
| primal_natures_grasp | Sudden root eruption | spell_nature |
| primal_wild_shape | Organic transformation | spell_nature |
| primal_wall_of_thorns | Rapid violent plant growth | spell_nature |
| primal_commune_with_nature | Deep earth resonance | spell_nature |
| primal_blight | Organic decay — drying, cracking | spell_nature |
| primal_guardian_of_nature | Organic transformation (by form) | spell_nature |
| primal_ice_storm | CMB-007 variant + hail impact | spell_ice |
| primal_earthquake | Deep seismic rumble then cracking | spell_nature |
| primal_tsunami | Building roar then crashing impact | spell_nature |
| primal_regenerate | Sustained organic healing tone | spell_heal |
| primal_animal_shapes | Cascading organic transformations | spell_nature |
| primal_feeblemind | Psychic collapse | spell_generic |
| primal_storm_of_vengeance | Building storm: wind, rain, thunder, hail, blizzard | spell_nature |

All 87 spells mapped (30 arcane + 28 divine + 29 primal). Only one spell,
`arcane_elemental_burst`, has a cast-time-variable element (fire/ice/lightning
chosen by the caster) — story-003 should decide whether the rules engine routes
its `sound_id` dynamically by the chosen element or ships it as a fixed
`spell_arcane_force` default; this doc defaults to the fixed key so the MVP
palette stays at 7 without a data-model change, and flags the dynamic-routing
option as a story-003 judgment call, not a blocker.

## 5. Regenerate Recipe

### (a) Recommended service — ElevenLabs SFX V2

Worked example: regenerating `spell_fire` from `arcane_fireball`'s audio_cue
("A bead of flame detonates — heat, light, the roar of air consumed") via
`CMB-006 (powerful)`.

```python
import os
import requests

API_KEY = os.environ["ELEVENLABS_API_KEY"]

response = requests.post(
    "https://api.elevenlabs.io/v1/sound-generation",
    headers={"xi-api-key": API_KEY},
    json={
        "text": (
            "A powerful fireball detonation: whoosh and crackle, ignition "
            "building to a brief roar, heat and the sound of air consumed. "
            "1-2 seconds, punchy game SFX, no reverb tail."
        ),
        "duration_seconds": 2,
    },
    timeout=30,
)
response.raise_for_status()
with open("apps/audio/sfx/spell_fire_01.mp3", "wb") as f:
    f.write(response.content)
```

(Endpoint path/params per ElevenLabs' current API reference at generation time —
confirm against their docs before wiring into a script, since SFX endpoints have
moved before.)

### (b) Fallback — stdlib procedural synth (no numpy/ffmpeg)

Worked example: a `spell_heal` stand-in — a warm rising tone with a gentle chime,
matching `CMB-009`'s description, built from pure sine synthesis via Python's
built-in `wave` and `math`/`struct` modules only.

```python
import math
import struct
import wave

SAMPLE_RATE = 44100


def _tone(freq_start, freq_end, duration_s, amplitude=0.4):
    n_samples = int(SAMPLE_RATE * duration_s)
    samples = []
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        # Linear frequency ramp = "rising tone"
        freq = freq_start + (freq_end - freq_start) * (i / n_samples)
        # Simple attack/decay envelope so it doesn't click at the edges
        envelope = min(1.0, i / (SAMPLE_RATE * 0.05), (n_samples - i) / (SAMPLE_RATE * 0.2))
        value = amplitude * envelope * math.sin(2 * math.pi * freq * t)
        samples.append(value)
    return samples


def _write_wav(path, samples):
    with wave.open(path, "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit PCM
        wav_file.setframerate(SAMPLE_RATE)
        frames = b"".join(struct.pack("<h", int(s * 32767)) for s in samples)
        wav_file.writeframes(frames)


# Rising tone (440Hz -> 880Hz over 1s) + a brief high chime tail
rising = _tone(440, 880, 1.0)
chime = _tone(1320, 1320, 0.4, amplitude=0.25)
_write_wav("/tmp/spell_heal_synth_example.wav", rising + chime)
```

Confirmed runnable (2026-07-05): produces a valid, playable mono 16-bit PCM
`.wav` with no third-party dependencies. Not committed — story-002 owns
generated assets.

**.mp3 vs .wav:** the mobile bundler (`apps/mobile/metro.config.js`) has no
`assetExts` override, so Metro/Expo's default asset extension list — which
already includes both `.mp3` and `.wav` — bundles either with zero config
changes. ElevenLabs SFX ships `.mp3`; the stdlib synth fallback naturally
produces `.wav`. Both drop straight into `apps/mobile/assets/sounds/` as-is.

## 6. Integration Notes for Stories 002/003

- **Source of truth:** generated assets land in `apps/audio/` (per the monorepo's
  reserved-for-future `apps/audio/` directory) as the SSOT, then get copied/bundled
  into `apps/mobile/assets/sounds/` for the client.
- **Wiring is two lines per sound:** a `require()` entry in
  `apps/mobile/src/audio/sound-registry.ts`'s `SOUNDS` map, plus one new
  `SoundName` union member. No other client code changes.
- **Cross-language `SoundName` desync (flag for story-003):** the agent's
  `apps/agent/environment_tools.py` `SoundName` Literal currently has 11 entries;
  the mobile `sound-registry.ts` `SoundName` union has 20. They are *already* out
  of sync today, independent of this milestone. No test currently catches this
  (story-003 is expected to add the cross-language guard). Story-003 should
  reconcile both lists when it adds the 7 new `spell_*` keys, not just append to
  one side.
- **`sound_id` is additive JSONB** (per the seeding note below) — adding it to
  `content/spells.json` needs no SQL migration, only a re-seed.
- **No migration needed:** seeding is JSONB-based
  (`scripts/seed_content.py` + `scripts/migrations/032_spells.sql`), so adding the
  new `sound_id` field to `content/spells.json` requires editing the JSON and
  re-seeding — no schema migration.
