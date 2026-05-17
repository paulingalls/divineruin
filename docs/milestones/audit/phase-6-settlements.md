# Phase 6 Audit — NPCs M6.2 (Settlement Templates & NPC Population)

Sprint-005 / Milestone 5 (story-002). Read-only audit of `docs/milestones/06_npcs.md` §M6.2 (L42-74) against `docs/game_mechanics/game_mechanics_npcs.md` §Settlement Templates (L544-595) + §Encounter Design: Hostile NPC Groups (L597-628) and shipped code in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges from spec; **NOT_SHIPPED** = no implementation found at all. Sibling sprint-005 audit file: `docs/milestones/audit/phase-6-schema-archetypes.md` (story-001, M6.1).

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.2 — Settlement Templates & NPC Population (8 acceptance items) | 0 | 0 | 8 |
| Settlement tiers (Hamlet/Village/Town/City/Capital — 5 rows) | 0 | 0 | 5 |
| Personality traits (8 rows) | 0 | 0 | 8 |
| Generation surfaces (3 functions/tool) | 0 | 0 | 3 |
| Hostile encounter templates (4 rows) | 0 | 0 | 4 |

**Headline finding:** M6.2 is **entirely unshipped**. No settlement-tier ladder (Hamlet/Village/Town/City/Capital) exists in code or content — the only "tier" on locations is the entity-tier 1|2 (authored vs template) at `packages/shared/src/entities/location.ts:28`, orthogonal to settlement size. No personality-trait enum exists (the 8 spec traits Prosperous/Struggling/Military/Scholarly/Corrupt/Devout/Frontier/Refuge are not constants, not enum members, not seed data). The three deliverable surfaces — `generate_settlement_npcs`, `instantiate_npc_from_template`, `get_settlement_npc_population` — return 0 hits across `apps/agent` and `apps/server`. No `settlement_templates` migration. The `apps/agent/city_agent.py:1` docstring promises "settlement/city gameplay", but its CITY_TOOLS list (L18-45) carries no population/template tool — only individual-NPC `query_npc` (`apps/agent/query_tools.py:62`). The 4 spec hostile-encounter templates (Bandit Ambush, Ashmark Patrol, Cult Cell, Hollow-Corrupted Settlement) are NOT in `content/encounter_templates.json` (6 shipped entries are all Hollow-themed: shadeling_cluster, ruins_mawling_pair, hollowed_scout, hollow_wisp, hollow_patrol_greyvale, ruins_guardian). The encounter-storage table itself ships (`encounter_templates` in `scripts/migrations/001_initial_schema.sql`) but does not satisfy any of the 4 spec templates — storage-ready, content-empty.

Naming caveat: `apps/agent/region_types.py:1-9` defines `REGION_CITY="city" | REGION_WILDERNESS="wilderness" | REGION_DUNGEON="dungeon"` — a 3-value **region-type** enum used by `apps/agent/city_agent.py` to scope tools. Easy to misread as partial settlement-tier coverage; it is not. The spec's 5-tier settlement ladder is a separate axis (size: Hamlet→Capital) from region type (city / wilderness / dungeon). `content/locations.json` (18 entries) uses `region_type` ∈ {city, wilderness, dungeon} and has no `settlement_tier` key.

## Coverage matrix

Every subsection of gm_npcs covering M6.2 (Settlement Templates + Hostile Encounter Design) is mapped below. Items marked **NEW** are spec content with no corresponding M6.2 acceptance bullet.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Settlement Sizes table (npcs.md:548-556) | M6.2 — 5 settlement tiers | Hamlet 10-50 / Village 50-300 / Town 300-3,000 / City 3,000-30,000 / Capital 30,000+. Spec notes "Capital: None currently exist — the Sundering destroyed the great cities" — the 5th tier is intentionally empty in current-world content. Milestone bullet "5+ innkeepers ... full role coverage with named authored NPCs" for Capital may be aspirational against a tier with zero in-world settlements. **Flag for capstone.** |
| Role Distribution by Settlement Size (npcs.md:560-578) | M6.2 — role distributions per tier | Spec lists 17 role-count rows × 4 columns (Hamlet/Village/Town/City — no Capital column in role table; missing despite Capital being a defined tier). **Spec/milestone divergence:** milestone L52 says Hamlet has "1 innkeeper, 1 merchant, 1 healer (partial)"; spec L562-578 says Hamlet has 0-1 innkeeper, 0 general merchant, 0 healer (herbalist only). Milestone overcounts Hamlet. **Flag for capstone.** Mentor NPCs row (npcs.md:578) is NEW vs milestone — overlaps M6.3 territory; recorded here as cross-milestone reference. |
| Settlement Personality table (npcs.md:580-594) | M6.2 — 8 personality traits | Maps 1:1 to milestone deliverable bullet for 8 traits. Per-trait Effect-on-NPCs prose covers disposition baseline AND inventory pool changes — matches milestone bullet 2 wording. |
| Bandit Ambush (npcs.md:601-606) | M6.2 — hostile encounter templates | Composition (3-5 Bandits + 1 Bandit Captain), tactics, morale, loot all spec'd. NEW vs milestone acceptance — milestone §Deliverables lists "Hostile encounter templates using companions: Bandit Ambush, Ashmark Patrol, Cult Cell, Hollow-Corrupted Settlement" but the 8 acceptance bullets do NOT mention them. Cross-milestone overlap with M6.4 §Companions (which lists the same 4 encounters as companion-using). **Coordinate hand-off with story-004 capstone.** |
| Ashmark Patrol (npcs.md:608-613) | M6.2 — hostile encounter templates | Allied/hostile-by-Thornwatch-rep flip is NEW vs milestone — reputation-aware encounter behavior is not in the M6.2 acceptance list. Cross-doc dep with faction system (`content/factions.json`). |
| Cult Cell (npcs.md:615-620) | M6.2 — hostile encounter templates | References Priest, Bandit, Mage, High Priest creature/NPC stat blocks — depends on M6.1 archetype stat blocks AND Phase 7 Bestiary. |
| Hollow-Corrupted Settlement (npcs.md:622-626) | M6.2 — hostile encounter templates | "Former NPCs may be recognizable as Hollowed. Fragment Voice triggers for any the player knew." NEW — narrative trigger tied to player-NPC history, not spec'd as a generic encounter mechanic. Cross-doc dep with Phase 7 (Hollowed creatures) and player history tracking. |

## M6.2 — Settlement Templates & NPC Population

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| All 5 settlement tiers defined with correct NPC role distributions | No `settlement_tier` field on `packages/shared/src/entities/location.ts:25-41` Location interface (existing `tier: 1 \| 2` at L28 is the entity authored/template flag, not Hamlet/Village/Town/City/Capital). No `Hamlet`/`Village`/`Town`/`City`/`Capital` constants anywhere (`grep -nE 'Hamlet\|Village\|Town\|Capital' apps/agent/*.py packages/shared/src/entities/*.ts content/locations.json` returns only flavor strings in `apps/server/src/image-prompt-templates.ts:78-82` `location_town` image-prompt template, plus `apps/server/src/debug.ts:255` "farming village" prose). `content/locations.json` (18 entries) has no `settlement_tier` or `settlement_size` key. | None | NOT_SHIPPED |
| All 8 personality traits modify NPC disposition baselines and inventory pools | No `personality` field on the Location interface. None of the 18 `content/locations.json` entries carry a personality trait. `grep -nE '\bProsperous\|Struggling\|Scholarly\|Devout\|Frontier\|Refuge\b' apps/ packages/ content/` returns 0 spec-aligned matches (false positives from `Corrupted`/`Corruption` Hollow-state vocabulary in unrelated files). No modifier-application function ties personality to either NPC `disposition_modifiers` (`packages/shared/src/entities/npc.ts:33`) or NPC `inventory_pool` (`npc.ts:34`). | None | NOT_SHIPPED |
| `generate_settlement_npcs` produces correct role counts for every tier | No symbol. `grep -rn 'generate_settlement_npcs' apps/ packages/` → 0 matches. No rules-engine function in `apps/agent/rules_engine.py`. `apps/agent/query_tools.py:62-91` `query_npc` queries a single NPC by id; no population/batch query. | None | NOT_SHIPPED |
| `instantiate_npc_from_template` applies settlement tier and personality modifiers to archetype defaults | No symbol. `grep -rn 'instantiate_npc_from_template\|from_template' apps/ packages/` → 0 matches. Chains story-001's finding that `create_npc_from_archetype` (M6.1 deliverable) is also NOT_SHIPPED. | None | NOT_SHIPPED |
| Generated NPCs have unique names, varied personalities within archetype constraints | No NPC generator exists (rows 3 + 4 above). The 14 NPCs in `content/npcs.json` are all hand-authored Tier-1 entries; no Tier-2 template-generated entries (`grep '"tier": 2' content/npcs.json` → 0 matches). No name-generation utility (`grep -rn 'generate_npc_name\|random_name' apps/agent apps/server` → 0 matches). | None | NOT_SHIPPED |
| Agent tool `get_settlement_npc_population` returns valid NPC list for any location | Not registered. `apps/agent/city_agent.py:18-45` CITY_TOOLS list enumerates 23 tools — none are `get_settlement_npc_population`. `grep -rn '@function_tool' apps/agent | grep -i 'settlement\|population'` → 0 matches. The closest is `query_location` (registered at `city_agent.py:30`, defined in `apps/agent/query_tools.py`) which returns a single location entity, not its NPC population. | None | NOT_SHIPPED |
| Settlement personality "Corrupt" increases Fence/Black Market frequency and reduces Guard disposition | No Corrupt-trait-aware code (row 2 above). No Fence archetype shipped (story-001 archetype coverage: NOT_SHIPPED). No personality-aware disposition modifier function. The `apps/agent/db_queries.py:25-30` `get_npc_disposition` resolves per-player disposition only; no settlement-level personality input. | None | NOT_SHIPPED |
| Tests cover all tier/personality combinations | No M6.2 surface exists to test. `grep -rln 'settlement_tier\|generate_settlement\|instantiate_npc_from_template' apps/agent/tests apps/server/src/*.test.ts packages/shared` → 0 matches. | None | NOT_SHIPPED |

**Deliverables status (per 06_npcs.md M6.2 §Deliverables L48-59):**
- 5 settlement tiers (Hamlet/Village/Town/City/Capital) with NPC role distributions: **NOT_SHIPPED**.
- 8 settlement personality traits modifying disposition baselines + inventory pools: **NOT_SHIPPED**.
- DB migration `settlement_templates` table (tier, personality, role_distribution): **NOT_SHIPPED**.
- Rules engine `generate_settlement_npcs(location_tier, personality)`: **NOT_SHIPPED**.
- Template-based generation `instantiate_npc_from_template(role, settlement_tier, personality)`: **NOT_SHIPPED**.
- Agent tool `get_settlement_npc_population`: **NOT_SHIPPED**.

## Settlement tier coverage

The 5 tiers enumerated in gm_npcs L552-556 (Hamlet/Village/Town/City/Capital):

| Tier | Spec role distribution (population) | Code or content trace | Status |
| --- | --- | --- | --- |
| Hamlet (10-50 pop) | 0-1 innkeeper, 0 general merchant, 0 blacksmith, 0 healer (herbalist), 0 guards (militia only), 0 stablemaster (npcs.md:562-578) | None. Closest: `content/locations.json` has no Hamlet-sized location seeded. Milestone L52 says "1 innkeeper, 1 merchant, 1 healer (partial)" — **diverges from spec** (spec is more austere). | NOT_SHIPPED |
| Village (50-300 pop) | 1 innkeeper, 1 general merchant, 0-1 traveling weapons merchant, 1 blacksmith, 1 healer (shrine), 2-4 militia guards (npcs.md:562-578) | None. `content/locations.json` includes `millhaven` (one of the 18 location entries) tagged `region: "greyvale"` / `region_type: "city"` (NOT settlement-typed). No role-count metadata. Spec explicitly names Millhaven as a village (L553). | NOT_SHIPPED |
| Town (300-3,000 pop) | 1-2 innkeepers, 2-3 general merchants, 1-2 blacksmiths, 1-2 healers (temple), 0-1 scholar, 6-12 guards + captain, optional Ashmark garrison 10-30 (npcs.md:562-578) | None seeded. No tier-tagged town in content. | NOT_SHIPPED |
| City (3,000-30,000 pop) | 3-5 innkeepers, 5-10 general merchants, 2-4 weapons merchants, 1-3 alchemists, 1-2 jewelers, 1-3 exotic goods, 1-2 hidden black market, 3-6 blacksmiths, 3-6 healers (major temple, high priest), 2-5 scholars, 30-60 guards + elite + commander, 50+ Ashmark soldiers (if garrison), 1-2 fences, 3-6 faction reps (npcs.md:562-578) | None. Spec gives Accord of Tides and Keldaran holds as examples (L555); neither is in `content/locations.json`. The 18 location entries are scoped to Greyvale + Sunward Coast regions only. | NOT_SHIPPED |
| Capital (30,000+ pop) | Spec note: "None currently exist — the Sundering destroyed the great cities" (L556). Milestone L54-55 says "full role coverage with named authored NPCs supplementing templates" — aspirational against a tier with 0 in-world examples. | None. No Capital location can exist by spec design; the tier is reserved for post-Sundering recovery content. | NOT_SHIPPED |

## Personality trait coverage

The 8 traits enumerated in gm_npcs L584-593:

| Trait | Spec effect on NPCs | Code or content trace | Status |
| --- | --- | --- | --- |
| Prosperous | Fuller inventories, higher prices. NPCs confident/well-fed. (npcs.md:586) | None. No `Prosperous` constant; no inventory-pool-by-trait logic. | NOT_SHIPPED |
| Struggling | Thin inventories, desperate NPCs. More quest hooks. (npcs.md:587) | None. | NOT_SHIPPED |
| Military | Guards everywhere, martial mentors available, suspicious of strangers. (npcs.md:588) | None. Cross-doc with M6.3 mentor registry; Ashmark Garrison concept lives in faction data but no settlement-trait binding. | NOT_SHIPPED |
| Scholarly | Scholar NPCs, library/archive access, cheap identification services. (npcs.md:589) | None. `scholar_emris` exists in `content/npcs.json` but is not bound to a settlement Scholarly trait. | NOT_SHIPPED |
| Corrupt | Black market easily found, guards bribable, faction tensions high. (npcs.md:590) | None. Acceptance bullet 7 explicitly calls out Corrupt → Fence frequency + Guard disposition; no mechanism exists. | NOT_SHIPPED |
| Devout | Temple is largest building, cheap healer services, divine knowledge rich. (npcs.md:591) | None. `content/gods.json` exists (M6.1 audit reference); no settlement→deity binding. | NOT_SHIPPED |
| Frontier | Minimal services, self-reliant NPCs, Hollow-related knowledge free. (npcs.md:592) | None. Greyvale-region locations (`content/locations.json`) are thematically frontier-ish but not trait-tagged. | NOT_SHIPPED |
| Refuge | Diverse population, cautious NPCs, high protection demand. (npcs.md:593) | None. | NOT_SHIPPED |

## Generation surfaces

| Surface | Expected signature | Evidence | Status |
| --- | --- | --- | --- |
| `generate_settlement_npcs` | `(location_tier: str, personality: str) -> list[NPCStatBlock]` (rules-engine pure function per milestone L56) | `grep -rn 'generate_settlement_npcs' apps/ packages/` → 0 matches. Not in `apps/agent/rules_engine.py`. | NOT_SHIPPED |
| `instantiate_npc_from_template` | `(role: str, settlement_tier: str, personality: str) -> NPCStatBlock` (template instantiator per milestone L57) | `grep -rn 'instantiate_npc_from_template\|from_template' apps/ packages/` → 0 matches. Chains M6.1's missing `create_npc_from_archetype`. | NOT_SHIPPED |
| `get_settlement_npc_population` (agent tool) | `@function_tool` returning NPC list for a location_id (milestone L58) | Not in `apps/agent/city_agent.py:18-45` CITY_TOOLS. `grep -rn 'get_settlement_npc_population\|settlement_population' apps/agent` → 0 matches. | NOT_SHIPPED |

## Hostile encounter templates

The 4 templates enumerated in 06_npcs.md M6.2 §Deliverables (under "Hostile encounter templates"):

| Encounter | Tier | Spec section | Content/Code trace | Status |
| --- | --- | --- | --- | --- |
| Bandit Ambush | Tier 1-2 | npcs.md:601-606 | Not in `content/encounter_templates.json` (6 shipped: shadeling_cluster, ruins_mawling_pair, hollowed_scout, hollow_wisp, hollow_patrol_greyvale, ruins_guardian — all Hollow-themed). `encounter_templates` table exists in `scripts/migrations/001_initial_schema.sql` — storage shipped, content not seeded. Bandit + Bandit Captain stat blocks: NOT_SHIPPED (cross-doc with Phase 7). | NOT_SHIPPED |
| Ashmark Patrol | Tier 2 (allied/hostile by rep) | npcs.md:608-613 | Not in `content/encounter_templates.json`. `hollow_patrol_greyvale` is name-adjacent (Ashmark = the Hollow-fighting military faction) but its theme/composition is Hollow Patrol (Hollow creatures), not Ashmark Patrol (4 Soldiers + 1 Sergeant). Reputation-aware allied/hostile flip is NEW vs milestone — no faction-rep gating in encounter selection (`grep -rn 'thornwatch_rep\|faction_rep' apps/agent` → only narrative usage in NPC knowledge gates). | NOT_SHIPPED |
| Cult Cell | Tier 2-3 | npcs.md:615-620 | Not in `content/encounter_templates.json`. Cult Fanatic / Cultist / Cult Leader stat blocks: NOT_SHIPPED (depends on Priest/Bandit/Mage archetype stat blocks, M6.1 NOT_SHIPPED). | NOT_SHIPPED |
| Hollow-Corrupted Settlement | Tier 2-3 | npcs.md:622-626 | Not in `content/encounter_templates.json`. Closest: `hollow_patrol_greyvale` + `ruins_mawling_pair` + `shadeling_cluster` are individual Hollow encounters but not the cohesive "former village" template (1 Hollowed Knight + 2-4 Mawlings + 6-10 Shadelings). Fragment-Voice-on-known-NPC narrative trigger: NOT_SHIPPED. | NOT_SHIPPED |

**Encounter storage infrastructure note** (does not count toward the 4 spec templates): the `encounter_templates` JSONB table ships in `scripts/migrations/001_initial_schema.sql` and the content layer has 6 entries — they're just all Hollow-themed, not the 4 M6.2 spec templates. Storage is ready; spec content for these 4 is NOT_SHIPPED.

## Material gaps

Content / data gaps that block M6.2 from leaving NOT_SHIPPED state:

1. **`content/settlement_templates.json`** (or migration-seeded `settlement_templates` table) — does not exist. Spec defines 4 active tiers × ~17 roles = ~68 role-count cells (Capital tier has no role table). Plus 8 personality traits × per-trait modifier deltas.
2. **`settlement_templates` DB table** — no migration creates it. Locations live as generic JSONB in the `locations` table (migration 001).
3. **`settlement_tier` field on Location** — neither in the TS interface (`location.ts`) nor in any of the 18 `content/locations.json` entries. Adding this is a schema-expansion task chained with content backfill (Millhaven → village, etc.).
4. **`personality` field on Location** — same as above; not in interface, not in content.
5. **Three M6.2 surfaces** (`generate_settlement_npcs`, `instantiate_npc_from_template`, `get_settlement_npc_population`) — all 0-hit greps.
6. **4 hostile encounter templates** — none of Bandit Ambush / Ashmark Patrol / Cult Cell / Hollow-Corrupted Settlement is in `content/encounter_templates.json`. The 6 shipped templates are all Hollow-themed Greyvale encounters; the 4 spec templates would expand the catalog to humanoid-faction encounters.
7. **Stat blocks for encounter composition** — Bandit, Bandit Captain, Cult Fanatic, Cultist, Cult Leader, Hollowed Knight references in spec all rely on creature/NPC stat block templates that are M6.1-dependent and Phase 7 (Bestiary) dependent.
8. **Faction-rep encounter gating** (Ashmark Patrol allied/hostile by Thornwatch standing) — no encounter selector consults faction reputation today.

## Cross-doc deps

- **M6.2 → M6.1 (NPC archetype templates).** The `instantiate_npc_from_template` function requires `create_npc_from_archetype` from M6.1 (story-001 audit: NOT_SHIPPED). M6.1 must land before M6.2's NPC-generation surfaces can take shape.
- **M6.2 → Phase 7 Bestiary.** All 4 hostile encounter templates reference stat-block-shaped creatures (Bandit, Cult Fanatic, Hollowed Knight, Shadeling, Mawling). Phase 7 (`game_mechanics_bestiary.md`) ships the CreatureStatBlock base type that NPC stat blocks inherit from (per story-001 finding); encounter compositions depend on Phase 7.
- **M6.2 → Phase 9 Economy.** Merchant inventory-by-tier (Hamlet 0 merchants → City 5-10) and price modifiers by personality (Prosperous → higher prices; Struggling → thin inventories) feed Phase 9's `merchant_inventory_restock` and `supply_demand_engine` subsystem docs. Cross-doc with planned milestone 6 (Economy rewrite) in execution_plan.json.
- **M6.2 → M6.3 Mentor Registry.** Settlement size determines mentor availability (Hamlet 0 mentors → City 3-6 mentors per spec L578). M6.3's mentor registry consumes the settlement-tier ladder M6.2 defines.
- **M6.2 → M6.4 Companions.** All 4 hostile encounter templates are explicitly listed in 06_npcs.md M6.4 §Deliverables L130 as "Hostile encounter templates using companions". This audit covers them under M6.2 (where the §Deliverables list also enumerates them); story-004 may re-audit from the companion-integration angle. **Capstone must reconcile to avoid double-counting.**
- **M6.2 → faction system.** Ashmark Patrol's allied/hostile flip depends on Thornwatch reputation; `content/factions.json` exists but no encounter-selector consults reputation today.
- **M6.2 → existing location data.** `content/locations.json` (18 entries) currently uses `region_type` ∈ {city, wilderness, dungeon} (`apps/agent/region_types.py:5-9`). This is orthogonal to settlement_tier — a `city` region_type can be a Village or a City in settlement terms. M6.2 needs to add settlement_tier as a parallel axis; do not collapse them.

## Out-of-scope findings (Sprint-spec-cleanup punch list)

- **Capital tier with zero in-world examples.** Spec L556 explicitly states no Capital currently exists; milestone L54-55 names "Capital: full role coverage with named authored NPCs supplementing templates" as a deliverable. Capstone should record: either Capital is post-launch content (acceptable aspirational tier) or the milestone should drop Capital from M6.2's "5 tiers" until lore evolves.
- **Hamlet role-count divergence.** Milestone L52 says "Hamlet: 1 innkeeper, 1 merchant, 1 healer (partial)"; spec L562-578 says Hamlet has 0-1 innkeeper, 0 merchants, 0 healers (herbalist at best). Capstone should record for customer resolution.
- **`region_type` vs `settlement_tier` orthogonality.** `content/locations.json` already has a `region_type` field (city/wilderness/dungeon, used by `apps/agent/city_agent.py` for agent-tool scoping). M6.2 introduces `settlement_tier` (size: Hamlet→Capital) as a parallel axis. These are NOT the same thing; capstone should record so M6.2 implementation doesn't accidentally collapse them.
- **Mentor row in settlement role-distribution table** (npcs.md:578). The "Mentor NPCs" row crosses into M6.3 territory (Mentor Registry & Training). Capstone should record that M6.3 reads M6.2's settlement-tier ladder for mentor-availability gating.
- **Reputation-aware encounter selection.** Ashmark Patrol's allied/hostile flip by Thornwatch standing (npcs.md:613) is a NEW mechanic the milestone doesn't enumerate. Either lift to a separate deliverable or document the deferral.
- **`hollow_patrol_greyvale` name collision.** Shipped encounter at `content/encounter_templates.json` is name-adjacent to spec's Ashmark Patrol but semantically a Hollow Patrol (Hollow creatures, not Ashmark soldiers). M6.2 implementation should add Ashmark Patrol as a new template and either rename or coexist with the existing Hollow Patrol entry.
- **Fragment Voice trigger** (npcs.md:626) — Hollow-Corrupted Settlement's narrative trigger that fires when the player encounters a former-NPC-now-Hollowed. This depends on per-NPC player-history tracking that may not yet exist; capstone should record as a cross-doc dep with Hollow Voice mechanics (Phase 8 territory, not yet in milestones).
- **Settlement role-distribution table has no Capital column** (npcs.md:560). The Capital tier is defined in Settlement Sizes but absent from Role Distribution by Settlement Size. Capstone should record so M6.2 implementation knows to leave Capital tier role counts deferred.

**Hand-off:** every bullet above is consumed by story-005 (sprint-005 capstone), which adds the Sprint-005 section + Sprint-spec-cleanup punch list to `docs/milestones/audit/README.md` per sprint.json's story-005 `file_domain`. This audit file is the source-of-truth for capstone consolidation of M6.2 findings.

## Verification reproducibility

The NOT_SHIPPED claims above rest on negative-grep evidence. Re-run these from the repo root to verify the audit didn't go stale (run as of commit 2388ae3 / migrations 001-017):

```bash
# 1. No settlement-tier or settlement-size field anywhere
grep -nE '\bsettlement_tier\b|\bsettlement_size\b' packages/shared/src/entities/location.ts content/locations.json apps/agent/*.py apps/server/src/*.ts

# 2. No personality field on Location, no spec personality constants
grep -nE '\bProsperous\b|\bStruggling\b|\bScholarly\b|\bDevout\b|\bFrontier\b|\bRefuge\b' apps/ packages/ content/

# 3. No M6.2 generation surfaces
grep -rn 'generate_settlement_npcs\|instantiate_npc_from_template\|get_settlement_npc_population\|from_template' apps/ packages/

# 4. No settlement_templates table
grep -l 'settlement_templates' scripts/migrations/*.sql

# 5. Settlement-tier-named constants are absent (image-prompt + debug-page false positives expected)
grep -nE '\bHamlet\b|\bVillage\b|\bCapital\b' apps/agent/*.py packages/shared/src/entities/*.ts

# 6. 4 spec hostile encounter templates absent from content
python3 -c "import json; ids=[e['id'] for e in json.load(open('content/encounter_templates.json'))]; want=['bandit_ambush','ashmark_patrol','cult_cell','hollow_corrupted_settlement']; print('shipped:', ids); print('want_present:', [w for w in want if w in ids])"
```

Each command exits with empty / 0-match output (or `want_present: []` for #6) as of this audit. A non-empty result means a downstream story or M6.2 implementation has landed code that this audit's NOT_SHIPPED verdicts should be re-evaluated against.
