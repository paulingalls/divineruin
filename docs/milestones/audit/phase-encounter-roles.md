# encounter_roles Integration Audit (Sprint-003)

> Source: `docs/game_mechanics/game_mechanics_encounter_roles.md` (790L). Primary owner: **Phase 04 Combat**. Cross-refs: **Phase 07 Bestiary** (creature roles, Worked Examples) and **Phase 09 Economy** (currency drops, material sell values, merchant pricing). This file is read-only by the audit; the capstone (story-007) will fold its annotations into `04_combat.md`, `07_bestiary.md`, and `09_economy.md`. Status legend: **confirmed** / **partial** / **aspirational** / **divergent** / **NOT_SHIPPED**.
>
> Peer audits: story-001 covers Phase 04 combat internals; story-002 covers Phase 07 bestiary internals. This file only addresses the encounter_roles overlay — refer there for combat phase machinery and creature stat block schema.

## Summary

**Headline:** `game_mechanics_encounter_roles.md` (added after the original milestones) is **0% built**. No `EncounterRole` enum, no role-modifier table, no `derive_role_stats`/`derive_role_loot`/`calculate_currency_drop` functions, no encounter budget system, no material sell-value table, no Boss signature/legendary action handling, no XP role multipliers. The only adjacent shipped surface is unrelated: `role` strings on NPCs in `content/npcs.json` describe narrative function ("guild hall master") not encounter roles, and `xp_value` exists per enemy in `content/encounter_templates.json` as a static value without role scaling.

**Ownership decision (per execution_plan.json §Milestone 3):** Phase 04 Combat is primary owner of the encounter_roles overlay. Phase 07 Bestiary cross-refs Role Definitions and Worked Example stat blocks; Phase 09 Economy cross-refs Currency Drop Rules and Material Sell Values. None of the three phases currently has a milestone item that names encounter_roles by file — every section below is **NOT_SHIPPED** and unallocated to a specific milestone.

| Section bucket | Confirmed | Partial | NOT_SHIPPED |
| --- | --- | --- | --- |
| Role Definitions (Minion/Standard/Elite/Boss/Named) | 0 | 0 | 1 |
| Combat Stat Modifiers (table + ability mods + Elite enhancement + Boss signature/legendary) | 0 | 0 | 5 |
| Loot Modifiers (table + Currency Drop Rules + Boss bonus + Material Sell Values) | 0 | 0 | 4 |
| XP Modifiers | 0 | 0 | 1 |
| Encounter Budget System | 0 | 0 | 3 |
| Worked Examples (Bandit / Grey Wolf / Mawling / Hollowed Knight) | 0 | 1 | 3 |
| DM Narration Guidance | 0 | 0 | 2 |
| Derivation Formula reference | 0 | 0 | 2 |
| Design Decisions 73-81 | 0 | 0 | 9 |

## Section Map

| gm_encounter_roles Section (file:line) | Owner Phase | Cross-refs | Code Evidence | Status |
| --- | --- | --- | --- | --- |
| Role Definitions — five roles (`game_mechanics_encounter_roles.md:11-63`) | 04 (primary) | 07 (creature roles in bestiary), 09 (currency drop tiers) | No `EncounterRole` enum in `apps/agent/`, no role type in `packages/shared/src/entities/`, no role field in `content/encounter_templates.json`. `content/npcs.json` `role` is narrative-only ("guild hall master"). | NOT_SHIPPED |
| Combat Stat Modifiers — HP/AC/Damage/Attack/DC/Save table (`:65-80`) | 04 (primary) | — | No `derive_role_stats`, no `ROLE_MODIFIERS` constant, no `apply_multiplier`/`scale_damage` in `apps/agent/rules_engine.py` or `apps/agent/combat_*.py`. | NOT_SHIPPED |
| Ability Modifications (`:82-89`) | 04 (primary) | 07 (creature `actives`/`passives` schema lives in bestiary) | No code path strips actives for Minions or enhances for Elites/Bosses. Enemies in `content/encounter_templates.json` use a single flat `action_pool`. | NOT_SHIPPED |
| Elite Enhancement Rules — frequency / expanded effect (`:90-101`) | 04 (primary) | 07 (which abilities exist to enhance) | No enhancement helper; no `enhance_abilities` function. | NOT_SHIPPED |
| Boss Signature Ability Design (`:103-111`) | 04 (primary) | 07 (signatures bound to creature identity) | No `signature_ability` field on creatures; no `generate_signature` function; no telegraph mechanism in narration tools. | NOT_SHIPPED |
| Boss Legendary Action (`:112-120`) | 04 (primary) | — | No `legendary_action` field on creatures, no per-round bonus action processing in `apps/agent/combat_resolution.py`. | NOT_SHIPPED |
| Loot Modifier Table — drop chance / qty / currency / unique (`:124-137`) | 09 (primary for currency + sell) **but** 04 owns invocation timing | 04 (Boss bonus item authored in encounter context), 07 (base loot table on creature) | No `derive_role_loot` function. `combat_end.py` reads static `xp_value` only; no loot generator processes role multipliers. Bestiary M7.4 names `generate_loot(creature, player_skills)` but no role parameter. | NOT_SHIPPED |
| Currency Drop Rules — per-category table + tier × dice (`:139-150`) | 09 (primary) | 04 (drop trigger on enemy death) | No `calculate_currency_drop` function; no `CURRENCY_RULES` table for Beast/Humanoid/Hollow categories; no `creature.category` discrimination in `combat_end.py`. M9.1 ships canonical price tables — different surface (item buy prices, not creature drops). | NOT_SHIPPED |
| Boss currency bonus + bonus item (context loot) (`:152-161`) | 09 (currency bonus) + 04 (context loot resolution) | 07 (which encounters expose context pool) | No `BOSS_CURRENCY_BONUS` constant; no context-loot pool concept anywhere in `content/` or `apps/agent/`. | NOT_SHIPPED |
| Material Sell Values — category × tier table (`:163-181`) | 09 (primary) | 07 (material category authored on creature loot rows) | No sell-value table in `content/items.json` (items have no `sell_value_sp` or per-tier pricing). M9.2 acceptance lists `calculate_price(base_price, disposition, faction_reputation)` for *buying* — no inverse merchant `sell_to_merchant` path; the sell-value floor table from `:167-177` is unallocated. | NOT_SHIPPED |
| Buyer specialization narration (`:181`) | 09 | 04 (DM narration) | No buyer-type tagging on merchants; `content/npcs.json` does not flag scholars/alchemists as material-specialist buyers. | NOT_SHIPPED |
| XP Modifiers — 0.5/1.0/1.5/2.0 (`:185-198`) | 04 (primary) | 01 (XP awarded into progression) | `content/encounter_templates.json` has flat per-enemy `xp_value` (Shadeling 25, Mawling 100, Hollow Warden 450) with no role multiplier. `combat_resolution.py` sums these as-is. | NOT_SHIPPED |
| Encounter Budget System — points + difficulty grid (`:201-235`) | 04 (primary, encounter design) | 07 (M7.4 "encounter builder" `build_encounter(tier, combatant_count, environment)` — does not consume budget points) | No `BUDGET_POINTS` table, no `encounter_budget` constraint check in `apps/agent/`. M7.4 deliverable mentions `build_encounter` but the signature takes `combatant_count` and `tier`, not budget. **Divergence vector** — M7.4 will need to be rewritten or supplemented to consume role-cost budget. | NOT_SHIPPED |
| Budget Allocation Rules — one Boss / Minion floor / tier gating (`:229-234`) | 04 (primary) | 07 (tier appropriateness lookup) | No validation function `validate_encounter_composition` exists. | NOT_SHIPPED |
| Example Budget Compositions (`:236-253`) | 04 (primary) | — | Documentation example only; no fixture file uses these compositions. | NOT_SHIPPED |
| Worked Example 1 — Bandit (Tier 1 Humanoid) full Minion/Standard/Elite/Boss derivations (`:259-349`) | 07 (creature data) + 04 (derivation engine) | 09 (currency rolls in loot) | **Absent.** No Bandit stat block in `content/encounter_templates.json` (only Shadeling, Mawling, Hollowed Scout, etc.). M7.2 lists Bandit as deliverable for Greyvale but no `bandit_*` entry ships. | NOT_SHIPPED |
| Worked Example 2 — Grey Wolf (Tier 1 Beast) (`:353-431`) | 07 + 04 | 09 (beast category drops no currency) | **Absent.** No `grey_wolf` entry in `content/encounter_templates.json`. M7.2 lists Grey Wolf as deliverable. | NOT_SHIPPED |
| Worked Example 3 — Mawling (Tier 2 Hollow-Rend) (`:435-515`) | 07 + 04 | 09 (Hollow-Rend 15% currency chance) | **Partial.** Base Mawling exists in `content/encounter_templates.json` (level 2, hp 18, ac 13) but with no role variants. None of the Minion/Elite/Boss Mawling stat blocks from the doc are seeded; `Rend shard`/`Dissolution membrane` loot rows are absent. | partial |
| Worked Example 4 — Hollowed Knight (Tier 3 Hollow-Wrack) (`:519-581`) | 07 + 04 | 09 (Tier 3 boss currency bonus +40 sp) | **Absent.** `content/encounter_templates.json` has a Hollowed Scout (level 3) but no Hollowed Knight stat block; no Elite "Dread Marshal" or Boss "Fallen Commander" variants. | NOT_SHIPPED |
| DM Narration Guidance — Communicating Roles via Voice (`:587-615`) | 04 (DM behavior) | 07 (per-creature narration cues live in bestiary) | No DM-side prompt hooks differentiate Minion/Elite/Boss narration cadence. `apps/agent/` voicing layer does not have role-aware narration templates. | NOT_SHIPPED |
| Narrating Loot — audio-first protocol (`:617-652`) | 04 (DM behavior) + 09 (loot generation) | 07 (skill-gated harvest data) | No `narrate_loot` agent tool; no batch-loot summarization helper; no Hollow-tainted warning prompt path. M7.4 deliverable names `resolve_harvesting(creature_id, player_skills)` — also NOT_SHIPPED per story-002. | NOT_SHIPPED |
| Derivation Formula — `derive_role_stats` / `derive_role_loot` / `calculate_currency_drop` pseudocode (`:660-766`) | 04 (primary) | 09 (currency rules table) | None of the three reference functions exist. `apps/agent/rules_engine.py` has no role-derivation symbols. | NOT_SHIPPED |
| `ROLE_MODIFIERS` constant (`:711-715`) | 04 (primary) | — | Constant not defined anywhere in `apps/agent/` or `packages/shared/`. | NOT_SHIPPED |
| Design Decisions 73-81 (`:770-790`) | mixed: 04 (74, 75, 76, 81), 07 (73), 09 (77, 78, 79, 80) | cross-link to `game_mechanics_decisions.md` | No decision is enforced in code: D73 (roles as modifiers, not separate creatures) — bestiary schema has no `role_variants` field, consistent with the decision but only because nothing is built; D74 (Minions strip actives) — not enforced; D75 (Elite enhance / Boss signature) — not enforced; D76 (1 legendary per round) — not enforced; D77 (harvest auto-success on skill match) — no harvest path; D78 (sell < craft) — no sell prices; D79 (Minions drop no currency) — no currency drops at all; D80 (context-driven Boss bonus) — no context loot pool; D81 (fractional budget, Minion 0.5) — no budget system. | NOT_SHIPPED (×9) |

## Ownership Rationale

- **04 primary.** Encounter roles are a *combat presentation layer* — they fire during encounter setup (Beat 0 / `encounter_start` in M4.1's state machine) and during combat resolution (HP/AC/Damage scaling, Boss legendary actions in the Resolution beat). The derivation engine itself (`derive_role_stats`, `enhance_abilities`, signature/legendary handling) belongs alongside `rules_engine.py` combat code. M4.1 owns the `combat_encounters` table; the role overlay slots into encounter setup before the phase loop begins. Decisions 74-76 and 81 are combat-mechanic decisions and belong to Phase 04.

- **07 cross-ref.** Role Definitions reference creature *categories* and stat-block fields (HP, AC, attacks, actives, passives, loot table) authored in Phase 07. Worked Examples 1-4 (Bandit / Grey Wolf / Mawling / Hollowed Knight) require the base stat blocks from M7.2 to exist before role derivation can produce them. Decision 73 (roles as modifiers, not separate entries) is a *bestiary schema* decision and constrains M7.1. Boss signature abilities are tactically tied to creature identity (M7.2 narration cues) even though they're authored at encounter time.

- **09 cross-ref.** Currency Drop Rules (`:139-161`), Material Sell Values (`:163-181`), and Buyer Specialization (`:181`) are economy concerns. M9.1 currently scopes "canonical price tables" for item *buy* prices — the encounter_roles sell-value table is a *separate* table the milestone does not list. M9.2 currently scopes `calculate_price` for buy-side disposition modifiers — no inverse `sell_to_merchant` path is defined. Decisions 77-80 are all economy decisions. **Phase 09 currently has no milestone item covering loot-side currency drops or material sell floor.** This is the most significant scope gap surfaced by this audit.

## Material Gaps

- **Phase 04 has no milestone item for encounter_roles** despite owning the system. M4.1 mentions `combat_encounters` table migration; no acceptance bullet covers role assignment, role-scaled stat derivation, signature abilities, or legendary actions. M4.2 (Action Economy) defines 6 declaration types but does not include legendary actions or Boss reaction windows.
- **Phase 07 M7.1 stat-block schema** does not include `signature_ability` or `legendary_action` fields. Per Decision 73 (roles are modifiers, not separate entries) the schema does *not* need `role_variants[]`, but it *does* need to support a `signature_ability_template` so Bosses can have one authored.
- **Phase 07 M7.4 encounter builder** uses `build_encounter(tier, combatant_count, environment)` — incompatible with the role-budget system in `:201-235`. Either M7.4 must be rewritten to consume budget points or a wrapper milestone must translate `combatant_count` → budget.
- **Phase 09 has zero coverage of loot-side economy** — no milestone owns: per-category currency drop tables (`:142-150`), Boss currency bonus per tier (`:154-159`), material sell-value table (`:167-177`), or buyer specialization (`:181`). M9.1 only covers item buy prices.
- **Content gap.** Worked Examples reference `Bandit`, `Grey Wolf`, `Mawling`, `Hollowed Knight` stat blocks. Only `Mawling` and a `Hollowed Scout` (not Knight) exist in `content/encounter_templates.json`. Until M7.2 lands the missing creatures, the Worked Examples cannot be exercised as fixtures.
- **DM narration gap.** No prompt template hooks differentiate Minion-collective vs Elite-individual vs Boss-introduced narration cadence. The audio-first loot protocol (`:617-652`) has no agent-tool surface.
- **All nine Design Decisions are unenforced** because nothing in the chain is built. They become live audit items as each downstream feature ships; for now they are inert documentation.

## Capstone Inputs

The capstone story (story-007) should consume this file and:

1. **`04_combat.md`** — insert a **new milestone M4.7 "Encounter Role Overlay"** (preferred over folding into M4.1 because the overlay is a self-contained derivation engine, not a state-machine change):
   - Header comment: `<!-- 04 is primary owner of encounter_roles overlay per audit/phase-encounter-roles.md; derivation engine, signature ability, legendary action, role-aware narration land here -->`
   - Deliverables: `EncounterRole` enum (Minion/Standard/Elite/Boss/Named), `ROLE_MODIFIERS` constant table (`gm_encounter_roles.md:711-715`), `derive_role_stats(base_creature, role)` (`:660-715`), `derive_role_loot(base_loot, role, category, tier)` (`:720-747`), `calculate_currency_drop(category, tier, role)` (`:749-765`), Boss legendary-action processor (1/round, `:112-120`), enhancement helper for Elite/Boss actives (`:90-101`).
   - Acceptance criteria: link to Role Definitions (`gm_encounter_roles.md:11-63`), Combat Stat Modifiers (`:65-120`), and Decisions 74, 75, 76, 81.
   - On M4.2 (Action Economy) — add inline comment: `<!-- cross-ref encounter_roles Decision 76: M4.7 introduces legendary_action as a Boss-only declaration outside the 6-type table; M4.2 declaration handler must dispatch to it -->` and an acceptance bullet: "Declaration handler accepts a 7th type `legendary_action` that fires once per round end-of-turn, dispatched by M4.7's overlay."
   - **Touchpoint flag (for the M4.7 author):** `apps/agent/session_data.py:42` (`xp_value` lives on the enemy dataclass — extending with `role: EncounterRole` and `signature_ability`/`legendary_action` fields touches all `combat_init.py` / `combat_resolution.py` / `combat_end.py` callsites). Test fixtures `apps/agent/tests/test_rules_combat.py:185` and `apps/agent/tests/sample_fixtures.py:50` hardcode `xp_value` without role context and must be migrated.

2. **`07_bestiary.md`** — add cross-references:
   - On M7.1 (stat block schema): `<!-- cross-ref encounter_roles: schema must support optional signature_ability_template and legendary_action fields (Boss only) for derivation by M4.7; see audit/phase-encounter-roles.md -->`. Add acceptance bullet: "Schema includes optional `signature_ability_template` and `legendary_action` fields on creature entries; existing seed entries default both to null." Link Decision 73.
   - On M7.2 (regional catalog): note Bandit + Grey Wolf are referenced by Worked Examples 1-2 (`gm_encounter_roles.md:259-431`); Hollowed Knight (not Scout) is referenced by Worked Example 4 (`:519-581`) and is currently absent from `content/encounter_templates.json`. M7.2 must seed all three.
   - On M7.4 (encounter builder): **rewrite the signature** from `build_encounter(tier, combatant_count, environment)` to `build_encounter(tier, budget_points, environment)` — the role-budget system (`gm_encounter_roles.md:201-235`) replaces combatant-count balancing. Acceptance bullet: "Encounter builder consumes budget points per role (Minion 0.5, Standard 1.0, Elite 2.0, Boss 4.0) and enforces Budget Allocation Rules: max 1 Boss, Minions require ≥1 non-Minion anchor, tier appropriateness check stands."

3. **`09_economy.md`** — insert a **new milestone M9.4 "Loot-side Economy: Currency Drops & Material Sell Values"**:
   - Header comment: `<!-- M9.4 claims loot-side economy per audit/phase-encounter-roles.md §Material Gaps; currency drops + material sell values fall under encounter_roles per gm_encounter_roles §Loot Modifiers -->`
   - Deliverables: `CURRENCY_RULES` table by creature category (Beasts/Humanoids/Hollow-Drift/Hollow-Rend+/Hollow-Named/Constructs/Undead, `gm_encounter_roles.md:142-150`), `BOSS_CURRENCY_BONUS` per-tier table (`:154-159`), Material Sell Value table by category × tier (`:167-177`) seeded into `content/items.json` or a new `content/material_values.json`, buyer specialization tagging on merchant NPCs (`:181`), `sell_to_merchant(material_id, merchant_id, character_id)` pricing function (inverse of M9.2's `calculate_price`).
   - Acceptance: enforce Decision 78 (sell value strictly < crafting yield), Decision 79 (Minions drop no currency — wired via `calculate_currency_drop` from M4.7), Decision 80 (Boss context loot pool authored per encounter, not per creature).
   - Cross-ref note on M9.1: "Item buy prices (M9.1) and material sell prices (M9.4) are separate tables — M9.1 does not cover sell-side."

`docs/INDEX.md:448` already lists `game_mechanics_encounter_roles.md` (790 lines) with a section map, and `:472,:484` cross-link it from the economy index — no INDEX.md update needed.
