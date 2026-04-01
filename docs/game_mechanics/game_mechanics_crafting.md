# Divine Ruin — Game Mechanics: Crafting System & Item Catalog

> **Claude Code directive:** Read `game_mechanics_core.md` first (Crafting skill, async activities). This document defines how crafting works mechanically, the recipe system, workspace requirements, item categories, and the complete equipment and magic item catalog.
>
> **Related docs:** `game_mechanics_core.md` (required — Crafting skill tiers, async activity model), `game_mechanics_bestiary.md` (creature loot/material catalog), `game_mechanics_npcs.md` (blacksmith commissions, merchant inventories), `game_mechanics_archetypes.md` (Artificer abilities, martial mentor system)

---

## The Crafting Principle

> **Crafting mirrors spellcasting:** recipes are learned, not inherent. Just as a Mage must learn Fireball before casting it, a crafter must learn a recipe before making the item. The three-track model from spell acquisition maps directly: **capacity** (how many projects you can run), **knowledge** (your library of recipes), and **workspace** (where you're crafting determines what's possible).

In voice-first play, the player says: *"I want to take the wrack core from that Hollowed Knight and the Keldaran steel and forge a blade that's effective against Hollow creatures."* The rules engine checks: does the player know a recipe that uses those materials? Do they have the Crafting skill tier required? Is their workspace sufficient? Then it resolves deterministically and returns a narrative-ready result.

---

## Crafting Resolution

### The Three Checks

Every crafting attempt requires three things to align:

**1. Recipe Knowledge** — Do you know how to make this?
- The player must have the recipe in their known recipes library
- Recipes are learned through Training, discovery, NPC teaching, or experimentation
- Unknown recipes cannot be attempted (except through the Experimentation system)

**2. Skill Tier** — Are you skilled enough?
- Each recipe has a minimum Crafting skill tier: Untrained, Trained, Expert, or Master
- Attempting a recipe below your tier: automatic success on the skill check
- Attempting at your tier: Crafting check vs DC
- You cannot attempt recipes above your tier

**3. Workspace** — Do you have the right tools and environment?
- Each recipe requires a workspace tier: Field, Workshop, Forge, or Laboratory
- Field: campfire, basic tools, anywhere outdoors. Always available
- Workshop, Forge, Laboratory: must be **rented from an NPC** at a settlement, **earned through reputation**, or **granted by a portable kit** (Artificer). See Workspace Access below
- You cannot own workspaces in Phase 1. Ownership (guild halls, personal forges) is a Phase 2-3 feature

### Resolution Flow

```python
def resolve_crafting(character, recipe, materials, workspace):
    # Check 1: Knowledge
    if recipe.id not in character.known_recipes:
        return FAILURE("You don't know how to make this. Study the recipe first.")
    
    # Check 2: Skill tier
    if character.crafting_tier < recipe.required_tier:
        return FAILURE("This is beyond your current skill. Requires: {recipe.required_tier}")
    
    # Check 3: Workspace
    if workspace.tier < recipe.workspace_required:
        return FAILURE("You need a {recipe.workspace_required} for this. Current: {workspace.tier}")
    
    # Check 4: Materials
    if not has_all_materials(character.inventory, recipe.materials):
        return FAILURE("Missing materials: {list_missing(character.inventory, recipe.materials)}")
    
    # Check 5: Tainted material handling
    if any_tainted(materials) and character.crafting_tier < EXPERT:
        return FAILURE("Working with Hollow materials requires Crafting: Expert.")
    
    # Resolution: Crafting check
    dc = recipe.dc
    roll = d20() + character.crafting_modifier  # Uses higher of INT or WIS mod + proficiency
    
    if roll >= dc + 10:
        result = EXCEPTIONAL  # Item has bonus property or is higher quality
    elif roll >= dc:
        result = SUCCESS       # Item created as specified
    elif roll >= dc - 5:
        result = PARTIAL       # Item created but flawed (reduced durability or minor penalty)
    else:
        result = FAILURE       # Materials consumed, nothing produced
    
    # Master: Masterwork declaration
    if character.crafting_tier == MASTER and result >= SUCCESS:
        # Player can declare Masterwork — unique named item
        pass
    
    return CraftingResult(
        result=result,
        item=recipe.output_item,
        narrative_hint=get_narrative_hint(result, recipe, materials),
        narration_cue=recipe.narration_cues[result]
    )
```

### Crafting Check DC by Recipe Tier

| Recipe Tier | Required Skill | Base DC | Exceptional Threshold |
|---|---|---|---|
| Basic | Untrained | 8 | 18 |
| Trained | Trained | 12 | 22 |
| Expert | Expert | 16 | 26 |
| Master | Master | 20 | 30 |

### Quality Outcomes

| Result | What Happens | Narrative Tone |
|---|---|---|
| **Exceptional** | Item has a bonus property: +1 to a stat, extra durability, minor enchantment, or cosmetic distinction. DM narrates the moment of inspired craft | Pride. The DM describes a flash of insight, a perfect strike of the hammer, the material responding beyond expectation |
| **Success** | Item created exactly as the recipe specifies. Standard quality | Satisfaction. Clean narration of completion |
| **Partial** | Item created but flawed: -1 durability tier, minor cosmetic defect, or situational penalty. Still functional | Frustration tempered by progress. The DM notes what went slightly wrong |
| **Failure** | Materials consumed. Nothing produced. A lesson learned — gain +1 toward the hidden Crafting skill counter | Disappointment. The DM narrates what went wrong — the metal cracked, the binding didn't hold, the mixture destabilized |

---

## Recipe System

### Recipe Schema

```python
class Recipe:
    id: str                      # "anti_hollow_blade", "healing_potion_minor"
    name: str                    # "Anti-Hollow Blade"
    category: str                # "weapon" | "armor" | "consumable" | "tool" | "enchantment" | "ammunition"
    tier: str                    # "basic" | "trained" | "expert" | "master"
    
    # Materials
    materials: list[MaterialReq] # Required materials with quantities
    optional_materials: list[MaterialReq]  # Optional materials that improve the result
    tainted_materials: bool      # Does this recipe use Hollow materials?
    
    # Requirements
    workspace_required: str      # "field" | "workshop" | "forge" | "laboratory"
    crafting_dc: int             # Base DC for the crafting check
    time: str                    # "1 hour" | "1 day" | "3 days" | "1 week"
    async_cycles: int            # How many async Training cycles this consumes (0 = instant)
    
    # Output
    output_item: str             # Item ID produced
    output_quantity: int         # How many produced (usually 1, consumables may be batch)
    
    # Learning
    study_cost: int              # Training cycles to learn this recipe (1-8, mirrors spell learning)
    discovery_sources: list[str] # Where this recipe can be found: "blacksmith_npc", "dungeon_schematic", "experimentation"
    
    # Narrative
    narration_cues: dict         # Per-outcome narration cues for the DM

class MaterialReq:
    material_id: str             # "keldaran_steel", "wrack_core"
    quantity: int
    tier_minimum: int            # Minimum material tier (1-4)
    substitutable: bool          # Can a different material of same category be used?
```

### Recipe Acquisition — Three Tracks (Mirroring Spells)

**Track 1: Recipe Slots (from Crafting skill tier)**

Your Crafting skill tier determines how many recipes you can know and what tiers you can learn:

| Crafting Tier | Max Recipe Tier | Known Recipe Slots |
|---|---|---|
| Untrained | Basic only | 3 |
| Trained | Trained | 8 |
| Expert | Expert | 15 |
| Master | Master | Unlimited (Master crafters collect endlessly) |

**Track 2: Recipe Knowledge (from Training and discovery)**

Recipes are learned through:

| Source | How It Works | Cost |
|---|---|---|
| **Async Training** | Study a recipe from a source (schematic, book, mentor notes). Most reliable path | 1-5 cycles depending on recipe tier |
| **NPC Teaching** | A blacksmith, alchemist, or specialist NPC teaches you during an in-session scene. Costs gold + in-game time | Gold (see NPC pricing) + 0 async cycles |
| **Schematic Discovery** | Find a recipe schematic in a dungeon, ruin, or as quest reward. Teaches immediately | 0 cycles (instant learn) |
| **Experimentation** | Attempt to create something without a recipe. Success teaches the recipe permanently. See Experimentation system | Materials consumed regardless of outcome |
| **Tier Advancement** | Advancing to a new Crafting tier grants 2 free recipes of the new tier (representing fundamental techniques unlocked by growing competence) | 0 cycles (automatic) |

**Study cost by recipe tier:**

| Recipe Tier | Async Cycles to Learn |
|---|---|
| Basic | 1 cycle |
| Trained | 2 cycles |
| Expert | 4 cycles |
| Master | 6 cycles |

**Track 3: Workspace Access (from location and social standing)**

You must be at an appropriate workspace to craft. In Phase 1, players **do not own** workspaces — they access them through four methods:

**Method 1: Field (always available)**

A campfire, a flat rock, and basic tools (knife, flint, cord). Every player has Field access everywhere. This supports Basic-tier recipes: bandages, torches, arrows, simple repairs, camp cooking, basic poisons, field butchering.

**Method 2: Rent from NPC**

The primary method for accessing Workshop, Forge, and Laboratory. The player pays a fee to the appropriate NPC (blacksmith, carpenter, alchemist, temple) and uses their workspace for a set duration.

| Workspace | Available At | Rental Cost | Duration | Supports |
|---|---|---|---|---|
| Workshop | Any settlement with a craftsperson (village+) | 2 sp / day | 1 day minimum | Trained recipes: leather armor, wooden weapons, herbal remedies, tool repair, rope, traps |
| Forge | Blacksmith in town+ | 5 sp / day | 1 day minimum | Expert recipes: metal weapons, metal armor, shields, weapon modifications |
| Laboratory | Alchemist in city, temple sanctum | 10 sp / day | 1 day minimum | Expert+ recipes: potions, enchantments, Veil-ward components, Hollow material processing, scrolls |
| Forge + Laboratory | City with both (or Keldaran hold) | 12 sp / day | 1 day minimum | Any recipe. Required for highest-tier crafting (Anti-Hollow weapons, Veil-Forged items) |

**Rental rules:**
- Rental requires the NPC's disposition to be **Neutral or better.** An unfriendly blacksmith won't let you touch their forge
- Rental is during off-hours — you use the forge when the blacksmith isn't (evenings/nights). During business hours, the NPC uses it. Multi-day projects accommodate this automatically
- The NPC may observe your work. If you craft something impressive (Exceptional result), their disposition improves by 1. If you damage their equipment (Failure on Expert+ recipe), disposition drops by 1 and you owe repair costs (5-15 sp)
- Rental cost is modified by disposition: Friendly = 80%, Trusted = 60%. This stacks with faction reputation price modifiers
- Payment is per calendar day, not per crafting hour. A 2-hour project still costs a full day's rental. Plan batches

**Method 3: Earned access through reputation**

At **Trusted** disposition with a craftsperson NPC, they may offer **standing access** — you can use their workspace without paying rental, in exchange for ongoing service (repair their equipment, share rare materials, take commissions). This is unlocked through a disposition milestone conversation:

*"You've been good to me. Look — the forge is yours whenever you need it. Just keep bringing me that Keldaran steel when you find it."*

Standing access doesn't cost gold but comes with a social obligation. Neglecting the relationship (not visiting, not fulfilling requests) causes the standing access to decay — the NPC mentions it casually, and after prolonged neglect, revokes it. This keeps the relationship alive as a gameplay loop.

| Workspace | Standing Access Requirement | Obligation |
|---|---|---|
| Workshop | Trusted disposition with a craftsperson | Visit at least once per 5 sessions. Share 1 uncommon material per month |
| Forge | Trusted disposition with a blacksmith + complete a personal quest for them | Share Tier 2+ metals when found. Take occasional commissions |
| Laboratory | Trusted disposition with an alchemist or high priest + faction rep Friendly+ | Supply rare ingredients. Assist with research. Report Hollow material findings |

**Method 4: Portable workspace (Artificer class feature)**

The Artificer's Portable Lab (crafted at Expert tier, see Tools & Utility recipes) provides Laboratory-tier workspace anywhere. This is the Artificer's unique class advantage — they're the only archetype that can do advanced crafting in the field.

**What this doesn't include (reserved for Phase 2-3):** Personal workshops, guild forges, player-owned buildings, upgraded workspaces (providing crafting bonuses), shared guild facilities. These are multiplayer and MMO features. The rental and reputation systems are designed with clean seams — personal ownership slots into the same access model, just with a different source (deed instead of disposition).

### Settlement Workspace Availability

Not every settlement has every workspace. This ties to the settlement templates in `game_mechanics_npcs.md`:

| Settlement Size | Field | Workshop | Forge | Laboratory |
|---|---|---|---|---|
| Hamlet | Always | Sometimes (carpenter's bench) | Never | Never |
| Village | Always | Usually (1 craftsperson) | Rarely (traveling smith visits) | Never |
| Town | Always | Always (2-3 options) | Usually (1-2 blacksmiths) | Rarely (temple only, limited) |
| City | Always | Always (many options) | Always (multiple smiths) | Usually (alchemist + temple) |
| Keldaran Hold | Always | Always | Always (renowned forges) | Sometimes (Keldaran focus on metalwork, not alchemy) |

This creates **geographic crafting incentive:** a player who harvests wyrm scales in a mountain cave must travel to a town with a forge to craft scale mail. A player who finds Hollow residue near the Ashmark must reach a city with a laboratory to process it. The journey between harvesting and crafting is content — travel encounters, NPC interactions, economic decisions.

### The Experimentation System

> *"What happens if I mix cave wyrm acid with this Hollow residue and pour it over my sword?"*

When a player attempts to create something they don't have a recipe for, the Experimentation system activates. This is the voice-first crafting moment — the player describes what they want to make using the materials they have, and the rules engine resolves whether they discover a valid recipe.

**Experimentation Flow:**

1. Player describes desired outcome and materials to the DM
2. Rules engine checks: does a recipe exist that uses these materials (or acceptable substitutes)?
3. If yes: Crafting check at DC +4 (harder without a recipe). Success: item created AND recipe learned permanently. Failure: materials consumed, no recipe learned, but the player learns one thing about what went wrong (narrated by DM)
4. If no valid recipe exists: DM narrates the attempt failing in an interesting way. Materials consumed. The player learns the combination doesn't work — this is tracked so they don't repeat it

**Experimentation is expensive but rewarding.** Materials are always consumed. But a successful experiment teaches the recipe permanently without spending Training cycles. This rewards creative players who pay attention to material properties and make smart guesses.

**The Artificer advantage:** Artificers have Tool Expertise (double proficiency on Crafting checks) and at Expert tier can work safely with Hollow materials. This means Artificer experimentation succeeds more often and can explore Hollow-material combinations that would corrupt other crafters.

---

## Crafting Categories

### Weapons

| Recipe | Tier | Materials | Workspace | DC | Time | Output |
|---|---|---|---|---|---|---|
| Wooden Club | Basic | 1 wood | Field | 8 | 1 hour | Club (1d4 bludgeoning) |
| Stone-Tipped Spear | Basic | 1 wood + 1 stone | Field | 8 | 2 hours | Spear (1d6 piercing, thrown 20/60) |
| Bone Dagger | Basic | 2 bones/teeth (any) | Field | 10 | 1 hour | Dagger (1d4 piercing, light, finesse) |
| Hunting Bow | Trained | 1 quality wood + 1 fiber/sinew | Workshop | 12 | 1 day | Shortbow (1d6 piercing, 80/320) |
| Iron Sword | Trained | 3 iron ore + 1 wood (handle) | Forge | 13 | 1 day | Longsword (1d8 slashing, versatile 1d10) |
| Steel Longsword | Expert | 2 Keldaran steel + 1 quality leather (grip) | Forge | 16 | 3 days | Longsword +1 (1d8+1 slashing, versatile 1d10+1) |
| Anti-Hollow Blade | Expert | 2 Keldaran steel + 1 wrack core (purified) + 1 blessed oil | Forge + Laboratory | 18 | 1 week | Longsword +1 with +1d6 radiant vs Hollow. Permanently blessed |
| Veil-Forged Weapon | Master | 2 Tier 3+ metal + 1 Named fragment + 1 Veil shard + 1 divine material | Forge + Laboratory | 22 | 2 weeks | Weapon +2, unique property (Masterwork declaration). Anti-Hollow. Resonance-reducing aura |

### Armor

| Recipe | Tier | Materials | Workspace | DC | Time | Output |
|---|---|---|---|---|---|---|
| Padded Armor | Basic | 2 cloth/fiber | Field | 8 | 2 hours | AC 11 + DEX. Disadvantage Stealth |
| Hide Armor | Trained | 2 hides/pelts (Tier 1) | Workshop | 12 | 1 day | AC 12 + DEX (max 2) |
| Studded Leather | Trained | 2 hides/pelts + 1 iron ore | Workshop | 13 | 1 day | AC 12 + DEX. Best light armor |
| Chain Shirt | Expert | 4 iron ore | Forge | 16 | 3 days | AC 13 + DEX (max 2) |
| Scale Mail | Expert | 3 wyrm/creature scales (Tier 2+) + 2 iron ore | Forge | 17 | 3 days | AC 14 + DEX (max 2). Themed to creature source |
| Hollow-Ward Armor | Expert | 3 Keldaran steel + 1 Veilrender carapace (purified) + 1 blessed oil | Forge + Laboratory | 19 | 1 week | AC 15 + DEX (max 2). Resistance to necrotic. +2 saves vs Hollow effects |
| Masterwork Plate | Master | 6 Tier 3+ metal + 2 quality leather + 1 divine material | Forge | 22 | 2 weeks | AC 18. Masterwork declaration: unique property |

### Consumables — Potions & Elixirs

| Recipe | Tier | Materials | Workspace | DC | Batch | Time | Output |
|---|---|---|---|---|---|---|---|
| Healing Salve | Basic | 1 medicinal herb | Field | 8 | 2 | 1 hour | Restores 1d4 HP. Applied externally |
| Antidote | Trained | 1 medicinal herb + 1 venom sac | Workshop | 12 | 1 | 2 hours | Cures Poisoned condition |
| Healing Potion (Minor) | Trained | 2 medicinal herbs + 1 crystal flask | Laboratory | 13 | 1 | 1 day | Restores 2d4+2 HP |
| Healing Potion (Standard) | Expert | 3 medicinal herbs + 1 dire bear heart + 1 crystal flask | Laboratory | 16 | 1 | 1 day | Restores 4d4+4 HP |
| Poison (Contact) | Trained | 1 venom sac + 1 alchemical reagent | Laboratory | 14 | 3 doses | 2 hours | DC 13 CON save or 2d6 poison + Poisoned 1 hour |
| Poison (Ingested) | Expert | 1 rare venom sac + 2 alchemical reagents | Laboratory | 17 | 1 dose | 1 day | DC 16 CON save or 4d6 poison + Poisoned 4 hours. Onset: 1d4 hours after ingestion |
| Alchemist's Fire | Trained | 1 alchemical reagent + 1 oil flask | Laboratory | 13 | 2 | 2 hours | Thrown (20 ft): 1d6 fire, target takes 1d6 at start of each turn until extinguished (action) |
| Holy Water | Trained | 1 blessed oil + water + silver dust (5 sp) | Temple | 12 | 3 vials | 2 hours | Thrown (20 ft): 2d6 radiant to Hollow/undead |
| Resonance Stabilizer | Expert | 1 Veil shard + 2 alchemical reagents + 1 divine material | Laboratory | 18 | 1 | 1 day | Drink: reduce personal Resonance by 3. Once per long rest |
| Healing Potion (Greater) | Master | 4 medicinal herbs + 1 thunderbird oil + 1 Tier 3 organ + 1 crystal flask | Laboratory | 20 | 1 | 3 days | Restores 8d4+8 HP |

### Consumables — Ammunition & Throwables

| Recipe | Tier | Materials | Workspace | DC | Batch | Time | Output |
|---|---|---|---|---|---|---|---|
| Arrows (basic) | Basic | 1 wood + feathers | Field | 8 | 10 | 1 hour | Standard arrows |
| Arrows (quality) | Trained | 1 quality wood + iron tips + feathers | Workshop | 12 | 10 | 2 hours | +1 damage arrows |
| Bolts (crossbow) | Basic | 1 wood + 1 iron | Field | 8 | 10 | 1 hour | Standard crossbow bolts |
| Blessed Arrows | Expert | quality arrows + 1 blessed oil | Laboratory | 16 | 5 | 1 day | +1d4 radiant vs Hollow/undead |
| Anti-Hollow Oil (coating) | Expert | 1 rend shard (purified) + 1 alchemical reagent + 1 blessed oil | Laboratory | 17 | 3 uses | 1 day | Coat weapon: +1d6 radiant vs Hollow for 3 hits |
| Smoke Bomb | Trained | 1 alchemical reagent + 1 cloth | Workshop | 13 | 3 | 2 hours | 10 ft obscurement, 1 round |

### Tools & Utility

| Recipe | Tier | Materials | Workspace | DC | Time | Output |
|---|---|---|---|---|---|---|
| Torch (long-burning) | Basic | 1 wood + 1 oil/fat | Field | 8 | 30 min | Burns 4 hours (double normal) |
| Rope (50 ft) | Basic | 3 fiber/plant material | Field | 8 | 2 hours | Standard rope |
| Lockpicks | Trained | 1 iron ore | Workshop | 14 | 2 hours | Thieves' tools. Required for picking locks |
| Trap (snare) | Trained | 1 rope + 1 metal | Workshop | 13 | 1 hour | DC 12 DEX save or Restrained. Manual trigger or tripwire |
| Trap (spike) | Expert | 2 metal + 1 poison (optional) | Forge | 16 | 2 hours | DC 14 DEX save or 2d6 piercing (+ poison if applied) |
| Artificer's Portable Lab | Expert | 3 Keldaran steel + 2 alchemical reagents + 1 crystal + 1 quality leather case | Forge + Laboratory | 18 | 1 week | Portable Laboratory workspace. Artificer-only. Allows Laboratory-tier crafting in the field |
| Veil-Ward Anchor (small) | Expert | 1 spatial residue (purified) + 1 blessed oil + 1 enchanted stone | Laboratory | 18 | 1 day | Creates a 15 ft Veil Ward for 1 hour. Consumed on use. Cleric/Artificer only |
| Veil-Ward Anchor (large) | Master | 1 Veilrender carapace + 1 Named fragment + 2 divine materials + 1 Veil shard | Laboratory | 22 | 1 week | Creates permanent 30 ft Veil Ward at a location. Not consumed. Relocatable with 1 day's work |

### Enchantments (Applied to Existing Items)

| Recipe | Tier | Materials | Workspace | DC | Time | Effect |
|---|---|---|---|---|---|---|
| Sharpen | Basic | 1 whetstone (buy, 1 sp) | Field | 8 | 30 min | +1 damage on next 5 attacks. Reapplied regularly |
| Reinforce | Trained | 1 iron ore or 1 hide | Workshop | 12 | 2 hours | +1 durability tier to weapon or armor |
| Minor Enchantment | Expert | 1 Tier 2 arcane component + item | Laboratory | 16 | 1 day | Add a minor magical property: glow on command, resist weathering, lightweight (+5 ft speed), warm in cold, cool in heat |
| Elemental Infusion | Expert | 1 Tier 2 arcane component + elemental material (fire crystal, ice shard, etc.) | Laboratory | 18 | 3 days | Weapon: +1d4 elemental damage (fire/ice/lightning). Armor: resistance to chosen element |
| Hollow Bane | Expert | 1 wrack core (purified) + 1 blessed oil + weapon | Laboratory | 19 | 3 days | Weapon: +1d6 radiant vs Hollow creatures. Permanently blessed |
| Resonance Dampener | Expert | 1 Veil shard + 1 divine material + armor | Laboratory | 19 | 3 days | Armor: wearer's spells generate -1 Resonance (minimum 0). Stacks with divine source reduction |
| Supreme Enchantment | Master | 1 Named fragment + 1 Tier 4 arcane component + item | Laboratory | 22 | 1 week | Major magical property negotiated with DM. Examples: weapon returns when thrown, armor grants flight 1/day, shield reflects spells |

---

## Item Catalog

### Item Rarity and Tier

| Rarity | Tier | Availability | How Obtained |
|---|---|---|---|
| Common | 1 | Sold in any settlement | Purchase, basic crafting |
| Uncommon | 2 | Sold in towns+, crafted with Trained+ skill | Purchase (limited), crafting, quest reward |
| Rare | 3 | Not sold. Crafted with Expert+ skill, or found | Crafting, dungeon loot, quest reward, NPC gift |
| Legendary | 4 | Unique. Crafted as Masterwork, or found in endgame content | Master crafting, Named creature loot, campaign reward |

### Weapons — Standard Catalog

| Weapon | Category | Damage | Properties | Weight | Price | Rarity |
|---|---|---|---|---|---|---|
| Dagger | Light melee | 1d4 piercing | Finesse, light, thrown (20/60) | 1 lb | 2 sp | Common |
| Short Sword | Light melee | 1d6 slashing | Finesse, light | 2 lb | 5 sp | Common |
| Rapier | Light melee | 1d8 piercing | Finesse | 2 lb | 15 sp | Uncommon |
| Longsword | Martial melee | 1d8 slashing | Versatile (1d10) | 3 lb | 10 sp | Common |
| Greatsword | Martial melee | 2d6 slashing | Heavy, two-handed | 6 lb | 25 sp | Uncommon |
| Battleaxe | Martial melee | 1d8 slashing | Versatile (1d10) | 4 lb | 8 sp | Common |
| Warhammer | Martial melee | 1d8 bludgeoning | Versatile (1d10) | 3 lb | 10 sp | Common |
| Mace | Simple melee | 1d6 bludgeoning | — | 4 lb | 3 sp | Common |
| Spear | Simple melee | 1d6 piercing | Versatile (1d8), thrown (20/60) | 3 lb | 1 sp | Common |
| Staff | Simple melee | 1d6 bludgeoning | Versatile (1d8) | 4 lb | 2 sp | Common |
| Handaxe | Light melee | 1d6 slashing | Light, thrown (20/60) | 2 lb | 2 sp | Common |
| Shortbow | Ranged | 1d6 piercing | Two-handed, ammunition (80/320) | 2 lb | 15 sp | Common |
| Longbow | Ranged | 1d8 piercing | Two-handed, heavy, ammunition (150/600) | 2 lb | 30 sp | Uncommon |
| Light Crossbow | Ranged | 1d8 piercing | Two-handed, loading, ammunition (80/320) | 5 lb | 15 sp | Common |
| Hand Crossbow | Ranged | 1d6 piercing | Light, loading, ammunition (30/120) | 3 lb | 40 sp | Uncommon |
| Heavy Crossbow | Ranged | 1d10 piercing | Two-handed, heavy, loading, ammunition (100/400) | 18 lb | 30 sp | Uncommon |

### Weapon Properties

| Property | Effect |
|---|---|
| Finesse | Use DEX or STR for attack and damage |
| Light | Can dual-wield with another light weapon |
| Heavy | Small creatures have disadvantage |
| Two-handed | Requires both hands |
| Versatile (XdY) | Can use one- or two-handed. Two-handed uses listed die |
| Thrown (X/Y) | Can be thrown. X = normal range, Y = long range (disadvantage) |
| Ammunition (X/Y) | Requires ammunition. Normal/long range |
| Loading | Can only fire once per turn regardless of Extra Attack (crossbow limitation) |
| Reach | Can attack targets 10 ft away |

### Armor — Standard Catalog

| Armor | Category | AC | Properties | Weight | Price | Rarity |
|---|---|---|---|---|---|---|
| Padded | Light | 11 + DEX | Disadvantage Stealth | 8 lb | 3 sp | Common |
| Leather | Light | 11 + DEX | — | 10 lb | 5 sp | Common |
| Studded Leather | Light | 12 + DEX | — | 13 lb | 25 sp | Uncommon |
| Hide | Medium | 12 + DEX (max 2) | — | 12 lb | 5 sp | Common |
| Chain Shirt | Medium | 13 + DEX (max 2) | — | 20 lb | 30 sp | Uncommon |
| Scale Mail | Medium | 14 + DEX (max 2) | Disadvantage Stealth | 45 lb | 30 sp | Uncommon |
| Half Plate | Medium | 15 + DEX (max 2) | Disadvantage Stealth | 40 lb | 50 gc | Rare |
| Chain Mail | Heavy | 16 | STR 13, Disadvantage Stealth | 55 lb | 50 sp | Uncommon |
| Plate | Heavy | 18 | STR 15, Disadvantage Stealth | 65 lb | 100 gc | Rare |
| Shield | Shield | +2 AC | One hand occupied | 6 lb | 5 sp | Common |

### Adventuring Gear — Standard Catalog

| Item | Weight | Price | Notes |
|---|---|---|---|
| Backpack | 5 lb | 2 sp | Holds 30 lb of gear |
| Bedroll | 7 lb | 1 sp | Required for comfortable short rest outdoors |
| Rations (1 day) | 2 lb | 5 cp | 1 day food. Spoils after 2 weeks |
| Waterskin | 5 lb (full) | 2 cp | 1 day water |
| Torch | 1 lb | 1 cp | 20 ft bright + 20 ft dim light. Burns 1 hour |
| Lantern | 2 lb | 5 sp | 30 ft bright + 30 ft dim. Burns 6 hours per oil flask |
| Oil Flask | 1 lb | 1 cp | Fuel for lantern. Can be thrown (5 ft fire, 1d4 fire damage) |
| Rope (50 ft) | 10 lb | 1 sp | Hemp. Holds 500 lb |
| Grappling Hook | 4 lb | 2 sp | Attach to rope for climbing |
| Healer's Kit | 3 lb | 5 sp | 10 uses. Required for Medicine checks to stabilize |
| Thieves' Tools | 1 lb | 15 sp | Required for picking locks and disabling traps |
| Climbing Kit | 12 lb | 15 sp | Advantage on Athletics (climbing) |
| Tent (2 person) | 20 lb | 2 sp | Shelter. +1 to short rest quality outdoors |
| Ink & Quill | — | 5 sp | Writing supplies. Required for scroll crafting |
| Crystal Flask | — | 3 sp | Required for potion crafting. Reusable after potion consumed |
| Holy Symbol | 1 lb | 5 sp | Required focus for divine casting. Patron-themed |
| Arcane Focus (staff/orb/crystal) | 2-4 lb | 10 sp | Required focus for arcane casting |

### Magic Items — Rare and Legendary

> Magic items are not mass-produced. Each is crafted, found, or earned. Their rarity ensures they feel meaningful in voice-first narration — the DM describes them with weight and reverence.

#### Rare Items (Tier 3)

**Blade of the Ashmark**
*Weapon (longsword), Rare, requires attunement*
A sword forged from Keldaran steel and quenched in blessed oil. Carried by Ashmark veterans.
- +1 to attack and damage
- +1d6 radiant damage vs Hollow creatures
- Glows faintly when Hollow creatures are within 60 ft (player hears a soft chime in-game)
*Audio:* Soft radiant hum when drawn. Blade chime intensifies near Hollow.
*Crafted from:* 2 Keldaran steel + 1 wrack core (purified) + 1 blessed oil. Expert recipe.

**Thornveld Guardian Shield**
*Armor (shield), Rare, requires attunement*
Carved from living Thornveld ironwood that still grows, slowly, even after being cut.
- +2 AC (standard shield bonus)
- Once per long rest: cast Bark Skin as a reaction without spending Focus
- In natural terrain: +1 additional AC (the shield draws strength from the land)
*Crafted from:* 2 Thornveld ironwood + 1 corrupted heartwood (purified) + 1 Thornveld amber. Expert recipe.

**Cloak of the Steppe Winds**
*Wondrous item, Rare, requires attunement*
A cloak woven from Drathian steppe grass and razorwing feathers. Moves as if always in wind.
- +10 ft movement speed
- Advantage on saves vs being knocked prone or pushed
- Once per long rest: Disengage as a free action (the wind carries you)
*Crafted from:* 2 razorwing feathers + 1 dire bear hide + Drathian spider silk. Expert recipe.

**Veil-Sight Lens**
*Wondrous item, Rare, requires attunement by a caster*
A monocle crafted from a Veil shard, set in Keldaran silver. Shows the invisible.
- See invisible creatures and objects within 30 ft
- See through illusions (advantage on Investigation to disbelieve)
- See Resonance levels as a faint glow around casters (DM reveals current Resonance state)
*Crafted from:* 1 Veil shard + 1 power crystal + silver (10 sp). Expert recipe.

**Ring of Resonance Dampening**
*Wondrous item, Rare, requires attunement by a caster*
A plain iron ring inlaid with a thread of spatial residue. Warm to the touch.
- Wearer's spells generate -1 Resonance (minimum 0)
- Hollow Echo rolls gain +2 (less dangerous when they do occur)
- If Resonance reaches Overreach while wearing: the ring absorbs 3 Resonance and cracks (destroyed, single use)
*Crafted from:* 1 spatial residue (purified) + 1 iron ore + 1 arcane component (Tier 2). Expert recipe.

**Potion of Veil Walking**
*Consumable, Rare*
A shimmering, iridescent liquid that smells of ozone and tastes of nothing.
- Drinker becomes incorporeal for 1 minute: can move through solid objects (ending turn inside one deals 3d10 force damage), immune to physical damage, can't physically interact with anything
- Generates 3 Resonance on consumption (tearing through the Veil has consequences)
*Crafted from:* 1 woven void fragment + 2 alchemical reagents + 1 crystal flask. Expert recipe.

#### Legendary Items (Tier 4)

**Architect's Edge**
*Weapon (any melee), Legendary, requires attunement*
Forged from living stone taken from the Architect's construction zone. The blade reshapes itself.
- +2 to attack and damage
- Once per combat: reshape a 10 ft wall, floor, or barrier within 30 ft (as the Architect's Reshape ability). Lasts 1 minute
- The weapon slowly changes shape between combats — the blade may be curved one day and straight the next. It's still learning
*Source:* Crafted from Architect loot (living stone + Named fragment + Veil shard). Master recipe. Or found in the Architect's ruins.

**Choir's Silence**
*Wondrous item (amulet), Legendary, requires attunement*
A crystal pendant containing a single perfect note — the last sound the Choir made before it was destroyed.
- Immunity to psychic damage
- Immunity to Charmed and Frightened conditions
- Once per long rest: create 30 ft radius Silence (no sound enters or leaves) for 10 minutes. Inside: total protection from sonic/psychic effects. Verbal spellcasting fails
- The wearer hears faint music when alone. It's not the Hollow — it's the trapped note dreaming
*Source:* Crafted from Choir resonance crystal + Named fragment + divine material. Master recipe. Or found after defeating the Choir.

**Stillheart**
*Wondrous item (ring), Legendary, requires attunement*
A ring carved from a shard of the Still's false paradise. Warm. Comforting. Slightly too comforting.
- Advantage on all WIS saves
- Immune to the Charmed condition
- Once per long rest: project a 15 ft aura of calm for 1 minute. All creatures in aura: advantage on saves vs fear, charm, and despair. Hostile creatures: WIS save DC 18 or unwilling to attack (as Sanctuary)
- **Drawback:** Once per week, the ring whispers an offer: *"Stay. Rest. You've earned it."* WIS save DC 15 or the wearer spends their next long rest in a trance of perfect contentment — gaining no benefit from the rest (no HP recovery, no spell recovery). The paradise tries to reclaim its shard
*Source:* Crafted from shard of false paradise + Named fragment + divine material. Master recipe.

**Thornridge's Stand** (unique)
*Armor (shield), Legendary, requires attunement*
A battered, scarred tower shield recovered from the ruins of Greyhaven's watchtower. It bears the names of seven soldiers.
- +2 AC (enhanced shield bonus)
- Intercept range extends to 15 ft (you can protect allies across a room)
- Once per long rest: Last Wall — for 1 round, allies behind you have full cover. You take all damage that would hit them. You cannot be reduced below 1 HP during this round
- The shield whispers the names of the seven when the bearer is afraid. Immunity to Frightened
*Source:* Found only at the ruins of Greyhaven, after completing the Vigil of Greyhaven quest chain. Cannot be crafted. Sergeant Kael Thornridge's legacy.

---

## Durability System

> Items in Aethos are not invulnerable. The Hollow corrodes, combat damages, and time wears.

### Durability Tiers

| Tier | Hits Before Damage | Repair |
|---|---|---|
| Fragile | 3 hits | Field repair (Crafting: Untrained) |
| Standard | 10 hits | Workshop repair (Crafting: Trained) |
| Reinforced | 25 hits | Forge repair (Crafting: Expert) |
| Masterwork | 50+ hits | Only repaired by Master crafter or original creator |

**What counts as a "hit" to durability:**
- Weapon: each combat encounter counts as 1 hit (not each swing — that would be tedious). Crits against heavily armored targets count as 2
- Armor: each time you take damage, 1 hit. Hollow dissolution effects count as 2
- Shield: each time you use a shield reaction (Shield Bash, Shield Wall, Intercept), 1 hit
- Tools: each crafting project counts as 1 hit

**At 0 durability:** Item is broken. -2 to attacks (weapons), -2 AC (armor), unusable (tools). Must be repaired to function. Repair costs materials appropriate to the item's tier.

**The Hollow corrodes faster.** Items used against Hollow creatures or in Hollow corruption zones take double durability damage. This creates a supply-line pressure: prolonged Hollow campaigns drain equipment faster than normal adventuring.

### Repair Pricing (at NPC blacksmith)

| Item Tier | Cost | Time |
|---|---|---|
| Common | 2 sp | 1 hour |
| Uncommon | 10 sp | 1 day |
| Rare | 50 sp | 3 days |
| Legendary | 200+ sp or quest | 1 week |

---

## Async Crafting Activity

> Crafting projects that take more than a few hours in-game time are resolved through the async activity system. The player starts the project, then checks in when it completes (like sending a companion on an errand).

### Async Crafting Flow

1. **Start project:** Player tells DM what they want to craft. Rules engine validates recipe, materials, workspace. Materials consumed. Timer starts
2. **Decision point (mid-project):** For Expert+ recipes, the DM presents a mid-crafting choice: "The metal is taking the quench differently than expected. Do you adjust the temperature (safer, standard result) or push it (riskier, chance of Exceptional quality)?" This creates engagement during the wait
3. **Completion:** Timer expires. Crafting check resolves. DM narrates the result in the next session's Catch-Up feed. Item added to inventory

### Async Cycle Conversion

| Recipe Time | Async Cycles | Real-World Time (1 cycle = 1 day) |
|---|---|---|
| 1 hour | 0 (instant, resolve in-session) | — |
| 2 hours | 0 (instant) | — |
| 1 day | 1 cycle | ~1 day |
| 3 days | 2 cycles | ~2 days |
| 1 week | 4 cycles | ~4 days |
| 2 weeks | 6 cycles | ~6 days |

### Crafting vs. Other Async Activities

Players choose how to spend their async time:
- **Crafting** — make items (consuming materials)
- **Training** — learn spells or recipes (consuming cycles)
- **Companion Errand** — send companion to scout/gather (consuming companion availability)

A player can only run **one async activity at a time** (unless they have an Artificer's Portable Lab, which allows crafting to run alongside one other activity). This forces meaningful time allocation — do you spend this week learning a new spell, or forging that anti-Hollow blade?

---

## Design Decisions Log (Crafting & Items)

> **Extracted to `game_mechanics_decisions.md`.** Decisions 36-43 cover crafting, items, and workspace systems.
