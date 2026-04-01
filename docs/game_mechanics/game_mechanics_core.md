# Divine Ruin — Game Mechanics: Core Systems

> **Claude Code directive:** This is the foundational mechanics reference. Read this before implementing any rules engine logic. When this conflicts with `game_design_doc.md`, this document wins.
>
> **Related docs:** `game_mechanics_combat.md` (dramatic dice, combat, conditions, death, social encounters, travel, gathering), `game_mechanics_archetypes.md` (class profiles, ability model), `game_mechanics_magic.md` (Resonance, spell catalogs), `game_mechanics_patrons.md` (divine patron system), `game_mechanics_bestiary.md` (creatures, materials), `game_mechanics_npcs.md` (NPC framework, mentors, companions), `game_mechanics_crafting.md` (crafting system, item catalog), `game_mechanics_decisions.md` (all 72 design decisions)

---

## Document Status (All Mechanics Files)

| Section | File | Status |
|---|---|---|
| Implementation Directive | `_core` | **LOCKED** |
| Core Math (attributes, proficiency, HP, resources) | `_core` | **LOCKED** |
| Racial Traits (all 6 races — attributes, abilities, Resonance cross-ref) | `_core` | **LOCKED** |
| Skill System (20 skills, 4 tiers, Expert/Master unlocks) | `_core` | **LOCKED** |
| XP, Leveling & Unified Progression Table (L1-20) | `_core` | **LOCKED** |
| Async Training System (cycle definition, time ranges, midpoint decisions, activity slots) | `_core` | **LOCKED** |
| Companion Errands (4 errand types, return scenes, risk, companion bonuses) | `_core` | **LOCKED** |
| Async Concurrency Model (3 independent slots, Artificer exception, companion availability) | `_core` | **LOCKED** |
| Combat System (phase-based action economy, initiative, 4-beat flow) | `_combat` | **LOCKED** |
| Combat Math (attack rolls, AC, damage, saves, pacing) | `_combat` | **LOCKED** |
| Status Effects (all conditions incl. Prone, Grappled, Restrained, Paralyzed, Concentration) | `_combat` | **LOCKED** |
| Resting | `_combat` | **LOCKED** |
| Death and Dying (Fallen, death saves, Mortaen's domain, escalating costs, Hollowed death, resurrection location) | `_combat` | **LOCKED** |
| Social Encounter Resolution (3-tier model, disposition-as-damage, structured social scenes) | `_combat` | **LOCKED** |
| Dramatic Dice System (always/contextual/never rules, frequency targets, integration with all beats) | `_combat` | **LOCKED** |
| Travel and Exploration (3 travel modes, encounters, navigation, exhaustion, camping) | `_combat` | **LOCKED** |
| Gathering and Resource Discovery (skill-gated gathering, regional tables, fixed nodes, discovery) | `_combat` | **LOCKED** |
| Character Creation (5-step flow, standard array, starting equipment, auto-derived culture) | `_core` | **LOCKED** |
| Archetype Profiles (16 of 16) | `_archetypes` | **LOCKED** — Warrior, Mage, Druid, Cleric, Rogue, Bard, Guardian, Skirmisher, Artificer, Seeker, Beastcaller, Warden, Paladin, Oracle, Spy, Diplomat |
| Core + Elective Ability Model | `_archetypes` | **LOCKED** |
| Spell Acquisition (Three-Track) | `_archetypes` | **LOCKED** |
| Martial Mentor-Style System | `_archetypes` | **LOCKED** |
| Magic System — Three Sources & Resonance | `_magic` | **LOCKED** |
| Racial Resonance Traits | `_magic` | **LOCKED** |
| Arcane Spell Catalog (30 spells) | `_magic` | **LOCKED** |
| Divine Spell Catalog (28 spells) | `_magic` | **LOCKED** |
| Primal Spell Catalog (29 spells) | `_magic` | **LOCKED** |
| Divine Patron Modifiers (10 gods + Unbound) | `_patrons` | **LOCKED** |
| Veythar Post-Reveal Mechanics | `_patrons` | **LOCKED** |
| Enemy Stat Blocks / Bestiary | `_bestiary` | **LOCKED** — Schema, 9 Hollow creatures (all 4 tiers inc. Named), 15 natural creatures, material catalog, encounter guidelines |
| NPC Framework & Mentor Registry | `_npcs` | **LOCKED** — Role archetypes, combat NPC stat blocks, mentor registry, settlement templates, encounter templates, companion framework (Kael/Lira/Tam/Sable) |
| Crafting System & Item Catalog | `_crafting` | **LOCKED** — Recipe system, crafting resolution, experimentation, item catalog (weapons, armor, gear, consumables, enchantments, magic items), durability, async crafting |
| Design Decisions Log (all 72 decisions) | `_decisions` | **LOCKED** — Canonical record of all locked design decisions with reasoning |

---

## Implementation Directive: The LLM is a Narrator, Not an Engine

> **This section is the single most important architectural principle in the game. Every system in this document must be implemented in accordance with it. Read this before writing any code.**

### The Principle

**The LLM's only job is narration. Everything mechanical is deterministic. Everything contextual is injected. The LLM is never trusted with math, never allowed off-role, and never given raw numbers where narrative cues can be given instead.**

### Three Boundaries

**1. The LLM never does math.**

All calculation — dice rolls, modifier application, DC comparison, HP tracking, Resonance accumulation, XP awards, skill tier advancement, damage resolution — happens in the deterministic rules engine. The LLM calls tools (`request_skill_check`, `request_attack`, `award_xp`, etc.) and receives structured results. It never adds numbers, never compares values, never tracks state.

*Wrong:* The LLM receives "roll: 14, modifier: +6, DC: 13" and determines success.
*Right:* The rules engine receives the request, resolves it completely, and returns `{ result: "success", margin: 1, narrative_hint: "barely_succeeded" }`. The LLM narrates from the hint.

**2. The LLM never leaves its role.**

The agent harness constrains the DM agent to in-world narration. The system prompt, tool definitions, and harness enforce this boundary. A player attempting to have an off-topic conversation receives an in-character response, not a refusal message and not off-topic content.

*Wrong:* Player says "What's the weather in Seattle?" → LLM says "I can't help with that."
*Right:* Player says "What's the weather in Seattle?" → DM says "The skies over the Greyvale are darkening. Rain before nightfall, I'd wager."

The LLM cannot be used as a general assistant, coding helper, math tutor, or anything other than the DM of Divine Ruin. The harness must make off-role responses structurally impossible, not merely discouraged.

**3. The rules engine returns narrative-ready packets, not raw numbers.**

Every tool result must include narrative cues that the LLM can weave into its response. The LLM should never need to interpret a number to decide how to narrate.

*Wrong:* `{ resonance: 7 }` — the LLM must know that 7 means Flickering.
*Right:* `{ resonance_state: "Flickering", narration_cue: "The caster's magic is visibly distorting — colors shift at the edges of their spells, and the air carries a faint wrongness.", mechanical_effects: "+1 damage die on next spell" }`

*Wrong:* `{ hp: 12, max_hp: 45 }` — the LLM must calculate 27%.
*Right:* `{ hp_state: "critical", narration_cue: "badly wounded — barely standing", hp_fraction: "below_quarter" }`

*Wrong:* `{ skill_uses: 19, threshold: 20 }` — the LLM must know advancement is close.
*Right:* `{ skill_advancement_imminent: true, skill: "Persuasion", next_tier: "Expert", narration_cue: "You feel your understanding of persuasion deepening — one more meaningful challenge and something will click." }`

### What This Means for Each System

| System | Rules Engine Does | LLM Does |
|---|---|---|
| **Skill checks** | Rolls dice, applies all modifiers, compares to DC, determines success/failure, generates narrative_hint | Narrates the attempt and outcome using the hint |
| **Combat** | Resolves attacks, calculates damage, updates HP, tracks initiative, manages combat state machine | Narrates the action, using hit/miss/crit hints and damage descriptions |
| **Resonance** | Tracks per-caster Resonance value, determines state transitions, rolls Hollow Echo table, applies effects | Narrates the Veil disturbance, weaving in the narration_cue from the state |
| **Progression** | Tracks XP, checks level thresholds, tracks skill use counters, triggers tier advancement | Narrates the growth moment using the level-up or skill-advancement cue |
| **Context injection** | Background process injects location details, quest hints, NPC data, time of day, Resonance states, nearby entities | Incorporates injected context naturally into narration without acknowledging the injection |
| **Divine favor** | God-agent heartbeat evaluates alignment, adjusts favor score, triggers tier transitions | Narrates the god's response (whisper, approval, disappointment) using the provided cue |
| **Veil Ward** | Calculates modified Resonance rates, adjusts damage/DC penalties, tracks ward duration | Narrates the ward's presence and its effect on the magical environment |

### Narrative-Ready Packet Format

All tool results returned to the LLM should follow this structure:

```python
class ToolResult:
    success: bool                    # Did the action succeed?
    narrative_hint: str              # "barely_succeeded", "overwhelming_success", "catastrophic_failure", etc.
    narration_cue: str               # A sentence the LLM can draw from (not dictate verbatim)
    mechanical_effects: list[str]    # What changed mechanically (for the LLM's awareness, not narration)
    ui_pushes: list[dict]            # What the client received (the LLM doesn't need to describe these)
    context_updates: dict            # What changed in the world state (injected into next turn's context)
```

The `narration_cue` is a suggestion, not a script. The LLM should absorb its meaning and narrate in its own voice and style. The cue exists so the LLM never needs to interpret a number to decide what happened.

### Why This Matters

1. **Consistency.** LLMs drift. If the LLM decides whether a roll succeeds, different sessions will apply different standards. The deterministic engine is the same every time.

2. **Trust.** If players discover the LLM miscalculated damage or applied the wrong modifier, trust collapses instantly. The engine is testable and auditable. The LLM is not.

3. **Safety.** The harness boundary prevents the LLM from being jailbroken into off-topic behavior. It's not a matter of prompting — the tool definitions and harness structure make it so the only actions available to the LLM are DM actions.

4. **Cost.** Every token the LLM spends on math or state-tracking is a token not spent on narration — the thing it's actually good at. Let the engine handle what engines handle. Let the LLM do what LLMs do.

---

## Core Resolution Mechanic

**d20 + modifier vs difficulty class (DC).**

```
roll = d20 + attribute_modifier + proficiency_bonus + skill_tier_bonus + situational_modifiers
success = roll >= DC
```

The player never sees the math. The DM narrates tension and outcome. The rules engine returns a `narrative_hint` with each result: "barely succeeded", "overwhelming success", "catastrophic failure", "close but not enough".

### Critical Hits and Fumbles

- **Natural 20:** Always succeeds. Weapon attacks deal double damage dice (not double modifier). Skill checks succeed with exceptional results.
- **Natural 1:** Always fails. Weapon attacks miss regardless of modifier. Skill checks fail with potential complications (DM narrates).

---

## Attributes

Six attributes, standard modifier formula.

```python
modifier = (score - 10) // 2  # floor division
```

### Starting Scores

**Standard array:** 16, 14, 13, 12, 10, 8 — player assigns to any attributes.
**Point buy:** Alternative method, details TBD.

### Attribute Score Ranges

| Score | Modifier | Description |
|---|---|---|
| 8 | -1 | Below average |
| 10 | +0 | Average |
| 12 | +1 | Above average |
| 14 | +2 | Notable |
| 16 | +3 | Exceptional |
| 18 | +4 | Extraordinary |
| 20 | +5 | Peak mortal limit (hard cap) |

### Attribute Increases

At levels **4, 8, 12, 16, and 20**, the player gains **+2 attribute points** to distribute. No single attribute can exceed 20.

### Attribute Descriptions

| Attribute | Governs | Used For |
|---|---|---|
| **Strength (STR)** | Physical power, carrying capacity | Melee attacks, Athletics, breaking things |
| **Dexterity (DEX)** | Agility, reflexes, precision | Ranged attacks, AC (light/medium armor), Stealth, initiative |
| **Constitution (CON)** | Endurance, vitality, resilience | Hit points, Stamina pool, concentration, Endurance checks |
| **Intelligence (INT)** | Reasoning, memory, analysis | Arcane magic, Investigation, lore knowledge |
| **Wisdom (WIS)** | Perception, intuition, willpower | Divine/primal magic, Perception, Insight, Survival |
| **Charisma (CHA)** | Force of personality, presence | Social skills, Bard magic, Persuasion, Deception, Intimidation |

---

## Proficiency Bonus

Scales with level in three breakpoints. Applies to all skills at Trained tier or higher. Does NOT apply to Untrained skill checks.

| Level Range | Proficiency Bonus |
|---|---|
| 1–6 | +1 |
| 7–13 | +2 |
| 14–20 | +3 |

```python
def proficiency_bonus(level: int) -> int:
    if level <= 6: return 1
    if level <= 13: return 2
    return 3
```

---

## Skill System

### Skill Tiers

Four-tier system. Tiers provide both numeric bonuses and qualitative capability gates.

| Tier | Numeric Bonus | Proficiency Bonus Applies? | Capability |
|---|---|---|---|
| **Untrained** | +0 | No | Can attempt basic uses only. Likely to fail moderate tasks. |
| **Trained** | +2 | Yes | Competent. Reliable at moderate DCs. |
| **Expert** | +4 | Yes | Unlocks advanced uses (per-skill). Can attempt DCs 24+ (Extreme). |
| **Master** | +5 | Yes | Signature capability (per-skill, always active). Can attempt DCs 28+ (Legendary). |

### Total Modifier Formula

```python
def skill_modifier(attribute_mod: int, proficiency: int, tier: str) -> int:
    tier_bonus = {"Untrained": 0, "Trained": 2, "Expert": 4, "Master": 5}
    if tier == "Untrained":
        return attribute_mod  # no proficiency bonus for untrained
    return attribute_mod + proficiency + tier_bonus[tier]
```

### Modifier Range

| Character State | Total Modifier |
|---|---|
| Level 1, Untrained, 8 in attribute | -1 (floor) |
| Level 1, Trained, 16 in attribute | +6 |
| Level 7, Expert, 16 in attribute | +9 |
| Level 10, Expert, 18 in attribute | +10 |
| Level 14, Expert, 18 in attribute | +11 |
| Level 20, Master, 20 in attribute | +13 (ceiling) |

**Total spread: 14 points on a d20.** The die always matters at every level.

### Skill Tier Advancement

**Hybrid model — session use + async Training feed the same counter.**

- The rules engine tracks a hidden usage counter per skill. Every `request_skill_check` call for that skill increments it.
- Async Training activities also increment the counter, at a slower rate than active session use.
- Advancement thresholds (approximate, tunable):
  - Untrained → Trained: **8 uses**
  - Trained → Expert: **20 uses**
  - Expert → Master: **40 uses** + a **qualifying moment** (narrative beat in a high-stakes session situation, triggered by the DM when the player at threshold performs exceptionally on that skill)
- The player never sees the counter. They experience a "ding" moment when they cross the threshold, narrated by the DM.
- Training (async) is the only reliable way to advance skills the player rarely uses in sessions. This keeps Training useful throughout the entire game.

### Skill List (20 Skills)

> **Reconciliation note:** The GDD lists one set of 15 skills, `rules_engine.py` lists a different 15. The canonical list below resolves both. Update `rules_engine.py` to match this list.

#### Physical Skills (STR/DEX/CON)

| Skill | Attribute | Notes |
|---|---|---|
| **Athletics** | STR | Climbing, swimming, jumping, grappling |
| **Acrobatics** | DEX | Balance, tumbling, aerial maneuvers |
| **Stealth** | DEX | Moving unseen and unheard |
| **Sleight of Hand** | DEX | Pickpocketing, lockpicking, fine manipulation |
| **Endurance** | CON | Sustained physical effort, marching, resisting exhaustion |

#### Mental Skills (INT/WIS)

| Skill | Attribute | Notes |
|---|---|---|
| **Arcana** | INT | Magical theory, identifying spells, Resonance sensing |
| **History** | INT | Historical knowledge, recognizing cultural artifacts |
| **Investigation** | INT | Deductive reasoning, analyzing clues, searching deliberately |
| **Nature** | INT | Flora, fauna, weather, terrain, natural phenomena |
| **Religion** | INT | Theological knowledge, divine practices, Hollow lore |
| **Crafting** | Higher of INT or WIS | Creating, repairing, and enhancing items. See Crafting Skill section below |
| **Medicine** | WIS | Treating wounds, diagnosing conditions, herbal remedies |
| **Perception** | WIS | Noticing things passively — sounds, movement, hidden objects |
| **Survival** | WIS | Tracking, foraging, navigation, reading the land |
| **Insight** | WIS | Reading people — detecting lies, sensing motives, gauging emotions |
| **Animal Handling** | WIS | Calming, commanding, and communicating with animals |

#### Social Skills (CHA)

| Skill | Attribute | Notes |
|---|---|---|
| **Persuasion** | CHA | Convincing through logic, charm, or appeal |
| **Deception** | CHA | Lying convincingly, maintaining a cover story |
| **Intimidation** | CHA | Coercing through threat, presence, or force of will |
| **Performance** | CHA | Entertaining, oration, musical ability (Bard core skill) |

**Total: 20 skills** (5 Physical, 11 Mental, 4 Social).

```python
SKILLS = {
    # Physical
    "Athletics": "STR", "Acrobatics": "DEX", "Stealth": "DEX",
    "Sleight of Hand": "DEX", "Endurance": "CON",
    # Mental
    "Arcana": "INT", "History": "INT", "Investigation": "INT",
    "Nature": "INT", "Religion": "INT", "Crafting": "max(INT, WIS)",
    "Medicine": "WIS", "Perception": "WIS", "Survival": "WIS",
    "Insight": "WIS", "Animal Handling": "WIS",
    # Social
    "Persuasion": "CHA", "Deception": "CHA",
    "Intimidation": "CHA", "Performance": "CHA"
}
```

> **Implementation note for `rules_engine.py`:** The SKILLS map must be updated to this canonical list. Key changes from current implementation: add Endurance (CON), Crafting (max INT/WIS), Deception (CHA), Intimidation (CHA), Performance (CHA). Remove nothing — all current skills remain. Constitution now has an associated skill (Endurance). Crafting uses `max(character.int_mod, character.wis_mod)` as its attribute modifier.

### Crafting Skill vs. Async Crafting Activity

These are complementary but independent systems:

| System | What It Provides | Who Uses It |
|---|---|---|
| **Crafting skill** | Competence and ceiling — *what* you can make and *how good* it is | Any character with Crafting proficiency; determines quality |
| **Async crafting activity** | Time and opportunity — sustained hours of workshop labor | Any character choosing crafting as their downtime activity |

**How they interact:** Async crafting sessions increment the hidden Crafting skill counter (use-based advancement). A player who consistently chooses crafting as their async activity will naturally advance toward Expert through the system we designed. The async activity IS the primary training path for Crafting.

**In-session crafting:** The Crafting skill also has in-session utility independent of async — improvise tools, field-repair equipment, identify craftsmanship quality, assess material value. These don't require the async loop.

---

### Skill Expert and Master Unlocks

> **Design principle:** Expert unlocks open new categories of action that Trained characters auto-fail. Master unlocks grant a signature capability that is always active and reshapes how the character interacts with the world. Both are earned through the hybrid skill advancement system (session use + Training async). Expert→Master additionally requires a qualifying narrative moment.

#### Physical Skills

**Athletics (STR)**

| Tier | Unlock |
|---|---|
| Expert | Attempt superhuman feats: break reinforced doors, leap gaps wider than 10 ft, grapple creatures one size larger. Auto-fail for Trained. |
| Master | **Immovable Anchor** — Cannot be forcibly moved against your will (shoved, pushed, thrown, pulled by spells) unless you choose to allow it. Cannot fall prone from physical force. |

**Acrobatics (DEX)**

| Tier | Unlock |
|---|---|
| Expert | Attempt impossible movement: run along walls briefly, flip over enemies to reposition, land from any fall under 40 ft without damage. Auto-fail for Trained. |
| Master | **Perfect Balance** — Cannot be knocked prone. Cannot trigger pressure plates, tripwires, or step-activated traps. Can stand on any surface regardless of width or angle. |

**Stealth (DEX)**

| Tier | Unlock |
|---|---|
| Expert | Hide in plain sight: attempt to become hidden even when actively observed, as long as any visual obstruction exists (dim light, light cover, crowd). Trained requires full cover. |
| Master | **Ghost Walk** — While hidden, movement makes no sound at all. Cannot be detected by hearing, tremorsense, or non-visual senses. Only direct line of sight or magical detection reveals you. |

**Sleight of Hand (DEX)**

| Tier | Unlock |
|---|---|
| Expert | Attempt during combat: plant items on enemies, steal worn objects, swap held items with decoys. Pick locks under time pressure without disadvantage. |
| Master | **Impossible Hands** — Pick any non-magical lock automatically (no roll, just time). Palm or swap objects a creature is actively gripping (contested check only vs Expert+ Perception). |

**Endurance (CON)**

| Tier | Unlock |
|---|---|
| Expert | Forced march 24 hours without exhaustion. Hold breath 10 minutes. Resist first stage of progressive conditions (poison, disease, Hollowed) automatically for 1 hour. |
| Master | **Iron Constitution** — Exhaustion caps at 3 stacks (others cap at 5). Immune to non-magical disease. Short rests take 30 minutes instead of 1 hour. |

#### Mental Skills

**Arcana (INT)**

| Tier | Unlock |
|---|---|
| Expert | Identify any spell being cast in real time (no check). Sense approximate Resonance levels of nearby casters and local Veil condition. Detect magical traps, wards, and enchantments by sight. |
| Master | **Arcane Intuition** — Instinctively know Focus cost and Resonance generation of any spell before casting, including environmental modifiers. Sense exact magical properties of any touched item (no Detect Magic needed). DM reveals all magical information automatically. |

**History (INT)**

| Tier | Unlock |
|---|---|
| Expert | DM volunteers relevant historical context during exploration and NPC interactions without you asking. Identify cultural origin, age, and significance of artifacts and ruins. |
| Master | **Living Archive** — Once per session, declare "I remember reading about this." DM must provide one useful, true, relevant fact about the current situation, NPC, or location from world history. |

**Investigation (INT)**

| Tier | Unlock |
|---|---|
| Expert | Reconstruct events from evidence: at crime scenes, ambush sites, or abandoned camps, the DM narrates what happened, who was involved, and when. See through disguises and illusions with a check (auto-fail for Trained). |
| Master | **Deductive Engine** — When entering a new room, area, or scene, the DM automatically reveals the single most important hidden detail (concealed door, trap, hidden NPC, most valuable item). No search action required. |

**Nature (INT)**

| Tier | Unlock |
|---|---|
| Expert | Identify any natural creature's strengths and weaknesses on sight (DM reveals resistances, vulnerabilities, behavior). Predict weather 24 hours ahead with certainty. Identify all plants and fungi including rare alchemical ingredients. |
| Master | **Naturalist's Sense** — Sense the health and mood of every living thing within earshot. Animals do not attack you unless magically compelled. DM tells you when the local ecosystem is abnormal, including subtle Hollow corruption not yet visibly manifested. |

**Religion (INT)**

| Tier | Unlock |
|---|---|
| Expert | Identify divine magic on sight (which god, what purpose). Sense consecrated and desecrated ground without check. Recognize followers of any god by behavioral patterns. |
| Master | **Theologian's Insight** — Understand the mechanical relationship between gods and the Veil theoretically. DM shares additional lore during divine encounters. Once per session, predict how a god-agent will respond to a player action before it happens. |

**Crafting (Higher of INT or WIS)**

| Tier | Unlock |
|---|---|
| Expert | **Veil-Stabilized Crafting** — Imbue items with magical properties during async crafting using rare materials. Create items with Resonance interactions (Resonance reduction, Hollow Echo advantage, Flickering-state bonuses). Work safely with Hollow-touched materials that would corrupt untrained hands. |
| Master | **Masterwork Creation** — Once per completed crafting project, declare the item a Masterwork. Define a unique property in collaboration with the DM, themed to materials and method. Masterwork items are named, tracked, and can become legendary gear. Also: improve existing items permanently (re-forge, enhance, repair Masterwork items crafted by others). |

**Medicine (WIS)**

| Tier | Unlock |
|---|---|
| Expert | Stabilize dying creatures automatically (no check). Diagnose any non-magical condition by observation. Short rest medical attention restores 1d6 extra HP to one patient. Identify poisons and antidotes on sight. |
| Master | **Field Surgeon** — During short rest, remove one negative condition (Poisoned, Wounded, Blinded, stage 1 Hollowed) from a patient with no Focus cost. Automatically detect when a creature is under magical compulsion (Charmed, Dominated) by observing behavior. |

**Perception (WIS)**

| Tier | Unlock |
|---|---|
| Expert | Passive detection radius doubled. DM tells you when someone is watching you (even if unidentified). Process background sounds for useful information (overhear distant conversations, estimate enemy numbers from footsteps). |
| Master | **Omniscient Awareness** — Cannot be surprised, ever. Always aware of every creature within earshot, including hidden ones (know something is there, not necessarily where or what). DM shares ambient information automatically: nearby creature count, environmental state, changes since last visit. |

**Survival (WIS)**

| Tier | Unlock |
|---|---|
| Expert | Track any creature across any terrain (including stone and water) within 48 hours. Navigate without landmarks. Camp setup grants +2 HP to everyone's short rest. |
| Master | **Apex Predator** — In wilderness, you choose where encounters happen (never ambushed, always ambush others). Track trails up to a week old across any surface. DM automatically reveals what passed through an area and when. |

**Insight (WIS)**

| Tier | Unlock |
|---|---|
| Expert | Detect lies automatically — DM signals when an NPC lies without a check (you don't know the truth, just that the statement was false). Read emotional states with precision: DM tells you what an NPC is feeling as granular narrative detail. |
| Master | **Empathic Clarity** — Know the true motivation of any NPC you converse with for 30+ seconds. Not surface emotions, but core drive. DM reveals: "They want X, and they're willing to Y to get it." Most powerful social reconnaissance ability in the game. |

**Animal Handling (WIS)**

| Tier | Unlock |
|---|---|
| Expert | Calm hostile natural animals without check (unless magically enraged). Command trained animals for complex multi-step tasks. Bond with a wild animal in a single encounter (follows you for session). |
| Master | **Beastfriend** — Communicate with animals at basic conceptual level (intentions, emotions, simple ideas — not language). Bonded animals gain +2 to all rolls within earshot. Sense what nearby animals sense (a bird sees danger approaching → you know). |

#### Social Skills

**Persuasion (CHA)**

| Tier | Unlock |
|---|---|
| Expert | Attempt to shift hostile NPCs to neutral (auto-fail for Trained). Negotiate beyond normal NPC parameters (better prices, unusual favors, restricted access). |
| Master | **Silver Tongue** — Once per session, automatically succeed on a Persuasion check regardless of DC (impossible requests still fail). NPCs you've successfully persuaded remember you favorably: permanent +2 disposition in future encounters. |

**Deception (CHA)**

| Tier | Unlock |
|---|---|
| Expert | Maintain long-term false identities (sustained personas, not single lies). Plant false information NPCs spread to others. Lie under magical truth detection (Expert Deception vs detection DC). |
| Master | **Living Lie** — Sustain up to 3 simultaneous false identities without checks. Discovery of one lie doesn't compromise others (compartmentalized deception). Once per session, plant a false memory in an NPC through conversational manipulation (WIS save). |

**Intimidation (CHA)**

| Tier | Unlock |
|---|---|
| Expert | Intimidate significantly stronger creatures without disadvantage (Trained has disadvantage). Demoralize groups: success against one enemy gives -1 to all their allies' next actions. |
| Master | **Terrifying Presence** — At combat start, all enemies who see/hear you must WIS save or be Frightened 1 round (free, automatic). Once per session, end combat by Intimidation: all remaining enemies flee if combined HP < your max HP. |

**Performance (CHA)**

| Tier | Unlock |
|---|---|
| Expert | Perform during combat for mechanical effect: grants all allies +1 to next roll (no Focus cost — pure skill). Lasting impressions: NPCs who witness Expert performance gain permanent +2 disposition. |
| Master | **Legendary Performer** — Performances are supernatural in impact without magic. Once per session: calm a riot, stop an NPC fight, cause an entire room to adopt an emotional state of your choice. Combat performance bonus increases to +2. |

---

## Difficulty Class (DC) Scale

DCs are set by the rules engine based on entity data (lock quality, NPC disposition, terrain difficulty), not by the AI DM. This prevents drift.

| DC | Label | Untrained L1 (+0) | Trained L7 (+6) | Master L20 (+13) | Examples |
|---|---|---|---|---|---|
| 5 | Trivial | 80% | Auto | Auto | Climb knotted rope, recall common knowledge |
| 8 | Easy | 65% | Auto | Auto | Pick a simple lock, track muddy footprints |
| 12 | Moderate | 45% | 75% | Auto | Persuade neutral NPC, swim rough water |
| 16 | Hard | 25% | 55% | 90% | Convince hostile guard, disarm complex trap |
| 20 | Very Hard | 5% | 35% | 70% | Pick masterwork lock, decipher ancient text |
| 24 | Extreme | Impossible | 15% | 50% | **Requires Expert tier or higher to attempt** |
| 28 | Legendary | Impossible | Impossible | 30% | **Requires Master tier to attempt** |

### DC Setting Rules

- DCs 24+ auto-fail for characters below Expert tier in the relevant skill.
- DCs 28+ auto-fail for characters below Master tier.
- NPC disposition-based DCs: `DC = 20 - disposition_score` (disposition ranges 0-10, so DC ranges 10-20).
- Lock DCs defined in item entity data.
- Environmental hazard DCs defined in location entity data.
- The DM can request a DC from the rules engine via context (e.g., "persuade this NPC") and the engine calculates based on entity state.

### Advantage and Disadvantage

- **Advantage:** Roll 2d20, take the higher. Grants ~+3.3 effective bonus.
- **Disadvantage:** Roll 2d20, take the lower. Imposes ~-3.3 effective penalty.
- Advantage and disadvantage cancel each other out regardless of how many sources of each exist (binary, not stacking).

---

## Hit Points

### HP Formula

```python
def calculate_hp(level: int, hp_base: int, hp_growth: int, con_mod: int) -> int:
    if level == 1:
        return hp_base + con_mod
    return hp_base + con_mod + (level - 1) * (hp_growth + con_mod // 2)
```

**CON modifier contributes at half rate per level** (floor division) to keep HP bounded.

### HP by Archetype Category

| Category | Archetypes | Base HP | Growth/Level | L1 (CON +1) | L10 (CON +1) | L20 (CON +1) |
|---|---|---|---|---|---|---|
| **Martial** | Warrior, Guardian, Skirmisher | 12 | 5 | 13 | 62 | 117 |
| **Primal / Divine** | Druid, Beastcaller, Warden, Cleric, Paladin, Oracle | 10 | 4 | 11 | 50 | 96 |
| **Arcane / Shadow / Support** | Mage, Artificer, Seeker, Rogue, Spy, Whisper, Bard, Diplomat | 8 | 3 | 9 | 39 | 75 |

### HP Ranges at Key Levels (CON +0 to +5)

| Level | Martial (low/high CON) | Primal-Divine (low/high) | Arcane-Shadow-Support (low/high) |
|---|---|---|---|
| 1 | 12 / 17 | 10 / 15 | 8 / 13 |
| 5 | 32 / 49 | 26 / 39 | 20 / 33 |
| 10 | 57 / 89 | 46 / 72 | 35 / 55 |
| 20 | 107 / 166 | 86 / 134 | 65 / 103 |

---

## Resource System — Stamina and Focus

### Design Philosophy

Two pools, narrative-state narration. The player hears "you're winded" (low Stamina) or "your concentration wavers" (low Focus). The DM knows the exact numbers; the player feels the state. The character sheet panel shows exact values.

### Stamina

Fuels physical and martial active abilities.

- **Base formula (Stamina-primary archetypes):** `8 + CON modifier + level`
- **Base formula (secondary/split):** Varies by archetype (see profiles)
- **Recovery:** 2 points per round in combat. Full on short rest.
- **Narrative states:**
  - Full (100%): "You feel ready"
  - High (60-99%): No narration needed
  - Low (20-59%): "You're breathing hard" / "You feel the strain"
  - Critical (1-19%): "You're winded" / "Your muscles burn"
  - Empty (0): "You have nothing left" — Stamina abilities unavailable

### Focus

Fuels magical and mental active abilities.

- **Base formula (Focus-primary archetypes):** `8 + casting attribute modifier + level`
- **Base formula (secondary/split):** Varies by archetype (see profiles)
- **Recovery:** None in combat (except specific abilities). Half pool on short rest. Full on long rest.
- **Narrative states:**
  - Full (100%): "Your mind is clear"
  - High (60-99%): No narration needed
  - Low (20-59%): "Your concentration wavers" / "The magic feels thin"
  - Critical (1-19%): "You can barely hold a thought" / "The arcane energy is almost spent"
  - Empty (0): "Your mind is empty" — Focus abilities unavailable

### Pool Allocation Patterns

| Pattern | Stamina | Focus | Archetypes |
|---|---|---|---|
| **Stamina-only** | Full pool, grows with level | None | Warrior, Rogue (and likely Guardian, Skirmisher, Spy) |
| **Focus-only** | None | Full pool, grows with level | Mage (and likely Artificer, Seeker) |
| **Focus-primary** | Small flat pool (~4+CON) | Full pool, grows with level | Druid, Cleric (and likely Beastcaller, Warden, Paladin, Oracle) |
| **Split** | Half pool, grows at half rate | Half pool, grows at half rate | Bard (and likely Diplomat, Whisper) |

---

## Experience Points and Leveling

### XP Thresholds

Designed for ~100 XP per session average.

| Level | XP to Next Level | Cumulative XP | ~Sessions to Reach | Sessions at This Level |
|---|---|---|---|---|
| 1 | — | 0 | 0 | 2 |
| 2 | 200 | 200 | 2 | 2.5 |
| 3 | 250 | 450 | 4.5 | 3 |
| 4 | 300 | 750 | 7.5 | 3 |
| 5 | 300 | 1,050 | 10.5 | 4 |
| 6 | 400 | 1,450 | 14.5 | 4.5 |
| 7 | 450 | 1,900 | 19 | 5 |
| 8 | 500 | 2,400 | 24 | 5 |
| 9 | 500 | 2,900 | 29 | 5.5 |
| 10 | 550 | 3,450 | 34.5 | 6 |
| 11 | 600 | 4,050 | 40.5 | 6 |
| 12 | 600 | 4,650 | 46.5 | 6.5 |
| 13 | 650 | 5,300 | 53 | 7 |
| 14 | 700 | 6,000 | 60 | 7.5 |
| 15 | 750 | 6,750 | 67.5 | 8 |
| 16 | 800 | 7,550 | 75.5 | 8.5 |
| 17 | 850 | 8,400 | 84 | 9 |
| 18 | 900 | 9,300 | 93 | 9.5 |
| 19 | 950 | 10,250 | 102.5 | 10 |
| 20 | 1,000 | 11,250 | 112.5 | — |

### XP Sources Per Session (~100 average)

| Source | XP Range | Notes |
|---|---|---|
| Combat encounters | 15–40 | Per encounter. Scales with difficulty. |
| Quest milestones | 25–75 | Reaching quest stages, completing objectives |
| Exploration | 10–25 | Discovering locations, finding secrets |
| Social / roleplay | 10–25 | NPC interactions, faction advancement, clever problem-solving |

### Level-Up Grants — Unified Progression Table

Every level, a character gains HP, resource pool increases, and possibly new abilities. This table consolidates all progression from across the mechanics docs into one reference.

| Level | Proficiency | HP Gain | Attribute Points | Archetype Milestone | Spell Tier Access | Technique Slots | Recipe Slots | Notable |
|---|---|---|---|---|---|---|---|---|
| 1 | +1 | Base HP | — | Starting abilities (core set) | Cantrips + Minor | L4 base techniques (not yet) | 3 Basic | Character creation. Core spells/abilities known |
| 2 | +1 | Growth+½CON | — | — | — | — | — | First Training cycles available. Async loop begins |
| 3 | +1 | Growth+½CON | — | New passive or ability upgrade | — | — | — | Companion gains new passive |
| 4 | +1 | Growth+½CON | +2 (any) | **L4 Elective techniques** (martials choose from pool of 4) | Standard | L4 techniques available | — | First martial elective choice |
| 5 | +1 | Growth+½CON | — | **SPECIALIZATION** (choose 1 of 2 paths) | — | — | 8 Trained | Major power spike. Identity-defining fork |
| 6 | +1 | Growth+½CON | — | Specialization ability | — | — | — | — |
| 7 | **+2** | Growth+½CON | — | — | Major | — | — | Proficiency increase |
| 8 | +2 | Growth+½CON | +2 (any) | **L8 Elective techniques** (martials choose from pool of 4) | — | L8 techniques available | — | Second martial elective choice |
| 9 | +2 | Growth+½CON | — | New passive or ability upgrade | — | — | — | — |
| 10 | +2 | Growth+½CON | — | **ARCHETYPE MILESTONE** — major new ability | — | Extra Attack (Warrior, Skirmisher, Paladin) | — | Companion major upgrade |
| 11 | +2 | Growth+½CON | — | Specialization ability | — | — | — | Cantrip damage scales to 3d6 |
| 12 | +2 | Growth+½CON | +2 (any) | — | — | — | 15 Expert | — |
| 13 | +2 | Growth+½CON | — | New passive or ability upgrade | Supreme | — | — | — |
| 14 | **+3** | Growth+½CON | — | — | — | — | — | Proficiency increase |
| 15 | +3 | Growth+½CON | — | **ARCHETYPE MILESTONE** — capstone ability preview | — | — | — | Companion capstone ability |
| 16 | +3 | Growth+½CON | +2 (any) | — | — | — | — | — |
| 17 | +3 | Growth+½CON | — | Specialization ability | — | — | — | Cantrip damage scales to 4d6 |
| 18 | +3 | Growth+½CON | — | — | — | — | — | — |
| 19 | +3 | Growth+½CON | — | — | — | — | — | — |
| 20 | +3 | Growth+½CON | +2 (any) | **ARCHETYPE CAPSTONE** — defining ultimate ability | — | — | Unlimited (Master) | Companion legendary. Total attribute points: +10 from levels |

**Key thresholds:**
- **L5 = identity.** The specialization fork defines who the character becomes. This is the biggest single moment in character progression
- **L10 = power.** Extra Attack, major archetype abilities, companion upgrade. The character feels fundamentally different from L1-9
- **L15 = mastery.** Capstone previews, supreme spells, the character is among the most powerful in Aethos
- **L20 = legend.** The capstone ability, legendary companion, maximum proficiency. The character is a force of nature

**Spell tier unlock by caster level:**

| Spell Tier | Focus Cost | Unlocked At | Examples |
|---|---|---|---|
| Cantrip | 0 | L1 | Arcane Bolt, Sacred Flame, Thorn Whip |
| Minor | 1-2 | L1 | Shield Spell, Heal Wounds, Entangle |
| Standard | 3-4 | L4 | Fireball, Spiritual Weapon, Call Lightning |
| Major | 5-6 | L7 | Chain Lightning, Mass Heal, Earthquake |
| Supreme | 7+ | L13 | Meteor Swarm, Divine Intervention, World Tree |

**Attribute point distribution:**
5 increases of +2 points each (L4, L8, L12, L16, L20) = +10 total attribute points across a full career. With the standard array (16/14/13/12/10/8 = 73 total) plus race bonuses (+3 typical) and attribute points (+10), a L20 character has 86 total attribute points — the primary attribute reaches 20-22 depending on race/allocation choices.

```python
XP_THRESHOLDS = [0, 200, 450, 750, 1050, 1450, 1900, 2400, 2900, 3450,
                 4050, 4650, 5300, 6000, 6750, 7550, 8400, 9300, 10250, 11250]

def level_for_xp(xp: int) -> int:
    for level in range(19, -1, -1):
        if xp >= XP_THRESHOLDS[level]:
            return level + 1
    return 1
```

---

## Async Training System

> **Design principle:** Training cycles are the central progression currency. Everything the player builds between sessions — spells, recipes, techniques, skill advancement — flows through this system. A cycle is not a fixed timer; it's a **variable-duration activity with a midpoint decision** that creates natural engagement hooks.

### What a Training Cycle Is

A Training cycle is one complete unit of async progression work. Starting a cycle kicks off a timer. Partway through, a **decision point** appears (narrated, with a meaningful choice). After the decision, more time passes before completion. The player needs to check in at least once during each cycle.

### Cycle Flow

```
1. LAUNCH — Player starts a Training activity
   ("I want to study Fireball" / "I want to train Cleaving Blow" / "I want to practice Crafting")
   → Engine rolls first-half duration from the activity's time range

2. MIDPOINT DECISION — Timer fires, notification sent
   ("Your study of Fireball has reached a crossroads. The incantation splits two ways —
    do you emphasize power or control?")
   → Player opens app, reads narrated scene, makes a choice
   → Engine rolls second-half duration

3. COMPLETION — Timer fires, notification sent
   ("After hours of focused study, the final syllable clicks into place.
    Fireball is yours — the power variant burns hotter at the cost of a narrower blast.")
   → Counter incremented. Spell/recipe/technique/skill advances.
   → Narrated outcome delivered in Catch-Up feed
```

### Time Ranges

Each half of the cycle rolls independently from the activity's time range. This creates variability — you can't perfectly predict when the decision point or completion will arrive.

| Activity Type | First Half Range | Second Half Range | Total Range | Typical Completions/Day |
|---|---|---|---|---|
| Spell study (cantrip/minor) | 3-5 hours | 2-4 hours | 5-9 hours | 1-2 |
| Spell study (standard/major) | 4-6 hours | 3-5 hours | 7-11 hours | 1 |
| Spell study (supreme) | 5-8 hours | 4-6 hours | 9-14 hours | 1 |
| Recipe study | 3-5 hours | 2-4 hours | 5-9 hours | 1-2 |
| Technique training (base) | 4-6 hours | 3-5 hours | 7-11 hours | 1 |
| Technique training (mentor variant) | 5-7 hours | 4-6 hours | 9-13 hours | 1 |
| Skill practice | 3-5 hours | 2-3 hours | 5-8 hours | 1-2 |
| Crafting project (per async cycle) | 4-6 hours | 3-5 hours | 7-11 hours | 1 |
| Companion errand | 4-8 hours | 3-5 hours | 7-13 hours | 1 |

**Dedicated players** (checking in 2-3 times/day) can complete 2 short cycles per day. **Casual players** (checking in once/day) complete 1 cycle per day. **Occasional players** (every few days) accumulate nothing — cycles don't run in the background without the launch action. This rewards engagement without punishing absence.

### Midpoint Decisions

Every Training cycle includes a midpoint decision. These are not filler — they create small but meaningful variations in what you learn.

**Spell study decisions:**

| Spell Tier | Example Decision | Effect of Choice |
|---|---|---|
| Cantrip/Minor | "The gestures feel natural. Do you practice speed or precision?" | Speed: -0.5 sec cast time (flavor). Precision: +1 to hit on first use per encounter (mechanical micro-bonus) |
| Standard | "The incantation splits two ways — power or control?" | Power: +1 damage die on first cast per long rest. Control: +1 save DC on first cast per long rest |
| Major/Supreme | "The magic resists. Do you push through the resistance or work around it?" | Push: learn 1 cycle faster but gain 1 Resonance on first cast. Work around: normal timing, no Resonance penalty |

**Technique training decisions:**

| Decision | Effect |
|---|---|
| "Your mentor demonstrates two stances. The aggressive one or the defensive one?" | Aggressive: +1 damage on first use per encounter. Defensive: +1 AC when you use this technique |
| "The footwork requires a choice — speed or stability?" | Speed: can use the technique 5 ft further from starting position. Stability: advantage on saves against being moved while using it |

**Skill practice decisions:**

| Decision | Effect |
|---|---|
| "You've hit a plateau. Drill the fundamentals, or experiment with advanced technique?" | Fundamentals: +2 counter toward advancement. Advanced: +1 counter, but next Expert/Master check has advantage |

These micro-bonuses are small enough to not unbalance anything but meaningful enough that the player feels their choices mattered. Over dozens of cycles, the accumulated micro-bonuses give each character a unique fingerprint — two Mages who both learned Fireball might have slightly different versions based on their training decisions.

### Activity Slots

A player can run **one Training activity at a time.** When the current activity completes, they can immediately launch another.

**Exceptions:**
- **Artificer with Portable Lab:** Can run 1 crafting project simultaneously alongside 1 Training activity (the lab handles crafting while you study)
- **Companion errands** run on a separate slot — the companion is doing something while you train. So a player can have 1 Training + 1 companion errand running simultaneously
- **You cannot queue.** No "study Fireball then automatically start studying Shield Spell." Each activity requires a conscious launch action. This is intentional — it brings the player back to the app

### Cycle Counts (How Many Cycles to Learn Something)

These are defined in the relevant system docs but summarized here for reference:

| What You're Learning | Cycles | Where Defined |
|---|---|---|
| Cantrip spell | 1 | `_archetypes` — Spell Acquisition |
| Minor spell (1-2 Focus) | 2 | `_archetypes` — Spell Acquisition |
| Standard spell (3-4 Focus) | 3 | `_archetypes` — Spell Acquisition |
| Major spell (5-6 Focus) | 5 | `_archetypes` — Spell Acquisition |
| Supreme spell (7+ Focus) | 8 | `_archetypes` — Spell Acquisition |
| Basic recipe | 1 | `_crafting` — Recipe Acquisition |
| Trained recipe | 2 | `_crafting` — Recipe Acquisition |
| Expert recipe | 4 | `_crafting` — Recipe Acquisition |
| Master recipe | 6 | `_crafting` — Recipe Acquisition |
| Base technique | 5-6 | `_archetypes` — Martial Mentor System |
| Mentor style variant | 3-4 (additional) | `_archetypes` — Martial Mentor System |
| Skill practice (1 counter increment) | 1 | `_core` — Skill Tier Advancement |

### Implementation

```python
class TrainingActivity:
    id: str                        # "train_spell_fireball"
    player_id: str
    activity_type: str             # "spell_study" | "recipe_study" | "technique_train" | "skill_practice" | "crafting" | "companion_errand"
    target: str                    # What's being learned: "fireball", "anti_hollow_blade", "cleaving_blow"
    cycle_number: int              # Which cycle of multi-cycle learning (1 of 5 for Major spell)
    
    # Timing
    first_half_duration: int       # Rolled from range, in minutes
    second_half_duration: int      # Rolled from range, in minutes
    started_at: datetime
    decision_at: datetime | None   # When midpoint fires (computed: started_at + first_half)
    completes_at: datetime | None  # When cycle completes (computed: decision_at + second_half)
    
    # State
    state: str                     # "running_first_half" | "awaiting_decision" | "running_second_half" | "complete"
    decision_presented: dict | None  # The midpoint choice and options
    decision_made: str | None      # What the player chose
    micro_bonus: dict | None       # The resulting micro-bonus from the decision
    
    # Completion
    result_narration: str          # Pre-rendered narration for Catch-Up feed
    counter_increment: int         # How much this cycle advances the target (usually 1)
```

---

## Companion Errands

> **Design principle:** The companion isn't just a combat partner — they're an agent in the world between sessions. Sending the companion on errands is the third async activity type, running on its own independent slot. The companion returns with a *story*, not just a result.

### Errand Types

| Type | What It Does | Duration Range | Decision Model | Risk Level |
|---|---|---|---|---|
| **Scouting** | Investigate a location or route. Returns with intel: safe/dangerous, who's there, what changed, threats or opportunities | 4-8 hours | End-of-errand only | Medium — companion may return injured |
| **Social** | Talk to NPCs, gather gossip, follow leads. Returns with contacts, rumors, quest hooks, or warnings | 3-6 hours | Midpoint decision possible | Low — social risk only (reputation, not HP) |
| **Acquisition** | Search for a specific resource, item, or material. Returns with the item, a lead on where to find it, or a story about why they couldn't | 4-10 hours | Midpoint decision possible | Low-Medium — depends on what and where |
| **Relationship** | Visit an NPC the player has a relationship with. Returns with news, messages, requests, or disposition updates | 2-4 hours | End-of-errand only | None — social visits are safe |

### Errand Resolution Models

**End-of-errand (Scouting, Relationship):**

The companion leaves, time passes, they return. The return scene is a 30-60 second pre-rendered narrated scene in the Catch-Up feed. The companion tells their story and presents a decision.

```
1. LAUNCH — Player selects errand type + destination/target
   ("Kael, check the northern road" / "Lira, go visit Scholar Emris")
   → Engine rolls duration from type's range

2. IN-FLIGHT — Timer runs. Progress indicators show intermediate narrative states
   ("Kael left an hour ago heading north. No word yet.")
   ("Kael should be reaching the crossroads about now.")

3. COMPLETION — Timer fires, notification sent
   ("Kael returned from the northern road. He looks worried.")
   → Pre-rendered narration scene plays in Catch-Up feed
   → Decision presented: what to do with the information
```

**Midpoint-decision (Social, Acquisition):**

The companion encounters a fork in the road and checks in. Same structure as Training midpoints.

```
1. LAUNCH — Player selects errand type + target
   ("Tam, find me some hollow-ward herbs" / "Lira, ask around about the missing patrol")
   → Engine rolls first-half duration

2. MIDPOINT — Timer fires, notification sent
   ("Tam found the herbs but also spotted razorwing feathers near the cliff.
    Stick with herbs or grab the feathers instead?")
   → Player makes decision in app
   → Engine rolls second-half duration

3. COMPLETION — Timer fires, notification sent
   → Pre-rendered narration scene with results + follow-up decision
```

### The Return Scene

Every errand completion delivers a narrated scene. This is the companion's moment — they're telling you what happened, in character, with personality.

**Kael returns from a scout:** *"The northern road is worse than we thought. The barricade's holding but barely. I ran into someone at the crossroads — an Aelindran woman asking questions about the ruins. She wouldn't give her name."* Decision: Investigate the tracks next session / Send Kael to follow her.

**Lira returns from a social errand:** *"The merchant's cousin left town two days ago. But his neighbor — she knows something. She got nervous when I mentioned the ruins. She'll talk, but only to you. And only at the tavern, after dark."* Decision: Meet the contact next session / Send Lira to press for more.

**Tam returns from acquisition:** *"Got your herbs. Also got a black eye — a forager from the Thornwatch claimed that patch was theirs. I told them where they could put their claim."* Decision: Keep the herbs (Thornwatch rep -1) / Return them with an apology (Thornwatch rep preserved, herbs lost).

**Sable returns from a scout:** The DM narrates Sable's behavior. *"Sable returns agitated. She drops a torn piece of cloth at your feet — dark fabric, not local. She growls at the northern path and refuses to go near it again."* Decision: Investigate the cloth / Send Sable to the southern route instead.

### Companion Risk

Some errands carry risk based on errand type and destination danger level:

| Destination Danger | Scouting Risk | Social Risk | Acquisition Risk | Relationship Risk |
|---|---|---|---|---|
| Safe (settlements) | None | None | None | None |
| Moderate (roads, frontier) | 10% injured | None | 10% injured | None |
| Dangerous (Ashmark edge, deep forest) | 25% injured, 5% emergency | None | 20% injured | N/A (companions don't relationship-visit in dangerous areas) |
| Extreme (deep Hollow territory) | 40% injured, 15% emergency | N/A | N/A | N/A |

**Injured:** The companion returns with reduced HP (50% max) at the start of the next sync session. Heals after one long rest. The DM narrates the injury: "Kael's favoring his left side. He doesn't want to talk about it."

**Emergency:** The companion gets into trouble that becomes a **side quest**. They send an urgent notification: "Kael hasn't returned. He was expected back hours ago." The player's next sync session opens with the option to search for the companion. This creates organic content from the async system — a rescue mission triggered by a risky errand.

### Companion-Specific Errand Bonuses

Each companion has natural strengths that affect errand outcomes:

| Companion | Scouting Bonus | Social Bonus | Acquisition Bonus | Relationship Bonus |
|---|---|---|---|---|
| **Kael** | Reduced injury risk (veteran survival instincts) | Neutral | Good at finding martial supplies | NPCs trust him — disposition shifts +1 |
| **Lira** | Identifies magical anomalies during scouts | Better social intelligence (reads people well) | Finds arcane/scholarly items more reliably | Academic NPCs respond better |
| **Tam** | Covers more ground (faster, wider area scouted) | Charismatic but unreliable (sometimes offends) | Good in wilderness, poor in cities | Emotional connections — NPCs open up more |
| **Sable** | Detects Hollow corruption during scouts | N/A (Sable can't talk to people) | Finds natural/primal materials via scent | N/A (Sable visits don't work socially) |

---

## Async Activity Concurrency Model

Three independent activity slots run simultaneously:

| Slot | Activity Type | Limit | Notes |
|---|---|---|---|
| **Training Slot** | Spell study, recipe study, technique training, skill practice | 1 at a time | Core progression currency. See Async Training System above |
| **Crafting Slot** | Crafting projects (from recipe system) | 1 at a time | Consumes materials. See `game_mechanics_crafting.md` — Async Crafting |
| **Companion Slot** | Scouting, social, acquisition, relationship errands | 1 at a time | Companion unavailable for sync combat while on errand |

**Artificer exception:** Artificer with Portable Lab can run crafting on the Training slot (lab handles it), freeing the Crafting slot for a second project. Maximum 2 crafting + 1 errand for an Artificer.

**No queuing.** Each activity requires a conscious launch action. When one completes, the player must open the app and start the next. This is intentional — it creates engagement hooks and brings the player back.

**Companion availability:** A companion on an errand is **not available for sync combat** until the errand completes. If the player enters a voice session while the companion is away, the DM narrates the absence: "Kael's still on the northern road. You're on your own for now." This creates a real tradeoff — do you send the companion for intel, or keep them available for combat? Short errands (2-4 hours) minimize this risk; long scouting missions (8+ hours) are a deliberate gamble.

**The 3-4 concurrent baseline:** The system gently encourages running all three slots. After resolving a crafting project: "While the next one's in the forge, want to send Kael to look into something?" After a training cycle: "Your mentor suggests practicing while Kael scouts ahead." The goal is 3 concurrent activities as the natural state — each with its own timer, each contributing to the next sync session.

**All outcomes are pre-rendered.** Narration is generated on simulation ticks, synthesized to audio, and stored. The player's check-in plays back pre-rendered content — no live voice pipeline, no real-time LLM cost. A full check-in with 3 resolved activities costs ~$0.01 in LLM + TTS.

---

## Combat, Conditions & Death

> **Extracted to `game_mechanics_combat.md`.** Dramatic Dice System, phase-based combat, action economy, initiative, all status effects (including Prone, Grappled, Restrained, Paralyzed, Concentration), Resting, death and dying (Fallen, death saves, Hollowed Death, Mortaen's domain, escalating cost engine, resurrection), social encounter resolution, travel and exploration (3 modes, encounters, navigation, exhaustion, camping), and gathering/resource discovery (skill-gated, regional tables, fixed nodes).

---

## Character Creation

> **Design principle:** Character creation is a conversation with the DM, not a form. Every choice is made through voice interaction. The player makes 3-4 narrative choices; the system computes everything else.

### Creation Flow (5 Steps)

**Step 1 — Awakening (Race)**

The DM narrates the player into consciousness through sensory details:

> *"You open your eyes. The world sharpens around you. What do you see when you look at your hands?"*

The player is offered descriptions — not stat blocks — that convey the feel of each race: the warmth of dense Draethar hands, the tingle of Elari awareness, the mineral solidity of Korath skin, the Vaelti nerve-alive nimbleness, the Thessyn sense of adaptability, the Human steady determination. The DM elaborates on whatever interests the player. Choice confirmed through conversation.

Each race provides: +2 to one attribute, +1 to another, one non-Resonance racial ability, and a Resonance trait (defined in `game_mechanics_magic.md`). Race stat blocks are detailed in the Racial Traits section below.

**Step 2 — Calling (Archetype)**

The DM guides through instinct, not a class list:

> *"When danger comes — and it always comes — what is your instinct? To fight? To understand? To protect? To slip away unseen?"*

The answer narrows to a category (Martial, Arcane, Primal, Divine, Shadow, Support), then the DM offers 2-3 options within it: "You fight with steel — are you the one who hits hardest, the one who never falls, or the one who's never where they expect?" This is the most important choice — it determines HP, resources, saves, skills, and ability model.

**Step 3 — Attributes (Standard Array)**

**Standard array: 16, 14, 13, 12, 10, 8.** Assign to the 6 attributes. No dice rolling — voice-first play needs deterministic, comparable starting points.

The DM guides based on archetype: "As a Warrior, strength and constitution serve you best. Where would you place your highest score?" The engine validates assignments. Race modifiers apply after.

**Quick option:** "Use the recommended spread for my archetype." The engine assigns the optimal array automatically. For players who don't want to engage with numbers.

**Recommended arrays by archetype category:**

| Category | Primary (16) | Secondary (14) | Tertiary (13) | Fourth (12) | Fifth (10) | Dump (8) |
|---|---|---|---|---|---|---|
| Martial | STR | CON | DEX | WIS | CHA | INT |
| Arcane | INT | DEX | CON | WIS | CHA | STR |
| Primal | WIS | CON | STR | DEX | INT | CHA |
| Divine | WIS | CON | CHA | STR | DEX | INT |
| Shadow | DEX | CHA | CON | INT | WIS | STR |
| Support | CHA | DEX | WIS | CON | INT | STR |

**Step 4 — Devotion (Divine Patron)**

> *"Do you pray? And if so, who answers?"*

The DM briefly introduces gods relevant to the player's archetype and background. A Warrior hears about Kaelen (courage), Valdris (justice), Thyra (fury). A Mage hears about Veythar (knowledge), Aelora (craft), Zhael (fate). The player chooses one — or chooses Unbound (no patron).

**Deferred choice:** The player can say "I don't know yet." Mechanically: they start as Unbound with a flag `patron_deferred: true`. They gain the Unbound passive (Veil Clarity — know exact Resonance number) but can switch to any patron later through a narrative commitment scene. Once committed, the Unbound passive is replaced by the patron's Layer 1 gift. This can only happen once — you can defer, then commit, but you can't switch patrons after committing.

**Step 5 — Identity (Name)**

> *"And what do they call you?"*

The player names their character. The DM acknowledges it with weight — this is the Awaken moment. The character sheet is complete. The game begins.

> *"You open your eyes. The light is wrong. Something has changed. [Name] — do you remember what happened?"*

### Behind the Scenes (Not Narrated)

These are computed automatically from the player's narrative choices:

**Culture and starting region** — Auto-derived from race + archetype + patron. The system selects the most narratively coherent starting culture and region. A Drathian Warrior of Kaelen → Drathian Steppe. An Elari Seeker of Veythar → Aelindran Diaspora in the Accord. A Human Cleric of Orenthel → Sunward Accord. For ambiguous combinations, defaults to the Sunward Accord (most cosmopolitan, any combination works). The player experiences their culture through play, not through a creation menu.

**Starting equipment** — Assigned automatically from archetype category. No shopping at creation.

| Category | Armor | Weapon Choice | Other | Gold |
|---|---|---|---|---|
| Martial (Warrior, Guardian, Skirmisher) | Chain shirt + shield OR chain mail | Longsword + shield OR greatsword | Explorer's pack (backpack, bedroll, rations ×5, torch ×3, rope, waterskin) | 10 sp |
| Arcane (Mage, Artificer, Seeker) | None (robes) | Staff OR dagger + light crossbow | Scholar's pack (backpack, ink, quill, parchment, arcane focus, rations ×3) | 10 sp |
| Primal (Druid, Beastcaller, Warden) | Hide armor | Staff + shield (non-metal) OR scimitar | Explorer's pack + herbalism kit | 10 sp |
| Divine (Cleric, Paladin, Oracle) | Chain shirt + shield (Cleric/Paladin) OR leather (Oracle) | Mace OR warhammer (Cleric/Paladin). Staff (Oracle) | Priest's pack (backpack, holy symbol, prayer beads, rations ×5, healer's kit) | 10 sp |
| Shadow (Rogue, Spy) | Leather armor | Short sword + daggers ×2 OR rapier | Burglar's pack (backpack, thieves' tools, dark cloak, rations ×3) | 10 sp |
| Support (Bard, Diplomat) | Leather armor | Rapier OR longsword (Bard). Dagger only (Diplomat) | Entertainer's pack (instrument or writing kit, fine clothes, rations ×3) | 15 sp |

**Starting skills** — Already defined per archetype (3-5 skills at Trained). No additional choices.

**Starting spells/recipes** — Core spells known automatically. Elective slots filled at creation: L1 casters start knowing 1 elective cantrip + 1 elective minor spell (representing pre-game training). Crafters start knowing 2 Basic recipes.

**Companion assignment** — Triggered after creation completes. System selects the best companion archetype based on player's race, archetype, patron, and starting culture. The companion finds the player organically during the opening normalcy phase — not through a selection screen.

### What Character Creation Does NOT Include

- **No alignment.** Patron choice and player behavior define morality
- **No backstory questionnaire.** The Awaken scene implies disorientation — backstory emerges through play and collaborative conversation with the DM during the Identity step
- **No shopping.** Starting equipment is fixed. The economy kicks in from session 2
- **No feat selection.** Archetype abilities, electives, specializations, and patron layers provide all customization
- **No multiclassing.** The Bard's cross-source access and Paladin's martial-divine hybrid cover the "two things" fantasy within single frameworks
- **No culture selection by the player.** Culture is auto-derived. The player discovers their culture through play

### Racial Traits

Each race provides attribute bonuses (applied after standard array assignment), a racial ability, and a Resonance trait. Resonance traits are defined in detail in `game_mechanics_magic.md` — Racial Resonance Integration.

#### Human (Thael'kin)

> *Adaptability. No innate magical affinity, no physical extremes, but an ability to thrive anywhere and learn anything.*

**Attributes:** +1 to any TWO attributes (player's choice). Humans are the only race with flexible attribute bonuses.
**Speed:** 30 ft | **Size:** Medium
**Racial ability — Versatile Heritage:** Start with one extra skill at Trained (player's choice from any skill). Humans learn faster than anyone.
**Resonance trait — Adaptive Resonance:** Resonance decays at 2/round instead of 1. Enables aggressive "dip and recover" casting.

#### Elari

> *Tall, long-lived, innately sensitive to the fabric of reality. They feel the Veil the way others feel temperature.*

**Attributes:** +2 INT, +1 WIS
**Speed:** 30 ft | **Size:** Medium
**Racial ability — Darkvision (60 ft).** Elari see in dim light as if bright, and darkness as dim light. Additionally: advantage on Arcana checks related to Veil phenomena and magical identification.
**Resonance trait — Veil-Sense:** Passively aware of local Resonance state. DM tells Elari their current Resonance level without asking. At Expert Arcana: sense Resonance of nearby casters. At Master: sense regional Veil integrity.

#### Korath

> *Broad, dense, stone-touched. Skin with a mineral quality, denser bones, an innate sense of geological structure.*

**Attributes:** +2 CON, +1 STR
**Speed:** 25 ft (shorter but unshakeable) | **Size:** Medium-Large
**Racial ability — Stoneblood Endurance.** Resistance to poison damage. Advantage on saves vs Poisoned condition. When you take the Defend declaration in combat, gain +3 AC instead of +2 (your body is harder to damage when braced).
**Resonance trait — Earth-Anchored:** -1 Resonance from all Primal spells. Underground: -2. Korath Druids and Wardens underground are the safest casters in Aethos.

#### Vaelti

> *Slight, quick, with senses sharper than any other race. Hyper-awareness evolved in dangerous environments.*

**Attributes:** +2 DEX, +1 WIS
**Speed:** 35 ft (Vaelti are fast) | **Size:** Medium (slight build)
**Racial ability — Keen Senses.** Advantage on all Perception checks. Cannot be surprised unless magically compelled (Vaelti senses catch everything). In voice play: the DM gives Vaelti players extra ambient audio information — approaching footsteps, hidden breathing, distant sounds others miss.
**Resonance trait — Hyper-Awareness:** 1-round advance warning before Hollow Echo effects manifest. Advantage on saves against Hollow Echo. The party's early warning system against Overreach consequences.

#### Draethar

> *Large, powerful, with controlled internal heat. Not fire-breathers, but they run hot — literally.*

**Attributes:** +2 STR, +1 CHA
**Speed:** 30 ft | **Size:** Medium-Large
**Racial ability — Inner Furnace.** Resistance to cold damage. Immune to environmental cold effects (blizzards, freezing water). Unarmed strikes deal 1d4 + STR fire damage (the heat in their fists). Intimidation checks gain advantage when the Draethar is visibly angry (heat shimmer, glowing skin).
**Resonance trait — Inner Fire (Active, 1/encounter).** Burn Resonance into HP: reduce Resonance by 3, take 1d6 fire damage (to self). A pressure valve for Draethar casters who push too hard.

#### Thessyn

> *Fluid, adaptable. Their bodies slowly attune to their environment over time — environmental evolution in miniature.*

**Attributes:** +1 to any THREE attributes (player's choice, max +1 each). Thessyn are the other flexible race, but spread thinner than Humans.
**Speed:** 30 ft | **Size:** Medium
**Racial ability — Deep Adaptation.** Every 10 sessions spent primarily in one environment, the Thessyn gains a minor permanent adaptation (DM narrates the physical change):

| Environment | Adaptation |
|---|---|
| Underground | Darkvision 30 ft. Advantage on Navigation checks underground |
| Coastal/aquatic | Hold breath 10 min. Swimming speed 20 ft |
| Forest/wilderness | +5 ft movement in natural terrain. Advantage on Stealth in forests |
| Urban/scholarly | +1 to INT checks. One extra known recipe or spell (free slot) |
| Ashmark/Hollow-adjacent | +1 to saves vs Hollow effects. Resistance to necrotic damage |

Thessyn can hold up to 3 adaptations. A 4th replaces the oldest. The DM narrates the shift: "Your fingers have grown longer since your months in the archives."

**Resonance trait — Deep Adaptation (Evolving).** Resonance behavior shifts with environment. In a region for 5+ sessions: -1 Resonance for spells aligned with that region's dominant magic source. A Thessyn Mage who lives in the Thornveld gradually attunes to Primal energy, reducing Primal Resonance even though they cast Arcane.

---

## Design Decisions Log

> **Extracted to `game_mechanics_decisions.md`.** All 72 locked design decisions with full reasoning. Decisions 1-23: core systems. 24-29: bestiary. 30-35: NPCs. 36-43: crafting. 44-53: combat, creation, death, training. 54-57: companions. 58-61: errands/concurrency. 62-63: races/progression. 64-67: social encounters. 68: dramatic dice. 69-71: travel and gathering. 72: economy reconciliation.
