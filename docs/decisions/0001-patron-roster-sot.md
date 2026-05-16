# ADR 0001 — Patron roster source of truth

Status: **Accepted** (2026-05-16) — sprint-003 story-006
Concerns: `d48e77f66c86`, `4d0c41efa770`

## Decision

**`content/gods.json` is the canonical source of truth for the 10-patron roster.**

The Python modules `apps/agent/creation_deities.py` and `apps/agent/god_whisper_data.py`
load their data from `content/gods.json` at module import time and memoize the result.
Their public dataclass APIs (`DeityData`, `GodWhisperProfile`) and module-level dicts
(`DEITIES`, `GOD_WHISPER_PROFILES`) remain unchanged, so existing consumers do not
need to change.

The Unbound Path (`id="none"`) is **not** stored in `gods.json`. It lives only in
`creation_deities.DEITIES` as a synthesized entry, because (a) gods.json seeds the
`god_agent_state` DB table and "no patron" is not an agent, and (b) the Unbound is
the absence of a divine patron, not one of them.

## Context

Sprint-002 phase-8 audit (`docs/milestones/audit/phase-8-patrons.md`) documented
three-surface fragmentation of the patron roster:

| Surface | Patrons | Shape | Authority |
| --- | --- | --- | --- |
| `apps/agent/creation_deities.py` `DEITIES` | 10 + `none` | `DeityData`: id, name, title, domain, description, card_description, synergy_classes | Character-creation flow (canonical for player-facing roster) |
| `apps/agent/god_whisper_data.py` `GOD_WHISPER_PROFILES` | 10 | `GodWhisperProfile`: deity_id, display_name, voice_character, voice_emotion, speaking_style, stinger_sound, personality_prompt | Whisper TTS rendering |
| `content/gods.json` | 4 of 10 | god_id, name, domain, personality, values, opposed_values, favor_actions, whisper_themes, temple_locations, faction_id, relationships, world_state | DB seed for `god_agent_state` (`scripts/seed_content.py`) |

The three shapes evolved independently. Future Phase 8 sprints (per
`docs/milestones/08_patrons.md`) must author Layer 1-4 mechanical data
(passive gifts, Resonance modifiers, tier abilities, archetype synergies)
and need exactly one place to write that data. `gods.json` is the natural
choice because:

1. It already seeds the DB layer where mechanical state will live.
2. Adding fields to JSON is friendlier to non-code authoring than editing dataclasses.
3. Phase 8 mechanics (favor_actions, whisper_themes) already started here for
   the 4 patrons that exist.

## Field mapping

Authoritative shape after this ADR. Fields marked **NEW** are added by this story
for the existing 4 patrons and authored from scratch for the missing 6. Layer 2-4
fields are added as `null` placeholders; future Phase 8 sprints populate them.

### Identity (Layer 1, authored by this story)

| gods.json field | Source / derivation | Consumed by |
| --- | --- | --- |
| `god_id` (string, required) | Canonical patron ID | All three surfaces |
| `name` (string, required) | "<Bare name>, <title>" — title taken from `creation_deities.DeityData.title` (player-facing authority) | gods.json itself; `GodWhisperProfile.display_name` |
| `short_name` (string, required) **NEW** | Bare name (e.g. "Veythar") — authored on every surface (gods.json, `DeityData.name`, `GodWhisperProfile.short_name`); consistency test reads it directly | All three surfaces |
| `title` (string, required) **NEW** | e.g. "the Lorekeeper" — from `creation_deities.DeityData.title` | `DeityData.title` |
| `domain` (string, required) | Domain string | `DeityData.domain` |
| `description` (string, required) **NEW** | Long audio-first personality sketch — canonical personality source | `DeityData.description` |
| `card_description` (string, required) **NEW** | One-line card text from `creation_deities.DeityData.card_description` | `DeityData.card_description` |
| `synergy_classes` (string[], required) **NEW** | Coarse Layer-4 hint, from `creation_deities.DeityData.synergy_classes` | `DeityData.synergy_classes` |

### Whisper voice profile (Layer 1 personality, authored by this story)

Nested under `whisper_profile` to keep the top level tidy. All fields **NEW** for the
roster (existing 4 patrons did not have them in gods.json).

| `whisper_profile.*` field | Source / derivation | Consumed by |
| --- | --- | --- |
| `voice_character` | `GodWhisperProfile.voice_character` (e.g. "GOD_KAELEN") | `GodWhisperProfile.voice_character` |
| `voice_emotion` | `GodWhisperProfile.voice_emotion` | `GodWhisperProfile.voice_emotion` |
| `speaking_style` | `GodWhisperProfile.speaking_style` | `GodWhisperProfile.speaking_style` |
| `stinger_sound` | `GodWhisperProfile.stinger_sound` | `GodWhisperProfile.stinger_sound` |
| `personality_prompt` | `GodWhisperProfile.personality_prompt` — embedded `<short_name>, <title>` aligned to canonical (see Note below) | `GodWhisperProfile.personality_prompt` |

Note: `god_whisper_data.GOD_WHISPER_PROFILES` previously used inconsistent titles in
its `display_name` field (e.g. "Veythar, the Unbound" vs the canonical "the Lorekeeper").
After this ADR, `display_name` is derived from `gods.json/name` so titles align
automatically. The `personality_prompt` strings have also been aligned to use the
canonical titles (Lorekeeper / Veilwatcher / Wildmother / Threshold / Tidecaller /
Dawnbringer / Fatespinner), since the whisper LLM literally pronounces the embedded
title and an audio-first project cannot ship stale name strings into the voice path.

The redundant short `personality` field (a near-paraphrase of `description` in the
4 pre-existing patrons) has been dropped from `gods.json`. `description` is the
canonical personality source and `DeityData.description` is the only consumer.

### Existing gods.json fields (preserved for the 4 patrons; required as placeholders for the new 6)

| Field | Shape | Status for new 6 patrons |
| --- | --- | --- |
| `values` | string[] | `[]` (empty placeholder — Phase 8 authors) |
| `opposed_values` | string[] | `[]` |
| `favor_actions` | `{positive: [], negative: []}` | `{"positive": [], "negative": []}` |
| `whisper_themes` | string[] | `[]` |
| `temple_locations` | string[] | `[]` |
| `faction_id` | string | `"<god_id>_faithful"` (matches existing 4-patron convention) |
| `relationships` | object<god_id, string> | `{}` |
| `world_state` | `{current_mood, active_concerns, secret_agenda}` | `{"current_mood": null, "active_concerns": [], "secret_agenda": null}` |

### Layer 2-4 placeholders (authored by future Phase 8 sprints, NOT this story)

Added as top-level `null` keys for every patron so that future authors have a stable
slot. Their absence today is intentional — sprint-003 story-006 is roster alignment,
not mechanics authoring.

| Field | Phase 8 milestone reference | This story sets |
| --- | --- | --- |
| `layer_1_gift` | M8.1 — Layer 1 passive gift (e.g. Lorekeeper's Insight) | `null` |
| `layer_2_resonance` | M8.1 — Layer 2 Resonance modifier (blocked on Phase 3) | `null` |
| `layer_3_tier_abilities` | M8.2 — Acknowledged/Devoted/Exalted ability triplet | `null` |
| `layer_4_synergy_matrix` | M8.3 — per-archetype synergy entries | `null` |

When a future sprint populates these, the shape will be designed *then* against
the implementation. This ADR explicitly does not pre-specify their internal shape
beyond "non-null when authored." That is the scope discipline the plan reviewer
flagged: defining empty shapes risks ad-hoc decisions that the implementing sprint
must immediately rework.

## Migration path

1. **`content/gods.json`** — extend to all 10 patrons. Add the **NEW** fields listed
   above to every entry. Preserve existing fields verbatim for veythar/kaelen/aelora/syrath.
   Add the 4 Layer 2-4 placeholder keys (all `null`).
2. **`apps/agent/creation_deities.py`** — at module import, load `content/gods.json`,
   build `DeityData` instances from `(short_name, title, domain, description,
   card_description, synergy_classes)`, plus the synthesized `none` entry. `DEITIES`
   dict shape is unchanged.
3. **`apps/agent/god_whisper_data.py`** — at module import, load `content/gods.json`,
   build `GodWhisperProfile` instances from the `whisper_profile` block plus the
   top-level `name` (as `display_name`). `GOD_WHISPER_PROFILES` dict shape is unchanged.
4. Both modules memoize via module-level dict construction (Python loads modules
   once per process — no additional caching needed).
5. The content path is resolved relative to the repo root via
   `Path(__file__).resolve().parents[2] / "content" / "gods.json"`.

## Consequences

**Simpler**
- One place to author patron data. Phase 8 sprints add fields to gods.json only.
- DB seed and runtime agent code see the same patron shape.
- `display_name` title divergence (Veythar/Veiled vs Veiled/Lorekeeper) auto-resolves
  because there is now one authoritative title.

**Harder**
- `creation_deities` and `god_whisper_data` are no longer pure-Python data modules —
  they read a file at import. Test fixtures that monkey-patch the dicts now need to
  do so *after* import. (Acceptable: no current test does this.)
- `content/gods.json` becomes a load-bearing file at agent startup. A malformed JSON
  crashes the agent. Mitigated by: JSON validation in CI seed step + roster
  consistency test on every run.
- File size of `gods.json` grows. Current ~4.5 KB → ~12 KB with 10 patrons and
  whisper profiles. Comfortably under any concern threshold for a data file.

**Trade-offs explicitly accepted**
- The `none` (Unbound) entry remains hand-written in `creation_deities.py`. The
  alternative — a `"is_unbound": true` row in gods.json — would mean the seeder has
  to skip a row, which is a worse trade than one synthesized constant.
- (Initially scoped as out: `personality_prompt` title alignment.) Closed in the
  reviewer-fix commit on this story: 10 personality_prompt strings now embed
  the canonical `<short_name>, <title>` from gods.json, and the regression test
  `test_personality_prompt_embeds_canonical_short_name_and_title` pins the
  invariant. The audio path can no longer pronounce stale titles.

## Out of scope (do not author in this story)

- Layer 1 gift effect text and mechanical bindings.
- Layer 2 Resonance modifiers (also blocked on Phase 3).
- Layer 3 tier ability rosters and recharge rules.
- Layer 4 archetype × patron synergy matrix.
- `favor_actions` / `whisper_themes` content for the 6 missing patrons.

All of the above are future Phase 8 work and will be authored against the slots
this ADR establishes.
