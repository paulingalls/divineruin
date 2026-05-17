# Phase 6 Audit — NPCs M6.1 (NPC Stat Block Schema & Role Archetypes)

Sprint-005 / Milestone 5 (story-001). Read-only audit of `docs/milestones/06_npcs.md` §M6.1 against `docs/game_mechanics/game_mechanics_npcs.md` §NPC Schema (L11-63) + §Role Archetype Templates (L65-378) and shipped code in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges from spec (corresponds to sprint-002/003 `aspirational` + `unverified`); **NOT_SHIPPED** = no implementation found at all.

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.1 — NPC Schema & Role Archetypes (8 acceptance items) | 1 | 1 | 6 |
| Role archetypes (12 enumerated, Merchant expanded to 7 subtypes = 18 rows) | 0 | 1 | 17 |

**Headline finding:** The narrative/social NPC layer is **shipped** — a 14-entry `content/npcs.json` rides a working schema in `packages/shared/src/entities/npc.ts:1-39`, the `npc_dispositions` table persists per-player disposition, and `apps/agent/tool_support.py:86-105` enforces disposition-gated knowledge (`disposition >= friendly`/`disposition >= trusted`) with test coverage in `apps/agent/tests/test_tools.py:19-34`. What is **NOT_SHIPPED** is the mechanical layer M6.1 adds on top: `services[]`, `price_modifier`, `mentor{}` nested object, and `role_archetype` template-link fields are all absent from `npc.ts` and `content/npcs.json`; no `role_archetypes` template store exists anywhere (no JSON file, no DB table, no Python module); no migration creates `npc_stat_blocks` or `role_archetypes` tables (migrations 001-017 inventoried — only `npcs` (generic JSONB) and `npc_dispositions` exist); no `create_npc_from_archetype(role, overrides)` function (`grep -rn 'create_npc_from_archetype\|from_archetype\|role_archetype' apps/ packages/` → 0 matches). The 14 shipped NPCs are all Tier-1 authored entries (`grep '"tier": 2'` in `content/npcs.json` → 0 matches) — no template-generated Tier-2 NPCs exist; the milestone's instantiation pipeline is unbuilt.

Naming caveat: `apps/agent/activity_templates.py:4-12` defines a 1-entry `CRAFTING_NPCS` map for `grimjaw_blacksmith` (narration personality only — `name/role/personality/speech_style/voice_id`); this is the closest thing to an archetype anywhere in the codebase and is a per-NPC narration shim, not a template instantiator. The three other spec deliverables (`create_npc_from_archetype`, `role_archetypes` template table, `npc_stat_blocks` typed table) are tracked in the Deliverables status list below.

## Coverage matrix

Every subsection of `docs/game_mechanics/game_mechanics_npcs.md` covering M6.1 (Schema + Role Archetype Templates) is mapped below. Items marked **NEW** are spec content with no corresponding milestone item. M6.2 (Settlement Templates), M6.3 (Mentor Registry), and M6.4 (Companions) are out of scope for this audit — see sibling audit files `phase-6-settlements.md`, `phase-6-mentors.md`, `phase-6-companions.md`.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Schema Extension on CreatureStatBlock (npcs.md:15-61) | M6.1 — NPC stat block schema | Spec lists 17 fields across 6 sections (Identity, Personality, Social, Schedule, Economy, Mentor, Voice). Shipped TS schema covers ~12 fields. **Missing in code:** `role_archetype`, `services[]`, `price_modifier`, `mentor{}`, `age_range` (TS has `age?: string`, spec has `age_range: str` enum). Schema-extension framing ("on top of CreatureStatBlock") is NEW vs milestone — no CreatureStatBlock type exists in `packages/shared/src/entities/` (`grep -rn 'CreatureStatBlock\|creature_stat_block' packages/shared apps/` → 0 matches). The milestone treats NPC schema as standalone; spec inherits from a creature schema that itself is unshipped (Phase 7 surface). |
| Merchant + 7 subtypes (npcs.md:75-96) | M6.1 — Merchant role archetype with 7 subtypes | Per-subtype Inventory Pool / Special Services / Typical Location matrix exists in spec. **Price modifier ranges (1.0 baseline, 0.9/0.8/1.2 by disposition; refusal at Hostile, npcs.md:84)** are NEW vs milestone (milestone says only "distinct inventory pools and price_modifier ranges"). |
| Blacksmith (npcs.md:100-117) | M6.1 — Blacksmith archetype | Combat stat block (Militia template Level 2 HP 14 AC 11) + Crafting Commission Pricing table NEW vs milestone bullet "default combat stats". |
| Innkeeper (npcs.md:121-138) | M6.1 — Innkeeper archetype | Lodging Pricing table NEW. |
| Healer/Temple Attendant (npcs.md:142-162) | M6.1 — Healer/Temple archetype | Healing Pricing table + patron-god association (npcs.md:151) NEW vs milestone bullet. Cross-doc dep with Phase 3 (gods). |
| Scholar/Sage (npcs.md:166-186) | M6.1 — Scholar archetype | Research Pricing table NEW. Hollow material buyer role NEW. |
| Quest Giver (npcs.md:190-206) | **NEW** | Explicit spec note "Not a standalone role — a function layered onto any NPC role." The milestone's 12-archetype list does NOT include Quest Giver. Quest-giving is driven by `knowledge` gating + role. Out-of-scope for M6.1 archetype shape; surface to capstone punch list. |
| Guard (npcs.md:214-234) incl. Elite Guard Tier-2 variant | M6.1 — Guard archetype | Full combat stat block + variant tier NEW vs milestone "default combat stats". |
| Soldier (Ashmark) (npcs.md:238-260) incl. Sergeant + Commander variants | M6.1 — Soldier (with Ashmark variants) archetype | Spec defines 3 variants (Soldier Tier-1, Sergeant Tier-2, Commander Tier-3). Milestone says "with Ashmark variants" — matches but underspecifies count. |
| Assassin/Rogue NPC (npcs.md:264-282) | M6.1 — Assassin/Rogue archetype | Multiattack + sneak attack + poison mechanics NEW vs milestone "default combat stats" bullet. |
| Mage NPC (npcs.md:286-314) incl. Apprentice + Archmage variants | M6.1 — Mage archetype | Focus pool + 5-spell catalog + 3 variants NEW. Cross-doc dep with Phase 3 (magic). |
| Priest NPC (npcs.md:318-344) incl. High Priest variant | M6.1 — Priest archetype | Focus pool + 5-spell catalog + 2 variants NEW. Cross-doc dep with Phase 3 (magic) and Phase 3 (gods). |
| Fence / Black Market Contact (npcs.md:352-358) | M6.1 — Fence archetype | Deception/Persuasion DC-15 gating to find a fence NEW (cross-doc with Phase 1 skill checks). |
| Stablemaster / Animal Handler (npcs.md:362-366) | M6.1 — Stablemaster archetype | Beastcaller service point reference NEW (cross-doc with companion system — Phase 6 M6.4). |
| Shipwright / Boatman (npcs.md:370-375) | **NEW** | Spec defines a 13th archetype not enumerated in the milestone's 12. Found in Sunward Coast settlements. Surface to capstone punch list. |
| Disposition System / 5-tier ladder | M6.1 — disposition base + modifier + gated knowledge | Implicit in spec via `default_disposition: str` enum (hostile/unfriendly/neutral/friendly/trusted, npcs.md:35) and per-NPC `disposition_modifiers: dict`. Spec keeps disposition mechanics in `world_data_simulation.md` (cross-doc per npcs.md:7). Gated-knowledge gates spec'd as `"disposition >= friendly"` / `"disposition >= trusted"` keys in `knowledge` dict. |

## M6.1 — NPC Stat Block Schema & Role Archetypes

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| NPC stat block schema validates all required fields including social/economic/mentor layers | `packages/shared/src/entities/npc.ts:17-39` defines `interface Npc { id; name; tier: 1\|2; role; species; gender; age?; appearance?; personality[]; speech_style; mannerisms?; backstory_summary?; knowledge; schedule; default_disposition; disposition_modifiers?; inventory_pool; secrets?; faction; voice_id; voice_notes? }`. **Missing M6.1 fields:** `npc_tier` (spec name vs TS `tier` — semantically equivalent), `role_archetype` (template link — spec npcs.md:22), `services[]` (spec npcs.md:45), `price_modifier` (spec npcs.md:46), `mentor{}` nested object (spec npcs.md:48-56), `age_range` enum (TS has free-form `age?: string`). Python side has no NPCStatBlock class (`grep -n 'class NPCStatBlock\|class NpcStatBlock' apps/agent/*.py` → 0 matches). | None for the schema interface itself; npc.ts is a types-only file. `apps/agent/tests/test_tools.py:19-34` exercises the disposition-gated subset via `filter_knowledge`. | DESIGNED |
| All 12 role archetypes defined with default combat stats, services, inventory pools, and knowledge domains | No archetype template store exists. No `content/role_archetypes.json`; no `content/archetypes/`; no `apps/agent/role_archetypes.py`; no migration creates a `role_archetypes` table (`grep -l 'role_archetypes' scripts/migrations/*.sql` → 0 matches). Only artefact: `apps/agent/activity_templates.py:4-12` defines a 1-entry `CRAFTING_NPCS` dict for `grimjaw_blacksmith` with `name/role/personality/speech_style/voice_id` — narration shim, not a template; no combat stats, no services, no inventory pool, no knowledge domains. | None | NOT_SHIPPED |
| Merchant subtypes have distinct inventory pools and price_modifier ranges | No Merchant template, no per-subtype data. `content/inventory_pools.json` exists (8202 bytes) — would receive the per-subtype pools but spec data is not seeded there. `grep -rn 'price_modifier\|merchant_subtype' apps/ packages/ content/` → 0 matches. None of the 14 NPCs in `content/npcs.json` have role `"merchant"` (`python3 -c "import json; print([e['role'] for e in json.load(open('content/npcs.json'))])"` returns blacksmith/innkeeper/scholar/companion/guild-master/elder/etc. — no merchant). | None | NOT_SHIPPED |
| Disposition supports base value, modifier list, and gated knowledge thresholds | **Base value:** `packages/shared/src/entities/npc.ts:32` `default_disposition: string`; persisted in `npc_dispositions` table (`scripts/migrations/001_initial_schema.sql` + `apps/agent/db_queries.py:22-52`). **Modifier list:** `npc.ts:33` `disposition_modifiers?: Record<string, number>`; matches spec shape `{"helped_with_task": 2, "threatened": -5}` (npcs.md:36). **Gated knowledge:** `npc.ts:7-11` `NpcKnowledge` indexer accepts arbitrary disposition gate keys; enforcement in `apps/agent/tool_support.py:86-105` `filter_knowledge()` honors `"free"`, `"disposition >= friendly"`, and `"disposition >= trusted"` gates; called from `apps/agent/query_tools.py:85` via `query_npc` agent tool. **Honesty note:** the modifier-list-on-event-application loop (deltas applied to `npc_dispositions` from gameplay events) is not traced; the schema and persistence support it, runtime application not audited here. | `apps/agent/tests/test_tools.py:19-34` covers `filter_knowledge` hostile/neutral/trusted paths. | BUILT |
| `create_npc_from_archetype` produces valid stat blocks for every archetype | No symbol. `grep -rn 'create_npc_from_archetype\|from_archetype' apps/ packages/` → 0 matches. Closest is `apps/agent/activity_templates.py:152-153` `get_crafting_npc(npc_id)` — dict-lookup against the 1-entry CRAFTING_NPCS map, not a template instantiator. | None | NOT_SHIPPED |
| Existing NPCs in `content/npcs.json` migrated to expanded schema without data loss | `content/npcs.json` contains 14 entries (708 lines). Every entry uses the legacy schema (`id/name/tier/role/species/gender/age/appearance/personality/speech_style/mannerisms/backstory_summary/knowledge/schedule/default_disposition/disposition_modifiers/inventory_pool/secrets/faction/voice_id/voice_notes`). **No entry carries the M6.1 expansion fields** (`services`, `price_modifier`, `mentor`, `role_archetype`). All entries are `tier: 1` (Authored) — no template-generated `tier: 2` NPCs (`grep '"tier": 2' content/npcs.json` → 0 matches). Roles in use: blacksmith, innkeeper, scholar, companion, guildmaster, elder, tavern keeper, temple warden, faction representatives — no merchant, guard, soldier, assassin, mage, priest, fence, stablemaster, shipwright. | None for the seed data. | NOT_SHIPPED |
| DB migration runs cleanly and schema matches entity definitions | Migrations 001-017 inventoried: `001_initial_schema.sql` creates `npcs (id TEXT PRIMARY KEY, data JSONB)` + `npc_dispositions` (per `db_queries.py:30` reference) + `npc_state` (referenced by content/npc_state.json). **No `npc_stat_blocks` table, no `role_archetypes` table** (`grep -l 'npc_stat_blocks\|role_archetypes' scripts/migrations/*.sql` → 0 matches). The generic `npcs` JSONB table accepts any shape — schema enforcement is application-side via `npc.ts` only. | None for migration validation. | NOT_SHIPPED |
| Tests cover all 12 archetypes and Merchant subtypes | No archetype tests exist. `grep -rln 'role_archetype\|merchant_subtype\|create_npc_from_archetype' apps/agent/tests apps/server/src/*.test.ts packages/shared` → 0 matches. The existing NPC tests (`apps/agent/tests/test_tools.py`, `apps/agent/tests/test_query_tools.py` etc.) exercise the shipped narrative/disposition path, not archetype instantiation. | None for archetypes specifically. | NOT_SHIPPED |

**Deliverables status (per 06_npcs.md M6.1 §Deliverables):**
- NPC stat block schema with fields including social/economic/mentor layers: **DESIGNED** (TS interface covers narrative/social/disposition+voice; missing `role_archetype`, `services[]`, `price_modifier`, `mentor{}`).
- 12 role archetype templates: **NOT_SHIPPED** (1 partial — Grimjaw blacksmith narration shim only).
- Per-archetype defaults (combat stats, services, inventory pool, knowledge domains, disposition baseline, special abilities): **NOT_SHIPPED**.
- DB migration `npc_stat_blocks` + `role_archetypes` tables: **NOT_SHIPPED**.
- Updated `content/npcs.json` with expanded schema for all existing NPCs: **NOT_SHIPPED** (14 entries on legacy schema).
- Pure function `create_npc_from_archetype(role, overrides)` returning a complete stat block: **NOT_SHIPPED**.

## Role archetype coverage

The 12 archetypes enumerated in 06_npcs.md M6.1 L16-23, with Merchant expanded to its 7 subtypes (18 rows total). Spec-only archetypes (Quest Giver, Shipwright) appear in the coverage matrix above tagged NEW and in the punch list below — not in this 18-row table.

| Archetype | Schema (packages/shared/src/entities) | Seed (content/npcs.json) | Code (apps/agent / apps/server) | Status |
| --- | --- | --- | --- | --- |
| Merchant — General Goods | No archetype type | 0 entries (no role=merchant) | None | NOT_SHIPPED |
| Merchant — Weapons & Armor | No archetype type | 0 entries | None | NOT_SHIPPED |
| Merchant — Alchemist | No archetype type | 0 entries | None | NOT_SHIPPED |
| Merchant — Jeweler | No archetype type | 0 entries | None | NOT_SHIPPED |
| Merchant — Exotic Goods | No archetype type | 0 entries | None | NOT_SHIPPED |
| Merchant — Traveling Merchant | No archetype type | 0 entries | None | NOT_SHIPPED |
| Merchant — Black Market | No archetype type | 0 entries (cf. Fence below — see punch list) | None | NOT_SHIPPED |
| Blacksmith | No archetype type | 1 entry — `grimjaw_blacksmith` (legacy schema; no archetype link) | `apps/agent/activity_templates.py:4-12` CRAFTING_NPCS narration shim (Grimjaw only — name/role/personality/speech_style/voice_id, no combat stats, no commission pricing) | DESIGNED |
| Innkeeper | No archetype type | 2 entries — `innkeeper_maren`, `tavern_keeper_bryn` (legacy schema; no archetype link, no Lodging Pricing data) | None | NOT_SHIPPED |
| Healer / Temple | No archetype type | 1 entry — `temple_warden_selene` (role: "temple row representative, divine liaison"; legacy schema; no archetype link, no Healing Pricing data, no patron-god binding) | None | NOT_SHIPPED |
| Scholar / Sage | No archetype type | 1 entry — `scholar_emris` (legacy schema; no archetype link, no Research Pricing data) | `apps/agent/activity_templates.py:22-27` TRAINING_MENTORS shim for Emris (narration only — not an archetype template) | NOT_SHIPPED |
| Guard | No archetype type | 0 entries (no role=guard) | None (combat stat block exists in spec only) | NOT_SHIPPED |
| Soldier (Ashmark) | No archetype type | 0 entries | None | NOT_SHIPPED |
| Assassin / Rogue | No archetype type | 0 entries | None | NOT_SHIPPED |
| Mage | No archetype type | 0 entries | None | NOT_SHIPPED |
| Priest | No archetype type | 0 entries (cf. `temple_warden_selene` — narrative role, not Priest stat block) | None | NOT_SHIPPED |
| Fence / Black Market Contact | No archetype type | 0 entries | None | NOT_SHIPPED |
| Stablemaster / Animal Handler | No archetype type | 0 entries | None | NOT_SHIPPED |

## Material gaps

Content / data gaps that block M6.1 from leaving DESIGNED/NOT_SHIPPED state:

1. **`content/role_archetypes.json`** — does not exist. Spec defines 12 (plus 2 NEW — Quest Giver function-overlay and Shipwright role) archetypes with per-archetype combat stats, services, inventory pool, knowledge domains, disposition baseline, and per-subtype Merchant data. None seeded.
2. **`role_archetypes` DB table** — no migration creates it. Migrations inventory (`ls scripts/migrations/`): `001_initial_schema`, `002_add_indexes`, `003_player_map_progress`, `004_auth_tables`, `005_async_activities`, `006_world_news`, `007_push_tokens`, `008_add_foreign_keys`, `009_god_whispers`, `010_generated_assets`, `011_auth_code_attempts`, `012_story_moments`, `013_scenes_table`, `014_skill_advancement`, `015_progression_table`, `016_training_activities`, `017_training_content`. None reference archetypes.
3. **`npc_stat_blocks` DB table** — no migration creates it (same 17-file inventory above). Generic `npcs (id, data JSONB)` table from migration 001 is the only NPC store; CreatureStatBlock base type referenced by spec (npcs.md:18) is also unshipped (Phase 7 surface).
4. **`content/npcs.json` schema-expansion** — 14 legacy entries need `services`, `price_modifier`, `mentor`, `role_archetype` fields backfilled (some may be `null`/`None` for non-economic NPCs). No Tier-2 entries.
5. **Combat stat blocks for Guard / Soldier / Assassin / Mage / Priest / Blacksmith (Militia) / Innkeeper bouncer (Guard)** — all reference combat data that lives in a CreatureStatBlock shape (`game_mechanics_bestiary.md`, Phase 7). M6.1 archetype templates cannot land complete combat-stat coverage until Phase 7's creature schema lands.
6. **Pricing tables** (Lodging, Healing, Research, Commission) — embedded in spec, not seeded as queryable data. Either become per-archetype `services[]` entries or live as a separate `pricing_tables.json`; design unspecified.

## Cross-doc deps

- **M6.1 → Phase 7 Bestiary (creature schema).** Spec `class NPCStatBlock(CreatureStatBlock)` (npcs.md:18) inherits from a creature schema that is unshipped. Combat stat blocks for Guard/Soldier/Assassin/Mage/Priest/etc. cannot validate against a base type that doesn't exist. The M6.1 schema deliverable will either (a) wait on Phase 7's CreatureStatBlock, (b) inline combat fields directly, or (c) ship a placeholder base interface. Decision needed in M6.1 implementation.
- **M6.1 → Phase 3 Magic.** Mage and Priest archetype templates carry Focus pool + spell catalog references (npcs.md:300-307, 332-339). The spell catalog is a Phase 3 surface; archetype templates would reference spell IDs from there.
- **M6.1 → Phase 3 Gods.** Healer/Temple archetype binds to a patron god (npcs.md:151). Patron data is in `content/gods.json` already; archetype templates would carry a `patron_god?: string` reference.
- **M6.1 → M6.2 Settlement Templates.** Settlement Workspace Availability matrix referenced in `game_mechanics_crafting.md:230-242` (Hamlet/Village/Town/City/Keldaran Hold) routes through NPC archetype + settlement-tier instantiation. M6.2 consumes M6.1's archetype templates to populate settlements; M6.1 must land first.
- **M6.1 → M6.3 Mentor Registry.** `mentor{}` nested field in the NPC schema (npcs.md:48-56) is consumed by M6.3's mentor registry. M6.1 ships the schema slot; M6.3 ships the registry + check/enroll surfaces. Two existing `TRAINING_MENTORS` entries at `apps/agent/activity_templates.py:16-27` (`guildmaster_torin`, `scholar_emris`) carry the narration data but not the structured mentor requirements/variant data the schema slot expects.
- **M6.1 → Phase 9 Economy.** `price_modifier` field per NPC (npcs.md:46) and Merchant subtype price ranges (npcs.md:84, npcs.md:88-96) feed Phase 9's faction-rep pricing engine. Cross-doc with the Phase 9 economy rewrite (planned milestone 6 in execution_plan.json).

## Out-of-scope findings (Sprint-spec-cleanup punch list)

- **Quest Giver archetype** (gm_npcs L190-206) is in the spec but NOT in 06_npcs.md M6.1's 12-archetype list. Spec explicitly notes "Not a standalone role — a function layered onto any NPC role." Either the milestone should explicitly call out Quest Giver as a function-overlay (not a 13th archetype) or treat it as a `quest_giver?: bool` flag on the base schema. Capstone should record for customer resolution.
- **Shipwright archetype** (gm_npcs L370-375) is in the spec but NOT in 06_npcs.md M6.1's 12-archetype list. The milestone undercounts by 1. Either add Shipwright to M6.1 deliverables or document the deferral. Capstone should record for customer resolution.
- **CreatureStatBlock base type** (gm_npcs L18 `class NPCStatBlock(CreatureStatBlock):`) is referenced as the inheritance root but has no shipped definition. The milestone treats NPC schema as standalone; spec treats it as an extension. Resolve in M6.1 implementation (inline vs depend on Phase 7).
- **`tier: 1 | 2` field in TS** matches semantic `npc_tier` from spec but uses different field name. M6.1 schema work should pick one (`tier` is simpler; `npc_tier` matches spec verbatim). Capstone should record the naming choice.
- **`age?: string` in TS** vs spec `age_range: str` enum (`"young" | "middle" | "elder"`). TS shipped a free-form field; spec wants a constrained enum. Capstone should record for schema-tightening when M6.1 lands.
- **`temple_warden_selene` role** in `content/npcs.json` is `"temple row representative, divine liaison"` — narrative description, not a structured archetype role. Once M6.1 ships, existing NPCs should bind to archetype IDs (`role_archetype: "healer_temple"`) and keep narrative role strings as `role` (display field).
- **`grimjaw_blacksmith`** entry exists in BOTH `content/npcs.json` (full NPC) AND `apps/agent/activity_templates.py:5-11` CRAFTING_NPCS (narration shim). When M6.1 ships, the narration shim should derive its data from the NPC record + archetype template, not duplicate it. Append to audit/README Sprint-spec-cleanup punch-list.
- **`apps/agent/activity_templates.py` TRAINING_MENTORS and CRAFTING_NPCS dicts** carry archetype-like narration metadata (`personality`, `speech_style`, `voice_id`) but at the NPC level, not the archetype level. M6.3 mentor-registry work will overlap — coordinate the consolidation when both M6.1 and M6.3 land.

**Hand-off:** every bullet above is consumed by story-005 (sprint-005 capstone), which adds the Sprint-005 section + Sprint-spec-cleanup punch list to `docs/milestones/audit/README.md` per sprint.json's story-005 `file_domain`. This audit file is the source-of-truth for capstone consolidation.

## Verification reproducibility

The NOT_SHIPPED claims above rest on negative-grep evidence. Re-run these from the repo root to verify the audit didn't go stale (run as of commit b33a50d / migrations 001-017):

```bash
# 1. No archetype instantiator anywhere
grep -rn 'create_npc_from_archetype\|from_archetype\|role_archetype' apps/ packages/

# 2. No archetype tables in migrations
grep -l 'npc_stat_blocks\|role_archetypes' scripts/migrations/*.sql

# 3. Schema-expansion fields absent from TS interface
grep -nE '\b(services|price_modifier|mentor|role_archetype)\b' packages/shared/src/entities/npc.ts

# 4. No Tier-2 (template-generated) NPCs in seed data
grep '"tier": 2' content/npcs.json

# 5. No Merchant role in any seeded NPC
python3 -c "import json; print([e['role'] for e in json.load(open('content/npcs.json')) if 'merchant' in e['role'].lower()])"

# 6. No Python NPCStatBlock class
grep -n 'class NPCStatBlock\|class NpcStatBlock' apps/agent/*.py
```

Each command exits with empty / 0-result output as of this audit. A non-empty result means a downstream story (or the M6.1 implementation) has landed code that this audit's NOT_SHIPPED verdicts should be re-evaluated against.
