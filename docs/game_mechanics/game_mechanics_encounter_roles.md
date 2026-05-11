# Divine Ruin — Game Mechanics: Encounter Roles

> **Purpose:** Canonical definition of encounter roles — the system that scales creatures from fodder to campaign-defining threats. Encounter roles modify base creature stat blocks (defined in `game_mechanics_bestiary.md`), loot output (feeding `game_mechanics_economy.md`), XP rewards (feeding `game_mechanics_core.md`), and DM narration behavior.
>
> **Design principle:** The bestiary defines *what* a creature is. Encounter roles define *how* it appears in a given fight. A Grey Wolf is always a Grey Wolf — but three wolves screening for an alpha is a different encounter than four wolves hunting as equals. Roles are assigned per-encounter by the encounter builder (or the DM), not baked into the creature definition.
>
> **Related docs:** `game_mechanics_bestiary.md` (base stat blocks, loot tables), `game_mechanics_combat.md` (phase-based combat, action economy), `game_mechanics_economy.md` (material sell values, currency drops, merchant pricing), `game_mechanics_core.md` (XP and progression)

---

## Role Definitions

Five encounter roles exist. Every creature in every encounter is assigned exactly one role.

### Minion

**Design intent:** Expendable creatures that create threat through numbers, not individual power. Minions exist so the DM can throw cinematic swarms at the player without each creature requiring full tactical resolution or flooding the economy with loot. A fight against eight Shadelings pouring through a Veil breach should feel overwhelming and desperate — but the player shouldn't walk away with eight creatures' worth of materials.

**Narrative identity:** The weakest of their kind. Green recruits, juveniles, stragglers, the desperate and underfed. The DM conveys this through description, never by using the word "minion."

**Mechanical identity:** Dies fast. Hits soft. No tricks. Dangerous only in groups.

---

### Standard

**Design intent:** The baseline. When a creature appears in the bestiary with a stat block, that stat block *is* the Standard role. Standard requires no modification — it is the identity function. Every other role is defined as a deviation from Standard.

**Narrative identity:** A typical specimen of its kind. A wolf. A bandit. A Mawling. Nothing more, nothing less.

**Mechanical identity:** Exactly as written in the bestiary.

---

### Elite

**Design intent:** A tougher, more dangerous variant of a base creature. Elites appear when the encounter needs a creature that's more threatening than Standard but doesn't warrant a full Boss treatment. The alpha wolf. The veteran bandit. The Mawling that's fed recently and grown stronger. Elites are the bestiary's existing "elite variant" reference, now formalized.

**Narrative identity:** Visibly superior to others of its kind. Larger, scarred, better equipped, more confident. The DM highlights the difference: "One of them is bigger than the rest — moves differently. That one's seen real fighting."

**Mechanical identity:** Tougher, hits harder, has enhanced abilities. Still recognizably the same creature.

---

### Boss

**Design intent:** The encounter capstone. One per encounter maximum. A Boss is the creature the fight revolves around — killing it ends the encounter or fundamentally changes it. Bosses have a signature ability that Standard creatures of that type don't possess, making the fight tactically distinct. The bandit captain who rallies their crew. The alpha Mawling that commands lesser Hollow.

**Narrative identity:** Obviously the leader or apex threat. The DM introduces them with weight: "Behind the line of bandits, a woman in scarred plate watches you with cold appraisal. She hasn't drawn her weapon yet."

**Mechanical identity:** Significantly tougher, hits harder, has a unique signature ability, and gets a legendary action (one extra action per round). Defeating the Boss often triggers morale breaks in remaining enemies.

---

### Named

**Design intent:** Campaign-defining unique creatures with bespoke stat blocks. The Choir, The Still, The Architect. Named creatures are not derived from a base creature — they *are* the base. Their stat blocks already exist in the bestiary as one-of-a-kind entries. The encounter role system does not modify Named creatures; it simply acknowledges them as a category.

**Narrative identity:** Unique. The DM has specific narration cues authored per creature. These are the fights players remember for years.

**Mechanical identity:** As written in the bestiary. No role modifiers apply.

---

## Combat Stat Modifiers

All modifiers are applied to the base creature stat block from `game_mechanics_bestiary.md`. Standard is the identity — no changes. Named creatures are exempt (they have bespoke stat blocks).

### Modifier Table

| Stat | Minion | Standard | Elite | Boss |
|---|---|---|---|---|
| **HP** | 50% (round down) | 100% | 150% (round up) | 200% |
| **AC** | -1 | Base | +1 | +2 |
| **Damage** | 75% (round down, min 1) | 100% | 125% (round up) | 150% (round up) |
| **Attack bonus** | Base | Base | +1 | +2 |
| **Save DCs** | -1 | Base | +1 | +2 |
| **Speed** | Base | Base | Base | Base |
| **Saves** | Base | Base | Base | +1 to proficient saves |

### Ability Modifications

| Role | Passive Abilities | Active Abilities | Signature Ability | Legendary Action |
|---|---|---|---|---|
| **Minion** | Retained (simplified where possible) | Removed. Minions use basic attacks only | None | None |
| **Standard** | As written | As written | None | None |
| **Elite** | As written | Enhanced: +1 use per encounter, OR expanded effect (see Enhancement Rules below) | None | None |
| **Boss** | As written | Enhanced (same as Elite) | Yes — one unique ability (see Signature Ability Design below) | Yes — 1 per round |

### Elite Enhancement Rules

When promoting a Standard creature to Elite, enhance its existing active abilities using one of these patterns. Choose the one that best fits the creature's tactical identity:

**Frequency increase:** An ability usable 1/encounter becomes 2/encounter. Simple, always works, preferred when the ability is already strong.

**Expanded effect:** The ability gains additional mechanical weight. Examples:
- Bandit's Dirty Fighting (blind 1 round) → Elite: blind 1 round + disadvantage on next attack even after blind clears
- Mawling's Rending Bite (bonus damage on grappled target) → Elite: rending damage applies to any target below max HP, not just grappled
- Wolf's Pack Tactics (advantage with ally adjacent) → Elite Alpha: Pack Tactics grants advantage to *all* allied wolves within 10 ft when the alpha attacks, not just the alpha itself

**Do not stack both.** One enhancement per ability. If the creature has multiple actives, enhance only the most tactically interesting one — the one that makes the player think.

### Boss Signature Ability Design

Every Boss gets one signature ability that its Standard form does not have. This ability should:

1. **Change the tactical calculus of the fight.** The player must account for it. A Boss without a signature is just a sponge with more HP.
2. **Be telegraphed.** The DM narrates a tell before the signature fires ("The captain raises her blade and shouts something in Keldaran—"). The player gets a chance to react (use a reaction, reposition, interrupt with a declaration enhancer).
3. **Fire once per encounter by default.** Some signatures may recharge (recharge 5-6 on d6 at start of Boss's phase), but once-per-encounter is the safe default.
4. **Be derivable from the creature's identity.** A bandit captain rallies troops. A dire bear alpha triggers a territorial rage. A Hollow Knight channels corruption. The signature should feel *inevitable* — "of course it does that."

### Boss Legendary Action

Bosses get 1 legendary action per round, taken at the end of any other creature's turn (or the player's turn). The legendary action is always one of:

- **Extra attack** (single basic attack at base damage, no specials)
- **Move** (up to half speed without provoking reactions)
- **Use an active ability** (if it has uses remaining)

One legendary action per round, not per turn. This gives the Boss tactical flexibility without action economy dominance.

---

## Loot Modifiers

All modifiers apply to the creature's base loot table as defined in `game_mechanics_bestiary.md`. Standard uses the table as-is.

### Loot Modifier Table

| Role | Drop Chance Modifier | Quantity Modifier | Currency Drop | Unique/Bonus Loot |
|---|---|---|---|---|
| **Minion** | ×0.5 (round down, min 5%) | -1 per entry (min 1) | None | None |
| **Standard** | As written | As written | Base (see Currency Drop Rules) | None |
| **Elite** | +25% (cap 100%) | +1 per entry | 1.5× base (round up) | None |
| **Boss** | All drops 100% (guaranteed) | +50% (round up) | 2× base + bonus (see below) | One bonus item from context loot pool |
| **Named** | As written (bespoke tables, already 100%) | As written | As written (bespoke) | Unique items per creature |

### Currency Drop Rules

Not every creature carries money. Currency drops are determined by creature category, then modified by encounter role.

| Creature Category | Drops Currency? | Base Amount | Narrative Justification |
|---|---|---|---|
| **Beasts** | No | — | Animals don't carry coin |
| **Humanoids** | Always | Tier × 1d6 sp | Pocket money, loot from prior victims |
| **Hollow — Drift** | No | — | Shadelings dissolve, leaving nothing monetary |
| **Hollow — Rend+** | 15% chance | Tier × 2d6 sp | Absorbed from victims. Found in residue |
| **Hollow — Named** | Set per creature | See bestiary | Unique, often non-monetary (research value) |
| **Constructs** | No | — | Machines don't carry coin |
| **Undead** | 25% chance | Tier × 1d4 sp | Grave goods, what they carried in life |

**Boss currency bonus:** In addition to 2× the base currency roll, Bosses drop a guaranteed bonus based on encounter tier:

| Encounter Tier | Boss Currency Bonus |
|---|---|
| 1 | +5 sp |
| 2 | +15 sp |
| 3 | +40 sp |
| 4 | +100 sp |

**Boss bonus item:** The Boss drops one additional item from a *context loot pool* — a small table defined by the encounter location or quest, not the creature type. A bandit captain in a mountain pass might drop a stolen merchant's ledger or a key to a hidden cache. A dire bear alpha in a corrupted forest might have a Thornwatch badge embedded in its hide from a previous victim. This item is authored per encounter or procedurally generated by the DM from location context. It connects the loot to the story, not just the creature.

### Material Sell Values

When materials are sold to merchants, base values are determined by material category and tier. These are *base merchant values* — actual price received is modified by disposition and faction reputation (see Merchant Pricing Formula in `game_mechanics_economy.md`).

| Material Category | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---|---|---|---|
| Hides / pelts | 1-2 sp | 5-8 sp | 15-25 sp | 50+ sp |
| Bones / fangs / chitin | 5 cp - 1 sp | 2-5 sp | 8-15 sp | 30-50 sp |
| Meat / organs | 2-5 cp | 1-3 sp | 5-10 sp | 15-30 sp |
| Venom / glands | 2-3 sp | 5-10 sp | 15-30 sp | 50-100 sp |
| Fiber / silk | 1-2 sp | 3-6 sp | 10-20 sp | 40-80 sp |
| Hollow residue | 5-15 sp | 10-25 sp | 50-100 sp | 200-500 sp |
| Arcane components | 3-5 sp | 10-20 sp | 30-75 sp | 100-300 sp |
| Divine materials | 5-10 sp | 15-30 sp | 50-100 sp | 150-400 sp |
| Named fragments | — | — | — | 500 sp (fixed) |

**Sell value is always lower than crafting value.** A wrack core sells to a scholar for 50-100 sp, but *using* it to craft an Anti-Hollow Blade produces a weapon worth far more. This is intentional — the crafting loop should always be more economically rewarding than selling raw materials.

**Buyer specialization:** Scholars pay full price (or premium) for Hollow research materials. Alchemists pay full price for venom and reagents. General merchants buy anything but at 50-75% of category value. The DM narrates this naturally: "Grimjaw will take the pelts, but for the venom sacs you'd want to find an alchemist."

---

## XP Modifiers

XP per creature is defined in the bestiary. Encounter roles modify that value.

| Role | XP Modifier | Rationale |
|---|---|---|
| **Minion** | 50% | Easier to kill, less rewarding |
| **Standard** | 100% | Baseline |
| **Elite** | 150% | Tougher fight, better reward |
| **Boss** | 200% | Encounter capstone, major challenge |
| **Named** | As written | Bespoke XP values already account for difficulty |

**Encounter XP is the sum of all creature XP.** No bonus for the encounter itself — the difficulty is captured in the per-creature role modifiers. This keeps XP math simple and predictable for the progression system.

---

## Encounter Budget System

The encounter builder (whether algorithmic or DM-driven) uses a point-buy budget to construct encounters. This replaces the bestiary's current encounter scaling table with a more flexible system while producing equivalent outcomes.

### Budget Points

Every creature in an encounter costs budget points based on its role:

| Role | Budget Cost |
|---|---|
| Minion | 0.5 |
| Standard | 1.0 |
| Elite | 2.0 |
| Boss | 4.0 |
| Named | — (encounter is built around them; no budget applies) |

### Encounter Difficulty Budgets

Budget scales with player level and desired difficulty. The companion (at 75% player effectiveness) is already factored into these budgets — they assume 1 player + 1 companion.

| Player Level | Standard Encounter | Tough Encounter | Boss Encounter |
|---|---|---|---|
| 1-2 | 2.0 | 3.0 | 4.0 |
| 3-4 | 3.0 | 4.5 | 5.0 |
| 5-8 | 4.0 | 6.0 | 7.0 |
| 9-14 | 5.0 | 7.5 | 9.0 |
| 15-20 | 6.0 | 9.0 | 11.0 |

### Budget Allocation Rules

1. **Maximum one Boss per encounter.** A Boss encounter means one Boss creature supported by lesser roles.
2. **Minions require at least one non-Minion.** A fight of *only* Minions has no tactical anchor — it's a chore, not a fight. At least one Standard or higher must be present to give the encounter shape.
3. **Creature tier must be appropriate to player level.** Budget constrains *composition*, not tier selection. A L1 player shouldn't face Tier 3 creatures regardless of budget — the encounter scaling table in the bestiary still governs tier appropriateness.
4. **Named encounters ignore budget.** Named creatures define the encounter by their nature. The DM builds the supporting cast narratively, not mathematically.

### Example Budget Compositions

**Standard encounter, L3 player (budget 3.0):**
- 6 Minions (3.0) — a wolf pack ambush
- 3 Standards (3.0) — three bandits at a chokepoint
- 1 Elite + 2 Minions (3.0) — alpha wolf with two yearlings
- 1 Elite + 1 Standard (3.0) — veteran bandit and their partner

**Tough encounter, L7 player (budget 6.0):**
- 1 Boss + 4 Minions (6.0) — bandit captain with green recruits
- 2 Elites + 4 Minions (6.0) — two veteran bandits with gang
- 3 Elites (6.0) — three experienced Mawlings hunting together
- 1 Boss + 1 Standard + 2 Minions (6.0) — Hollowed Knight with corrupted soldiers

**Boss encounter, L12 player (budget 9.0):**
- 1 Boss + 1 Elite + 3 Standards (9.0) — bandit warlord, lieutenant, and soldiers
- 1 Boss + 2 Elites + 2 Minions (9.0) — Wrack-tier Hollow with Rend support
- 1 Boss + 10 Minions (9.0) — swarm encounter with a central threat

---

## Worked Examples

### Example 1: Bandit (Humanoid, Tier 1)

**Base stat block** (from bestiary): Level 2 | HP 16 | AC 13 | Short Sword +4 (1d6+2) | Light Crossbow +4 (1d8+2) | Dirty Fighting 1/encounter (Blind 1 round, DEX DC 12) | XP 50

---

**Minion Bandit — "Green Recruit"**

*"Two of them can barely hold their swords straight. Farm kids with stolen leather and bad ideas."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 8 | 16 × 0.5 |
| AC | 12 | 13 - 1 |
| Short Sword | +4, 1d4+1 (3 avg) | Damage: (1d6+2 avg 5.5) × 0.75 ≈ 4 → 1d4+1 (3.5 avg) |
| Dirty Fighting | Removed | Minions lose active abilities |
| XP | 25 | 50 × 0.5 |

**Loot:**

| Drop | Qty | Chance | Derivation |
|---|---|---|---|
| Short Sword | 1 | 50% | Base 100% × 0.5 |
| Leather scraps | 1 | 50% | Base 100% × 0.5 |
| Currency | — | None | Minions drop no currency |

---

**Standard Bandit**

*"A highway robber. Lean, watchful, weapon in hand. This one knows what they're doing."*

Exactly as written in the bestiary. No modifications.

**Loot:**

| Drop | Qty | Chance |
|---|---|---|
| Short Sword | 1 | 100% |
| Leather armor (worn) | 1 | 100% |
| Currency | 1d6 sp | 100% (humanoid, Tier 1 × 1d6) |

---

**Elite Bandit — "Veteran Highwayman"**

*"Scarred across the jaw. Moves like a soldier — this one didn't start on the road. Something put them here."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 24 | 16 × 1.5 |
| AC | 14 | 13 + 1 |
| Short Sword | +5, 1d6+3 (6 avg) | +1 hit; damage: (5.5) × 1.25 ≈ 7 → 1d6+3 (6.5 avg) |
| Save DCs | 13 | 12 + 1 |
| Dirty Fighting | Enhanced: 2/encounter | Frequency increase |
| XP | 75 | 50 × 1.5 |

**Loot:**

| Drop | Qty | Chance |
|---|---|---|
| Short Sword | 1 | 100% |
| Leather armor (worn, good condition) | 1 | 100% |
| Currency | 1d6 sp × 1.5 (round up) | 100% |
| Bonus: personal item | 1 | 25% (base 0% + 25% Elite bonus) |

---

**Boss Bandit — "Road Captain"**

*"She sits on a fallen log behind the line, eating an apple. Hasn't drawn her weapon. Doesn't need to — the six around her jump when she speaks."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 32 | 16 × 2.0 |
| AC | 15 | 13 + 2 |
| Short Sword | +6, 1d8+3 (7 avg) | +2 hit; damage: (5.5) × 1.5 ≈ 8 → 1d8+3 (7.5 avg). Weapon upgraded to reflect status |
| Save DCs | 14 | 12 + 2 |
| Dirty Fighting | Enhanced: 2/encounter | Same as Elite |
| **Signature: Rally** | 1/encounter | All allied bandits within 30 ft gain +2 to attack rolls and advantage on saves vs. fear for 2 rounds. Telegraphed: "She stands, draws her blade, and *shouts.*" |
| **Legendary Action** | 1/round | Extra attack, half-speed move, or Dirty Fighting (if uses remain) |
| XP | 100 | 50 × 2.0 |

**Loot:**

| Drop | Qty | Chance |
|---|---|---|
| Quality short sword (or longsword) | 1 | 100% (guaranteed) |
| Studded leather armor | 1 | 100% (guaranteed) |
| Currency | (1d6 × 2) + 5 sp | 100% (2× base + Tier 1 Boss bonus) |
| Bonus item (context loot) | 1 | 100% (guaranteed). Example: stolen merchant's manifest, key to a cache, coded letter from a faction contact |

---

### Example 2: Grey Wolf (Beast, Tier 1)

**Base stat block** (from bestiary): Level 1 | HP 11 | AC 12 | Bite +4 (1d6+2, DC 11 STR or prone) | Pack Tactics, Keen Senses | XP 25

---

**Minion Wolf — "Yearling"**

*"Smaller than the others. Ribs showing. It snarls, but there's more fear than fury in it."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 5 | 11 × 0.5 (rounded down) |
| AC | 11 | 12 - 1 |
| Bite | +4, 1d4+1 (3 avg) | Damage: (1d6+2 avg 5.5) × 0.75 ≈ 4 → 1d4+1. Prone effect removed (simplified) |
| Pack Tactics | Retained | Passive, kept for minions |
| XP | 12 | 25 × 0.5 (rounded down) |

**Loot:**

| Drop | Qty | Chance |
|---|---|---|
| Wolf pelt (poor quality) | 1 | 50% | 
| Wolf fangs | 1 | 50% |
| Wolf meat | 1 | 50% |
| Currency | — | None (beast) |

*Requires:* Survival: Trained for pelt and meat (per bestiary).

---

**Elite Wolf — "Alpha"**

*"The big one hangs back, watching. When it moves, the others shift to match — this is their leader."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 17 | 11 × 1.5 (rounded up) |
| AC | 13 | 12 + 1 |
| Bite | +5, 1d6+3 (6 avg) | +1 hit; damage: (5.5) × 1.25 ≈ 7 → 1d6+3 |
| Save DCs | 12 | 11 + 1 (prone save) |
| Pack Tactics | Enhanced: Alpha Presence | Pack Tactics now grants advantage to *all* allied wolves within 10 ft when the alpha attacks (not just the alpha gaining advantage) |
| XP | 37 | 25 × 1.5 (rounded down) |

**Loot:**

| Drop | Qty | Chance |
|---|---|---|
| Wolf pelt (large, prime) | 1 | 100% |
| Wolf fangs | 1d4 + 1 | 100% |
| Wolf meat | 3 | 100% |
| Currency | — | None (beast) |

---

**Boss Wolf — "Greymane Pack Lord"**

*"It steps out of the treeline and the forest goes quiet. Silver-scarred, one eye clouded. The pack drops low behind it — not following, obeying."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 22 | 11 × 2.0 |
| AC | 14 | 12 + 2 |
| Bite | +6, 1d8+3 (7 avg) | +2 hit; damage × 1.5 → 1d8+3 |
| Save DCs | 13 | 11 + 2 (prone save) |
| Pack Tactics | Enhanced (same as Elite Alpha) | Alpha Presence |
| **Signature: Howl of the Pack** | 1/encounter | The Pack Lord howls. All allied wolves within 60 ft immediately move up to half their speed and make a free bite attack against a target within reach. Telegraphed: "The big one throws back its head—" |
| **Legendary Action** | 1/round | Extra bite attack or half-speed reposition |
| XP | 50 | 25 × 2.0 |

**Loot:**

| Drop | Qty | Chance |
|---|---|---|
| Wolf pelt (magnificent, prime) | 1 | 100% |
| Wolf fangs | 1d4 + 2 | 100% |
| Wolf meat | 4 | 100% |
| Bonus item (context loot) | 1 | 100%. Example: Thornwatch scout's badge tangled in its fur, broken silver chain with a locket, remnant of whoever it last killed |
| Currency | — | None (beast, even as Boss) |

---

### Example 3: Mawling (Hollow — Rend, Tier 2)

**Base stat block** (from bestiary): Level 4 | HP 38 | AC 14 | Rending Claws +6 (2d6+3 slashing) | Dissolution Bite +6 (1d8+3 necrotic, DC 14 CON or 1d6 ongoing) | Multi-attack (claws + bite) | Hollow Resilience (resistance to non-magical physical), Malleable Form (squeeze through 1 ft gaps) | XP 150

---

**Minion Mawling — "Whelp"**

*"It drags itself through the breach half-formed — limbs still knitting together, jaw hanging wrong. Hungry, but not yet whole."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 19 | 38 × 0.5 |
| AC | 13 | 14 - 1 |
| Rending Claws | +6, 1d6+2 (5 avg) | Damage: (2d6+3 avg 10) × 0.75 ≈ 7.5 → 1d6+2. Single attack only (multi-attack removed) |
| Dissolution Bite | Removed | Active abilities stripped for minions |
| Hollow Resilience | Retained | Passive |
| Malleable Form | Retained | Passive |
| XP | 75 | 150 × 0.5 |

**Loot:**

| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Rend shard | 1 | 37% | Crafting: Expert (base 75% × 0.5) |
| Dissolution membrane | 1 | 25% | Crafting: Expert (base 50% × 0.5) |
| Currency | — | None (Drift-adjacent, still forming) |

---

**Elite Mawling — "Gorged"**

*"This one is swollen — fed recently. Something about its proportions is wrong in a different way than the others. More substance. More hunger."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 57 | 38 × 1.5 |
| AC | 15 | 14 + 1 |
| Rending Claws | +7, 2d6+4 (11 avg) | +1 hit; damage: (10) × 1.25 ≈ 12.5 → 2d6+4 |
| Dissolution Bite | +7, 1d8+4 necrotic, DC 15 | +1 hit, +1 DC; damage scaled |
| Multi-attack | Enhanced: Claws + Bite + Claws | Extra claw attack (frequency increase on multi-attack) |
| Save DCs | 15 | 14 + 1 |
| XP | 225 | 150 × 1.5 |

**Loot:**

| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Rend shard | 1d4 + 1 | 100% | Crafting: Expert (base 75% + 25%) |
| Dissolution membrane | 2 | 75% | Crafting: Expert (base 50% + 25%) |
| Spatial residue | 1 | 25% | Arcana: Trained (base 0% + 25% Elite bonus) |
| Currency | 2d6 × 1.5 sp (round up) | 15% | Absorbed from victims (Rend+, Tier 2 × 2d6) |

---

**Boss Mawling — "The Ravener"**

*"It's the size of a horse. The other Mawlings give it space — even the Hollow has hierarchy. The ground beneath it darkens, stone pitting and crumbling where it stands."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 76 | 38 × 2.0 |
| AC | 16 | 14 + 2 |
| Rending Claws | +8, 2d8+4 (13 avg) | +2 hit; damage: (10) × 1.5 ≈ 15 → 2d8+4 |
| Dissolution Bite | +8, 1d10+4 necrotic, DC 16 | +2 hit, +2 DC; damage scaled |
| Multi-attack | Enhanced (same as Elite) | Claws + Bite + Claws |
| Save DCs | 16 | 14 + 2 |
| **Signature: Corruption Pulse** | 1/encounter | The Ravener slams the ground. 15 ft radius: DC 16 CON save or take 2d8 necrotic damage and gain Stage 1 Hollowed condition. Half damage on success, no condition. Telegraphed: "The ground beneath the creature *cracks* — dark veins spreading outward—" |
| **Legendary Action** | 1/round | Extra claw attack, half-speed move, or Dissolution Bite (if target in reach) |
| XP | 300 | 150 × 2.0 |

**Loot:**

| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Rend shard | 2d4 | 100% | Crafting: Expert |
| Dissolution membrane | 3 | 100% | Crafting: Expert |
| Spatial residue | 1 | 100% | Arcana: Trained |
| Woven void fragment | 1 | 50% (base 25% × 2, guaranteed floor) | Arcana: Expert |
| Currency | (2d6 × 2) + 15 sp | 15% (base chance unchanged) | Absorbed from victims |
| Bonus item (context loot) | 1 | 100% | Example: half-dissolved Thornwatch badge, corrupted weapon from a previous victim, Hollow-tainted gem |

---

### Example 4: Hollowed Knight (Hollow — Wrack, Tier 3)

**Base stat block** (from bestiary): Level 10 | HP 95 | AC 18 (corrupted plate) | Corrupted Greatsword +9 (2d6+5 slashing + 1d6 necrotic) | Shield Bash +9 (1d6+5, DC 17 STR or prone + pushed 10 ft) | Multi-attack (2 greatsword attacks) | Command Lesser Hollow (direct Tier 1-2 Hollow within 30 ft as bonus action) | Hollow Resilience, Undying Will (first time reduced to 0 HP, drop to 1 HP instead, once per encounter) | XP 500

---

**Elite Hollowed Knight — "Dread Marshal"**

*"The armor is almost recognizable — Thornwatch issue, decades old. Whoever wore it died a long time ago. What's inside now moves with terrible precision."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 143 | 95 × 1.5 (rounded up) |
| AC | 19 | 18 + 1 |
| Corrupted Greatsword | +10, 2d6+6 slashing + 1d8 necrotic | +1 hit; necrotic damage enhanced (1d6 → 1d8 as ability enhancement) |
| Shield Bash | +10, 1d6+6, DC 18 | +1 hit, +1 DC |
| Multi-attack | As written (2 greatsword) | Not further enhanced — necrotic upgrade is the enhancement |
| Command Lesser | Enhanced: range 60 ft (doubled) | Range increase as enhancement |
| Undying Will | As written | — |
| Save DCs | 18 | 17 + 1 |
| XP | 750 | 500 × 1.5 |

**Loot:**

| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Wrack core | 1 + 1 | 100% | Crafting: Expert (base 75% + 25% = 100%) |
| Corrupted plate fragments | 1d4 + 1 | 100% | Crafting: Trained |
| Corrupted greatsword | 1 | 100% | None (base 75% + 25%) |
| Veil shard | 1 | 50% | Arcana: Expert (base 25% + 25%) |
| Currency | 3 × 2d6 × 1.5 sp (round up) | 15% | Absorbed (Rend+, Tier 3) |

---

**Boss Hollowed Knight — "The Fallen Commander"**

*"It stands at the center of the ruined watchtower, corruption bleeding from every joint in its armor. Around it, lesser Hollow move in formation — not a swarm, a unit. This thing remembers what it was."*

| Stat | Value | Derivation |
|---|---|---|
| HP | 190 | 95 × 2.0 |
| AC | 20 | 18 + 2 |
| Corrupted Greatsword | +11, 2d8+6 slashing + 1d8 necrotic | +2 hit; weapon damage scaled (2d6 → 2d8 at 1.5×) |
| Shield Bash | +11, 1d8+6, DC 19 | +2 hit, +2 DC, damage scaled |
| Multi-attack | Enhanced: 3 greatsword attacks | Frequency increase |
| Command Lesser | Enhanced: range 60 ft | Same as Elite |
| Undying Will | As written | — |
| Save DCs | 19 | 17 + 2 |
| **Signature: Hollow Standard** | 1/encounter (recharge 5-6) | The Fallen Commander plants its blade in the ground. 30 ft radius: all allied Hollow gain +2 AC and resistance to radiant damage for 3 rounds. All non-Hollow in the area: DC 19 WIS save or Frightened for 1 round. The area becomes corrupted terrain (counts as Hollow corruption zone for durability purposes). Telegraphed: "It reverses its grip and drives the blade into the stone. The corruption *surges.*" |
| **Legendary Action** | 1/round | Extra greatsword attack, Command Lesser (redirect one Hollow creature's action), or half-speed move |
| XP | 1000 | 500 × 2.0 |

**Loot:**

| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Wrack core | 2 | 100% | Crafting: Expert |
| Corrupted plate (intact) | 1 | 100% | Crafting: Expert |
| Corrupted greatsword | 1 | 100% | None |
| Veil shard | 1 | 100% | Arcana: Expert (guaranteed for Boss) |
| Remnant identity | 1 | 50% | Arcana: Expert. A fragment of who this was. Research value to scholars |
| Currency | (3 × 2d6 × 2) + 40 sp | 15% | Tier 3 Boss bonus |
| Bonus item (context loot) | 1 | 100% | Example: the commander's signet ring (identifies their former faction), a partially intact orders document, a locket with a portrait still visible through the corruption |

---

## DM Narration Guidance

### Communicating Roles Through Voice

The player never hears mechanical role names. Roles are conveyed through the DM's description, the audio treatment, and the companion's tactical commentary.

**Minions:**
- Described collectively, not individually: "A pack of wolves bursts from the undergrowth" not "Wolf 1, Wolf 2, Wolf 3..."
- Companion minimizes them: "The small ones aren't the threat. Watch the big one."
- Die quickly and the DM moves on without lingering: "Your blade cuts through — it drops. Two more behind it."

**Standard:**
- Described individually when few, collectively when many: "The bandit levels her crossbow at you" vs. "Three bandits fan out across the road."
- Companion assesses normally: "Armed and ready. Be careful."
- Combat narration at normal detail level.

**Elite:**
- Always described individually with distinguishing detail: "One of them is bigger — scarred, moving differently."
- Companion flags the threat: "That one — watch it. It's not like the others."
- Enhanced audio treatment on their attacks. The DM gives their actions more narrative weight.

**Boss:**
- Introduced with a pause in narration. The audio shifts. The DM gives them a moment of presence before combat begins.
- Companion reacts with genuine concern: "That's... that's the one in charge. Kael, be careful." / "I've heard stories about things like this. Stay close."
- Signature ability gets full narrative treatment with telegraphing. The DM describes the tell, pauses, then delivers the effect.
- Death is narrated as a significant moment, not a routine kill.

**Named:**
- Per-creature narration cues already exist in the bestiary. The DM follows those.
- The companion may refuse to speak, or speak in whispers, or react with fear they've never shown before.
- Audio design is bespoke (already defined per Named creature in the bestiary).

### Narrating Loot (Audio-First Protocol)

In a voice-first game, loot can't be a popup window. The DM narrates loot discovery following these rules:

**1. Automatic loot (no skill check):** Narrated immediately after combat ends, before the player can ask. Keep it brief.

> "The bandits' pockets yield a handful of silver — about 4 pieces between them. One had a decent short sword, bit dull but serviceable."

**2. Skill-gated loot (requires harvesting):** The DM prompts the player. If the player meets the skill requirement, they auto-succeed — no roll. The gate is the skill tier, not a dice check. This avoids the frustrating "killed it but can't loot it" pattern.

> "The spider's venom sac is intact. You've got the Survival training to extract it carefully — want to take a moment?"

If the player *doesn't* meet the skill requirement, the DM mentions the opportunity exists but is beyond them:

> "There's something in the spider's thorax — some kind of gland. You're not sure how to extract it without rupturing it."

This teaches the player what skills unlock, creating motivation for future Training investment.

**3. Batch narration for large fights:** When multiple creatures die, summarize. Never list per-creature drops in sequence.

> "Between the wolves, you collect four pelts and a pile of fangs. Good haul — the pelts alone would fetch 6 or 7 silver at market."

**4. Value narration is approximate, not exact:** The DM conveys relative value through tone and context. Exact numbers live on the character sheet.

> "Worth a few silver" (low value, Tier 1 common materials)
> "A merchant would pay well for this" (moderate value, Tier 2 materials or better)
> "This is rare. Scholars would bid against each other for it" (high value, Tier 3+ Hollow research materials)
> "You could retire on what this is worth — if you could find a buyer" (Named fragments, legendary materials)

**5. Hollow material warning:** Always flagged when tainted materials are collected.

> "The wrack core pulses with Hollow energy. Valuable, no question — but corrupted. You'll want to purify it before using it in anything you plan to keep."

**6. Boss bonus item narration:** The context loot item gets its own narrative beat — it's a story hook, not just a drop.

> "In the captain's belt pouch, a folded letter. The seal is broken but the wax is fresh — someone read this recently. It's addressed to someone called 'The Nail' and mentions a shipment arriving at the south dock in three days."

---

## Derivation Formula (Implementation Reference)

For the rules engine, the complete stat derivation from a base creature and an assigned role:

```python
def derive_role_stats(base_creature: Creature, role: EncounterRole) -> Creature:
    """
    Takes a base creature stat block and an encounter role.
    Returns a modified creature with role adjustments applied.
    Named creatures are returned unmodified.
    """
    if role == EncounterRole.STANDARD:
        return base_creature  # Identity function
    
    if role == EncounterRole.NAMED:
        return base_creature  # Bespoke stat block, no derivation
    
    modifiers = ROLE_MODIFIERS[role]
    derived = base_creature.copy()
    
    # HP
    derived.hp = apply_multiplier(base_creature.hp, modifiers.hp_mult, round_down=(role == EncounterRole.MINION))
    derived.max_hp = derived.hp
    
    # AC
    derived.ac = base_creature.ac + modifiers.ac_mod
    
    # Attacks
    for attack in derived.attacks:
        attack.to_hit = base_creature_attack.to_hit + modifiers.attack_mod
        attack.damage = scale_damage(base_creature_attack.damage, modifiers.damage_mult)
        if attack.save_dc:
            attack.save_dc = base_creature_attack.save_dc + modifiers.dc_mod
    
    # Saves (Boss only)
    if role == EncounterRole.BOSS:
        for save in derived.proficient_saves:
            derived.save_bonus[save] += 1
    
    # Abilities
    if role == EncounterRole.MINION:
        derived.active_abilities = []  # Strip all actives
    elif role in (EncounterRole.ELITE, EncounterRole.BOSS):
        derived.active_abilities = enhance_abilities(base_creature.active_abilities)
    
    # Boss additions
    if role == EncounterRole.BOSS:
        derived.signature_ability = generate_signature(base_creature)
        derived.legendary_actions = 1
    
    # XP
    derived.xp = int(base_creature.xp * modifiers.xp_mult)
    
    return derived

ROLE_MODIFIERS = {
    EncounterRole.MINION:   RoleMod(hp_mult=0.5, ac_mod=-1, damage_mult=0.75, attack_mod=0, dc_mod=-1, xp_mult=0.5),
    EncounterRole.ELITE:    RoleMod(hp_mult=1.5, ac_mod=+1, damage_mult=1.25, attack_mod=+1, dc_mod=+1, xp_mult=1.5),
    EncounterRole.BOSS:     RoleMod(hp_mult=2.0, ac_mod=+2, damage_mult=1.5, attack_mod=+2, dc_mod=+2, xp_mult=2.0),
}
```

### Loot Derivation

```python
def derive_role_loot(base_loot: list[LootEntry], role: EncounterRole, creature_category: str, creature_tier: int) -> list[LootEntry]:
    """
    Modifies a creature's base loot table by encounter role.
    Also calculates currency drop if applicable.
    """
    if role in (EncounterRole.STANDARD, EncounterRole.NAMED):
        return base_loot  # No modification
    
    derived_loot = []
    for entry in base_loot:
        modified = entry.copy()
        
        if role == EncounterRole.MINION:
            modified.probability = max(0.05, entry.probability * 0.5)
            modified.quantity = max(1, parse_quantity(entry.quantity) - 1)
        
        elif role == EncounterRole.ELITE:
            modified.probability = min(1.0, entry.probability + 0.25)
            modified.quantity = parse_quantity(entry.quantity) + 1
        
        elif role == EncounterRole.BOSS:
            modified.probability = 1.0  # All drops guaranteed
            modified.quantity = ceil(parse_quantity(entry.quantity) * 1.5)
        
        derived_loot.append(modified)
    
    return derived_loot

def calculate_currency_drop(creature_category: str, creature_tier: int, role: EncounterRole) -> CurrencyDrop | None:
    """Returns currency drop for a creature, or None if the category doesn't drop currency."""
    base = CURRENCY_RULES.get(creature_category)
    if base is None or base.chance == 0:
        return None
    
    if role == EncounterRole.MINION:
        return None  # Minions never drop currency
    
    amount = roll_dice(base.dice_formula) * creature_tier
    
    if role == EncounterRole.ELITE:
        amount = ceil(amount * 1.5)
    elif role == EncounterRole.BOSS:
        amount = (amount * 2) + BOSS_CURRENCY_BONUS[creature_tier]
    
    return CurrencyDrop(amount_sp=amount, chance=base.chance)
```

---

## Design Decisions

> Extracted to `game_mechanics_decisions.md` for canonical reference.

**Decision 73: Encounter roles are modifiers on base stat blocks, not separate creature entries.** Reason: the bestiary should contain one canonical entry per creature. Roles are a *presentation layer* applied by the encounter builder, not a data layer. This keeps the bestiary clean, avoids stat block proliferation, and means adding a new creature automatically gives the encounter builder five usable variants without additional authoring.

**Decision 74: Minions lose all active abilities.** Reason: Minions exist to create threat through numbers with minimal tactical overhead. If Minions have special abilities, the DM must track ability uses across potentially 6-10 creatures per fight — that's too much state for the rules engine and too much narration for a voice-first game. Minions attack. That's it. Their danger comes from Pack Tactics, flanking, and action economy pressure.

**Decision 75: Elites get enhanced existing abilities; Bosses get one new signature ability.** Reason: the hybrid model. Elites are recognizably the same creature, just better — the player's knowledge of the base creature transfers. Bosses are tactically distinct — the signature forces the player to adapt. Authoring new abilities per creature per role would be unsustainable at scale; limiting it to one signature per Boss keeps the authoring burden manageable while ensuring Boss fights feel unique.

**Decision 76: Boss legendary action is 1 per round, not per turn.** Reason: in a solo-player game with one companion, "per turn" and "per round" are nearly equivalent (only 2-3 turns per round). 1 per round gives the Boss one extra action — enough to create tactical pressure without overwhelming a single player. In multiplayer (Phase 2+), this may need re-evaluation as more turns per round dilute the Boss's relative action economy.

**Decision 77: Harvesting is auto-success if skill requirement is met.** Reason: the gate is investment (Training in the right skill), not luck. A player who invested in Survival: Expert should reliably harvest Expert-tier materials. Adding a roll creates a double gate — you need the skill AND a good roll — which punishes the player's investment rather than rewarding it. The drama is in the fight, not the looting.

**Decision 78: Material sell values are always lower than crafting value.** Reason: the economy must incentivize the crafting loop. If selling raw materials is more profitable than crafting, the Artificer archetype loses economic identity and the async crafting system becomes irrelevant. Sell values are the floor; crafting is the multiplier. This also creates natural market dynamics — players with Crafting skill extract more value from the same materials.

**Decision 79: Minions never drop currency.** Reason: currency drops from Minions would create a farming exploit — throw yourself at the largest possible Minion swarms for maximum coin per encounter. By restricting currency to Standard and above, the economy rewards *harder* fights, not *bigger* ones. This aligns with the GDD's philosophy that engagement, not grind, drives income.

**Decision 80: Boss bonus loot is context-driven, not creature-driven.** Reason: a bandit captain in a mountain pass should drop something different from a bandit captain in a harbor. Context loot connects the encounter to the story — a letter, a key, a badge, a map fragment. This gives the DM (or the quest author) a loot slot that serves narrative, not just economy. It also makes Boss encounters memorable beyond their mechanics.

**Decision 81: The encounter budget system uses fractional points with Minions at 0.5.** Reason: Minions should be cheap enough to field in large numbers (that's their purpose) but not free (that would create infinite swarms). At 0.5, a Standard encounter budget of 3.0 supports up to 6 Minions — enough for a cinematic swarm — while a tighter budget of 2.0 limits Minion groups to 4, keeping early-game encounters manageable.
