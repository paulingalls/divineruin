# Divine Ruin — Game Mechanics: Combat, Conditions & Death

> **Claude Code directive:** Read `game_mechanics_core.md` first for foundational systems (attributes, skills, HP, resources). This document defines the Dramatic Dice System, phase-based combat, action economy, initiative, all status effects and conditions, the complete death and dying system, social encounter resolution, and travel/exploration/gathering mechanics.
>
> **Note:** This file has grown beyond pure combat into a general **encounter resolution** document covering all player-facing challenge systems. A rename to `game_mechanics_encounters.md` may be warranted in a future reorganization.
>
> **Related docs:** `game_mechanics_core.md` (required), `game_mechanics_archetypes.md` (archetype abilities referenced in combat), `game_mechanics_magic.md` (spell effects, Resonance in combat), `game_mechanics_bestiary.md` (creature stat blocks, encounter scaling)

---

## Dramatic Dice System

> **Design principle:** The visible dice roll — animation on the HUD, audio cue, DM pause — is the most powerful tension tool in the game. Its power comes from scarcity. If every roll triggers the animation, none of them matter. The bar for dramatic is HIGH. In a typical 5-phase combat encounter, the player should see dramatic dice **0-2 times**. When the dice appear on screen, the player's heart rate should spike because they've learned this only happens when something *actually matters.*

### Always Dramatic (engine flags automatically)

These rolls ALWAYS trigger the HUD dice animation and audio cue, regardless of context:

| Roll Type | Why It's Always Dramatic |
|---|---|
| **Death saves** | The character's life hangs on this roll. The most personal dice in the game |
| **Natural 20 (critical hit)** | The best possible outcome. Celebration moment |
| **Natural 1 (critical fumble)** | The worst possible outcome. Dread moment |
| **Boss attack against the player** | Named creature (Tier 4) targeting you directly. Every hit from a boss matters |
| **Counterspell contests** | Mage vs enemy caster. Two wills clashing. Outcome swings the fight |
| **De-escalate attempt** | Diplomat trying to end combat with words. Success or failure changes everything |
| **Concentration check after major damage** | The spell that's holding the battlefield together might shatter |

### Contextually Dramatic (engine evaluates)

The engine checks these conditions. If any are true, the roll is flagged dramatic:

```python
def is_dramatic(roll_result, context) -> bool:
    # Always dramatic
    if roll_result.raw_die in [1, 20]:
        return True
    if context.roll_type == "death_save":
        return True
    if context.attacker and context.attacker.tier == 4:  # Named/boss
        return True
    if context.ability in ["counterspell", "de_escalate"]:
        return True
    if context.roll_type == "concentration" and context.damage_taken >= 15:
        return True
    
    # Contextually dramatic
    if context.target_hp_remaining <= context.damage_potential:
        return True  # This hit could be the killing blow
    if context.player_hp_percent <= 0.25 and context.roll_type == "defense":
        return True  # Player is nearly dead, this defense matters
    if context.is_first_attack_of_combat:
        return True  # Opening strike sets the tone
    if context.enemies_remaining == 1 and context.roll_type == "attack":
        return True  # Last enemy standing — the finishing blow
    if context.margin is not None and abs(context.margin) <= 1:
        return True  # Razor-thin outcome (resolved after roll, shown retroactively)
    if context.social_stakes == "high":
        return True  # High-stakes social check (Tier 2-3 social encounters)
    
    return False
```

### Never Dramatic (always invisible)

These rolls NEVER show dice, regardless of outcome:

| Roll Type | Why It's Never Dramatic |
|---|---|
| Minor damage calculations | Math, not drama |
| NPC initiative rolls | Bookkeeping |
| Loot randomization | Happens off-screen |
| Routine skill checks in exploration | "I search the room" doesn't need a dice animation |
| Background disposition adjustments | World simulation, not player-facing |
| Enemy attacks in easy encounters (Tier 1 creatures vs high-level player) | No real threat, no real tension |

### How Dramatic Dice Work in Play

**Audio:** A distinct percussive audio cue plays — the `dice_roll` sound. Over time, this sound becomes Pavlovian. The player hears it and *knows* something important just happened, even if they're not looking at the screen.

**Visual:** The HUD dice overlay appears — an animated d20 that tumbles and lands on the result. The roll value shows large, the modifier smaller, the outcome label (SUCCESS/FAILURE) in accent color. Auto-dismisses after 3-4 seconds.

**DM behavior:** When the engine flags a roll as dramatic, the DM's narration packet includes a `pause_for_dice: true` instruction. The DM builds tension before the result: "You swing with everything you have—" [dice animation fires, 1-2 second pause] "—and the blade *shatters* through the knight's guard." Without the flag, the DM narrates the outcome seamlessly with no pause.

**Frequency target:** In a typical 5-phase combat encounter against Tier 2 enemies, the player sees dramatic dice **0-2 times.** In a boss fight (7+ phases against a Named creature), the player sees dramatic dice **3-5 times.** In a social encounter, dramatic dice appear **0-1 times** (only for Tier 2-3 contested checks or structured scene climaxes). Death saves are always dramatic but should be rare by design — the death system is consequential precisely because you shouldn't be making these rolls often.

---

## Combat System — Phase-Based

> **Design principle:** Combat is a cinematic sequence, not a spreadsheet. Every phase plays out as one flowing scene — players declare, the engine resolves, the DM narrates everything as a single dramatic moment. No turn-by-turn. No movement grids. No action budgets. One declaration, one resolution, one narration.

### Action Economy

**One declaration per phase per participant.** The player says ONE thing — "I attack the mawling," "I cast Fireball," "I protect the healer." The rules engine resolves everything that declaration implies, including any declaration enhancers from the character's abilities.

**Declaration categories:**

| Category | Player says | Engine resolves |
|---|---|---|
| **Attack** | "I attack it" / "I hit it with my sword" | Attack roll + damage. Positioning handled by engine |
| **Ability** | "I use Devastating Strike" / "I cast Fireball" | Resource cost + ability resolution + all effects |
| **Interact** | "I drink a healing potion" / "I pick up the sword" | Item use or object interaction |
| **Maneuver** | "I tackle it" / "I push it off the ledge" | Contested check or skill check vs DC |
| **Defend** | "I protect the healer" / "I take cover" | +2 AC until next phase, or Guard (impose disadvantage on attacks vs one ally) |
| **Retreat** | "I run" / "I get out of here" | Disengage + move to safety. May provoke if no clean-exit ability |

**Declaration enhancers** (abilities formerly labeled "quick action" or "bonus action"):

These are NOT separate actions. They expand what a single declaration resolves into. The player still says one thing; the engine does more.

| Ability | Archetype | Enhancement |
|---|---|---|
| Cunning Action | Rogue | Any attack declaration also includes Dash, Disengage, or Hide |
| Extra Attack (L10) | Warrior, Skirmisher, Paladin | Attack declarations resolve as 2 attacks instead of 1 |
| Hit and Run | Skirmisher | Attack declaration includes free 15 ft reposition |
| Command Lesser | Hollowed Knight | Attack declaration also directs up to 4 lesser Hollow |
| Quick Change | Spy | Any social declaration can include identity swap |
| Shield Bash | Warrior, Paladin, Guardian | Can combine with main weapon attack (replaces one attack if multiattack) |

> **Terminology note:** All references to "bonus action" or "quick action" in archetype profiles and creature stat blocks should be read as declaration enhancers. They expand what a single declaration resolves into, not a separate action. The term "reaction" remains unchanged — reactions are interrupt-triggered abilities (see below).

### Reactions — Voice Interrupts

Reactions happen **during enemy resolution**, not during the player's declaration. The DM narrates enemy actions and the player can interrupt.

**Reaction rules:**
- One reaction per phase per character. The engine tracks availability
- Each reaction ability specifies its trigger: "when hit" (Brace for Impact, Uncanny Dodge), "when ally hit" (Intercept, Shield of Faith), "when enemy casts" (Counterspell), "when enemy approaches" (Dissonant Whisper)
- The DM creates reaction windows during narration: "The mawling lunges at you—" [pause]. Player shouts "I block!" or says nothing. If nothing, DM continues with full damage
- If the player has no reaction abilities, the DM doesn't pause — narration flows continuously. The engine signals which characters have reactions available
- Stamina/Focus cost still applies. "I block!" at 0 Stamina fails — DM narrates: "You try to brace but you're too winded. The blow lands full force"

### Companion Declaration

The companion gets one declaration per phase. The player can direct it ("Kael, protect the flank") or let the DM decide based on the companion's personality and tactical judgment. If undirected, the DM selects from the companion's ability list based on the situation. This keeps companion behavior feeling autonomous.

### Initiative

Initiative determines **resolution priority** within a phase, not turn order. Everyone acts in the same phase. Initiative decides who goes first when order matters — who kills before being killed, who heals before the next blow, who buffs before the attack.

```
initiative = d20 + DEX modifier
// Rolled ONCE at combat start. Persists for entire encounter.
// Ties: player wins over NPC. Among NPCs: higher DEX wins. Still tied: simultaneous.
```

**Initiative rules:**

| Rule | Details |
|---|---|
| Player rolls individually | Player character and companion each roll separately |
| Creatures roll by type | All mawlings share one roll. Hollowed Knight rolls separately. Reduces overhead |
| Surprise | Surprised creatures cannot declare or react in the first phase. Initiative still applies from phase 2+ |
| Cunning Reflexes (Rogue) | Advantage on initiative roll. Cannot be surprised |
| Alert (Guard passive) | Advantage on initiative. Cannot be surprised on duty |
| Assassinate (Assassin NPC) | Advantage on attacks against creatures that haven't acted in first phase |

### Combat Phase Flow — Four Beats

The combat state machine: `idle → encounter_start → initiative_roll → [phase_loop] → combat_end`

Each phase has four beats:

**Beat 1 — Declaration**

DM prompts: "What do you do?" Player speaks intent. Companion declares (player-directed or DM-autonomous). Enemy declarations are determined silently by the DM from creature behavior/tactics blocks.

*Declaration timer:* If the player hesitates too long (~8 seconds solo, 10-15 seconds multiplayer), the DM narrates the hesitation: "You freeze for a moment—" and the phase resolves with the player taking the Defend action (+2 AC). Hesitation is a valid outcome.

*Multiplayer:* Collection window gathers all player declarations simultaneously. No turn order for declaring — everyone speaks at once if they want.

**Beat 2 — Player Resolution (silent)**

The rules engine resolves all player and companion declarations in initiative order. No narration yet — results are collected into a packet. Each result carries a `dramatic` flag (see Dramatic Dice System above). If a player's target died from a higher-initiative ally's action, the declaration is wasted (narrated later as "you swing but it's already falling").

**Beat 3 — Enemy Resolution with Reaction Windows**

The DM narrates the phase as one flowing scene, interleaving player results and enemy actions. Dramatic dice fire during this beat — the DM pauses for the animation when the packet flags a result as dramatic.

1. DM narrates player/companion results from Beat 2. For dramatic results (killing blows, crits, close calls): DM builds tension, dice animation fires on HUD, DM narrates outcome after the beat. For non-dramatic results: DM narrates seamlessly with no pause ("Kael's blade bites deep — the mawling staggers")
2. DM narrates each enemy action, pausing for reaction windows before resolving damage ("The mawling lunges at you—" [pause for reaction]). Boss attacks (Tier 4) always trigger dramatic dice on the enemy's attack roll — the player sees whether the boss hits before the DM narrates the impact
3. If player uses a reaction: engine resolves it immediately. Reactions that are dramatic (Counterspell, Concentration check after major damage) trigger dice animation before the DM narrates the modified outcome. Non-dramatic reactions (basic shield block vs minor enemy) resolve seamlessly
4. If no reaction: DM narrates full impact ("—claws rake across your armor")
5. Continue through all enemy actions

The engine holds enemy damage until each reaction window closes. This means reactions can change outcomes — Uncanny Dodge halves damage, Shield of Faith causes a miss, Counterspell negates a spell.

**Beat 4 — Phase Wrap**

After all actions are narrated: check combat end conditions (all enemies dead/fled, party fled, surrender). If any characters are Fallen, death saves resolve now — **death saves are always dramatic** (dice animation fires with heightened audio treatment, the DM pauses for each save). If combat continues: Stamina regenerates (2/round for martial characters), Resonance decays (1/phase), status effect durations tick down, "start of turn" effects trigger. Next declaration phase begins.

### Simultaneous Resolution Shortcut

If resolution order doesn't matter (two allies attacking different enemies, no healing-before-damage timing), the engine resolves simultaneously for speed. Order-dependent resolution only applies when it could change outcomes.

### Combat End

Combat ends when: all enemies are dead or fled, the party flees or retreats, surrender is offered and accepted, or a narrative event ends the fight. On combat end: XP awarded, loot narrated, combat state machine returns to idle, any lingering status effects noted for post-combat resolution.

---

## Combat Math

### Attack Rolls

```
attack_roll = d20 + attribute_modifier + proficiency_bonus (if proficient with weapon)
hit = attack_roll >= target_AC
```

### Armor Class (AC)

| Armor Category | Base AC | DEX Contribution | Typical AC Range | Archetypes |
|---|---|---|---|---|
| Unarmored | 10 | Full DEX mod | 10–15 | Mage, Bard, Diplomat |
| Light armor | 12 | Full DEX mod | 13–17 | Rogue, Spy, Skirmisher |
| Medium armor | 14 | DEX mod (max +2) | 14–16 | Druid, Cleric, Beastcaller |
| Heavy armor | 16–18 | None | 16–18 | Warrior, Guardian, Paladin |
| Shield (add-on) | +2 | — | +2 | Any one-handed wielder |

### Weapon Damage

| Weapon Category | Damage Die | + Modifier | Avg (low attr) | Avg (high attr) | Archetypes |
|---|---|---|---|---|---|
| Light (dagger, short blade) | 1d4 | STR or DEX | 3.5 | 7.5 | Rogue, Spy, Whisper |
| Standard (longsword, mace) | 1d8 | STR | 5.5 | 9.5 | Warrior, Guardian, Paladin |
| Heavy (greatsword, halberd) | 1d12 | STR | 7.5 | 11.5 | Warrior, Skirmisher |
| Ranged (bow, crossbow) | 1d8 | DEX | 5.5 | 9.5 | Skirmisher, Rogue |
| Cantrip (basic spell) | 1d6 (scaling) | Casting attr | 4.5 | 8.5 | Mage, Cleric, Druid |
| Leveled spell (Focus cost) | 2d6 to 4d8 | — | 7 to 18 | 7 to 18 | Mage, Cleric, Oracle |

### Cantrip Scaling

Cantrips are free (0 Focus) and scale with character level:

| Level | Damage Dice |
|---|---|
| 1–4 | 1d6 |
| 5–10 | 2d6 |
| 11–16 | 3d6 |
| 17–20 | 4d6 |

### Combat Pacing Target

**3–5 rounds per encounter.** Voice combat must resolve quickly. The math is calibrated so that:

- A level 1 Warrior vs. a goblin resolves in 2–3 rounds
- A level 10 party vs. 2–3 mid-tier enemies resolves in 3–5 rounds
- Boss fights may extend to 5–7 rounds with phase transitions

### Saving Throws

```
saving_throw = d20 + attribute_modifier + proficiency_bonus (if proficient in that save)
success = saving_throw >= DC
```

Each archetype is proficient in 2 saving throw attributes (defined per archetype).

---

## Status Effects

Applied by mechanics tools, tracked in character state, automatically factored into rolls.

### Combat Conditions

| Effect | Mechanical Impact | Cleared By |
|---|---|---|
| **Wounded** | Reduced max HP until rest | Long rest |
| **Stunned** | Incapacitated — cannot declare or react. Auto-fail STR/DEX saves | End of next turn |
| **Prone** | Disadvantage on attacks. Melee attacks against have advantage, ranged against have disadvantage. Standing up costs your entire declaration for the phase | Use declaration to stand |
| **Grappled** | Speed 0 (can't reposition or retreat). Attacks not affected. Escape: STR or DEX check vs grappler's DC as your declaration | Escape check, grappler incapacitated, or released |
| **Restrained** | Speed 0. Disadvantage on attacks. Attacks against have advantage. Disadvantage DEX saves | STR check vs source DC, or source destroyed/dispelled |
| **Incapacitated** | Cannot declare or react. Aware but unable to act. Umbrella condition (Stunned, Paralyzed include this) | Depends on source |
| **Paralyzed** | Incapacitated. Auto-fail STR/DEX saves. Attacks against have advantage. Melee hits auto-crit. Most dangerous condition | Duration expires, Greater Restoration, source removed |
| **Poisoned** | Disadvantage on physical checks (STR, DEX, CON) | Short rest, Medicine check, or antidote |
| **Blessed** | Advantage on next roll | Consumed on use |
| **Shielded** | Damage reduction (amount varies by source) | Duration expires |
| **Enraged** | +2 bonus damage, -2 AC | End of combat or dismissed |

### Environmental Conditions

| Effect | Mechanical Impact | Cleared By |
|---|---|---|
| **Exhausted** | Cumulative -1 to all checks per stack (max 5) | Long rest removes 1 stack |
| **Blinded** | Disadvantage on attacks and Perception | Situational |
| **Frightened** | Disadvantage against fear source, can't approach | WIS save at end of each turn |
| **Charmed** | Treats source as ally, disadvantage on checks against them | Damage from source, or duration |
| **Deafened** | Can't hear. Auto-fail hearing Perception. Can't benefit from Bardic Inspire or spoken buffs. In voice play: the DM goes silent for this character's perception | Duration expires or magical healing |
| **Shaken** | Disadvantage on next attack only (one-time). Momentary psychological shock — hearing a Hollowed Knight's fragment voice, witnessing horror | Consumed after one attack roll |
| **Petrified** | Transformed to stone. Incapacitated. Weight ×10. Resistance to all damage. Immune to poison/disease. Aging stops. Effectively removed from combat | Greater Restoration or specific counter-magic |

### Magical Conditions

| Effect | Mechanical Impact | Cleared By |
|---|---|---|
| **Cursed** | Specific penalty (defined by curse source) | Remove Curse ability or quest |
| **Inspired** | +1d4 to creative or social checks | Consumed on use |
| **Hollowed** | Escalating: stage 1 = disadvantage on WIS checks; stage 2 = hallucinations; stage 3 = stat drain | Greater Restoration (Cleric L15), or extended rest in sanctified area |

### Concentration

Spells marked "Concentration, X duration" require ongoing focus to maintain.

- **One at a time.** Only one Concentration spell active. Casting a second ends the first
- **Damage breaks it.** When you take damage while concentrating: CON save DC = 10 or half the damage taken (whichever higher). Fail: spell ends
- **Incapacitated breaks it.** Stunned, Paralyzed, or unconscious: Concentration auto-fails
- **Environmental disruption.** Inside a Veilrender's aura, Hollow Weaver distortion, or similar: DM may call for Concentration check at DM-set DC
- **Hollowmoth debuff.** -1 to Concentration checks per moth swarm in range (max -3)
- **Voice-first narration.** The DM never says "make a Concentration check." Instead: "The mawling's claws rake across your arm — you feel the Entangle spell wavering as your focus fractures." The engine resolves; the DM narrates

### Phase-Based Condition Interactions

Conditions interact with the phase-based action economy in critical ways:

- **Prone costs your declaration.** Standing up IS your declaration for the phase. You can't attack and stand. Knockdown effects (wolf bite, War Cry, Unstoppable Charge) are devastating because they steal an entire phase of action
- **Grappled costs your declaration.** Escaping IS your declaration. Mawling's Lunge (grapple on hit) wastes the target's next phase
- **Stunned/Paralyzed skip your phase entirely.** No declaration, no reaction. The DM doesn't ask "what do you do?" — they narrate the helplessness. Losing a phase in phase-based combat is losing everything
- **Frightened limits declarations.** You can't declare actions that move you toward the fear source. Attack and Ability declarations against the source have disadvantage
- **Charmed limits declarations.** You can't declare hostile actions against the charm source. Effectively removes one enemy from your target list

---

## Resting

| Rest Type | Duration | HP Recovery | Stamina | Focus | Other |
|---|---|---|---|---|---|
| **Short rest** | ~1 hour (in-game) | None (unless abilities grant it) | Full | Half pool | Some abilities reset |
| **Long rest** | ~8 hours (in-game) | Full HP | Full | Full | All abilities reset, Exhaustion -1 |

**Rest restrictions:**
- Cannot long rest in combat or hostile territory without risk of interruption events
- Short rest requires a safe, non-threatened location
- The `rest()` tool validates safety and returns warnings the DM narrates

---

## Death and Dying

> **Design principle:** Death must matter or combat has no stakes. But permanent death in a voice RPG — where the player has built a character through hours of conversation — is too harsh. Death has real, escalating consequences that create dramatic tension without ending the character's story.

### The Fallen State

When HP reaches 0, the character is **Fallen** — unconscious and dying. They cannot declare, react, move, or perceive. The companion's voice becomes urgent. The DM's narration slows and drops in pitch. The player is still listening, still experiencing the story.

**Audio design:** Ambient sounds fade. The player's heartbeat (already escalating from low HP) becomes the dominant sound, slowing to a deep, echoing pulse. The companion narrates frantically. Other combat sounds become muffled and distant.

**Instant death threshold:** If a single source of damage reduces HP to 0 AND the excess damage equals or exceeds the character's max HP, the character dies instantly — no Fallen state, no death saves. Straight to Mortaen's domain. This prevents absurd situations where a Veilrender's 4d8 force attack merely knocks out a 12 HP Mage.

### Death Saves

While Fallen, the character makes death saving throws during **Beat 4 (phase wrap)** of each combat phase — after all actions and reactions resolve. This gives allies exactly one phase to reach the Fallen character with healing.

```
death_save = d20 (no modifiers — raw chance, pure tension)

20    = Critical: regain 1 HP, consciousness restored, can act next phase
10-19 = Success (accumulates)
2-9   = Failure (accumulates)
1     = Critical failure: counts as 2 failures
```

**Three successes:** Stabilized. Still unconscious at 0 HP, but no longer dying. Regain consciousness after 1d4 phases (or immediately if healed for any amount).

**Three failures:** Dead. The character's soul departs for Mortaen's domain.

**Death save tracking:** The rules engine tracks successes and failures. They don't reset between phases — they accumulate until one side reaches 3. Taking damage while Fallen counts as 1 automatic failure (and a melee hit from within 5 ft counts as 2 failures — a Mawling finishing off a downed character is nearly instant death).

**Healing a Fallen character:** Any healing that restores HP immediately ends the Fallen state. The character regains consciousness with whatever HP was restored. Death save counters reset. Allies with healing abilities have incentive to act fast — every phase without healing is another death save.

### The Hollowed Death (Stage 2+ Hollowed Condition)

> *The most horrifying thing in the game happens when you die wrong.*

If a character with **Stage 2 or higher Hollowed condition** reaches 0 HP, they do not enter the normal Fallen state. Instead:

**Phase 1 — The Corruption Takes Hold (1 phase)**

The character falls. But instead of lying still, their body begins to change. The DM narrates the corruption spreading — skin darkening, joints shifting, the wrongness taking over. The player hears this happening to their character. No control. No saves. Just the horror of feeling yourself become the thing you've been fighting.

*Audio:* The player's heartbeat distorts — becomes mechanical, too-regular. Hollow audio cues (HLW-001 subsonic drone) begin mixing with the character's breathing. The companion screams the character's name.

**Phase 2 — The Hollow Rise (combat continues)**

The character rises as a **Temporary Hollowed** — mechanically, a creature under DM control that uses the character's stat block with modifications:

- HP = 50% of character's max HP
- All attacks deal the character's weapon damage + 1d6 necrotic
- Immune to Charmed, Frightened, Poisoned (Hollow immunities apply)
- Moves toward the nearest living creature and attacks
- Uses the character's known abilities but without tactical intelligence — brute force, no finesse
- Retains the character's voice — occasionally speaks fragments. The DM performs this. The companion and party hear their friend's voice, distorted, saying things that are almost words

**The player experiences this.** They hear the DM narrating their body fighting their friends. They hear their companion trying to reach them. They have no control. This is the ride-along — the most emotionally intense moment the game can create.

**Phase 3 — Resolution**

The Temporary Hollowed is destroyed when reduced to 0 HP. The character then enters normal death (Mortaen's domain, see below). The Hollowed condition is cleared by the death — corruption doesn't follow you past Mortaen's threshold.

**If the entire party falls** while a Temporary Hollowed character is active, the total party wipe rules apply (see Party Death below). The Hollowed character resurrects with the party — the corruption is purged by the passage through Mortaen's domain.

**Preventing Hollowed Death:** Greater Restoration (Cleric L15) cures Hollowed at any stage. Dispel Corruption cures Stage 1. Smart parties prioritize removing Hollowed condition before it reaches Stage 2, because the alternative is watching your friend become a monster. This creates real urgency around the Hollowed status effect.

### Mortaen's Domain

When a character dies (three failed death saves, instant death, or Temporary Hollowed destroyed), their soul enters **Mortaen's domain** — the border between life and death.

This is not a game-over screen. It is a narrative scene with mechanical consequences.

**The scene:** The DM voices Mortaen (or an aspect of Mortaen) — calm, ancient, not unkind. The world falls silent. The player hears only the god's voice and their own breathing. Mortaen acknowledges the death, comments on how it happened (the engine provides context), and offers the return.

**The return is automatic.** The character always comes back. The question is not "if" but "at what cost." The rules engine determines the cost tier based on the character's **death counter** — a permanent integer that increments with each death and never resets.

### The Cost Engine

```python
def determine_death_cost(character) -> DeathCost:
    death_count = character.death_counter + 1  # This death
    character.death_counter = death_count
    
    if death_count == 1:
        tier = "gentle"
    elif death_count == 2:
        tier = "moderate" 
    elif death_count <= 4:
        tier = "severe"
    else:
        tier = "devastating"
    
    # Select specific cost from tier
    cost = select_cost(tier, character)
    
    return DeathCost(
        tier=tier,
        cost=cost,
        death_count=death_count,
        narration_cue=get_mortaen_narration(tier, cost, character)
    )
```

**Cost tiers and specific costs:**

| Tier | Death # | Possible Costs (engine selects one, Mortaen narrates) |
|---|---|---|
| **Gentle** | 1st | A **memory fragment** is lost — the DM occasionally references something the character "can't quite remember" (a minor NPC's name, a childhood detail). Narratively poignant, mechanically negligible. OR: Mortaen takes a **small trinket** from inventory (non-essential, sentimental if possible) |
| **Moderate** | 2nd | **-1 to one attribute** (permanent). The engine selects the character's lowest attribute — the cost is felt but not crippling. OR: **Mark of Death** — a visible mark that NPCs who know what it means will comment on. Some NPCs become wary (certain disposition modifiers shift -1). Hollow creatures are slightly more drawn to the marked character (+10% encounter frequency) |
| **Severe** | 3rd-4th | **-1 to a PRIMARY attribute** (permanent). The engine selects from the character's top 2 attributes — this hurts. OR: **Mortaen's Debt** — a personal quest from the god of death. Must be completed within 10 sessions or the character gains 1 permanent Exhaustion stack that cannot be removed. The quest is narratively appropriate (escort a soul, close a breach, destroy an undead abomination). OR: **Loss of a significant item** — Mortaen claims the character's best magical item or most valuable possession |
| **Devastating** | 5th+ | **-2 to a PRIMARY attribute** (permanent). AND **Mortaen's Warning** — the god tells you this is becoming untenable. "The threshold weakens each time you cross it. There will come a time when I cannot send you back." This is narrative foreshadowing, not a mechanical threat — the character always returns. But the accumulating stat losses make the character mechanically weaker with each death, creating natural pressure to play more carefully. At death 7+: **permanent -1 to max HP per level** (retroactive). The character is fraying |

**Cost selection logic:**

```python
def select_cost(tier, character):
    if tier == "gentle":
        if character.has_sentimental_item():
            return TrinketLoss(item=character.least_valuable_sentimental_item())
        return MemoryFragment()
    
    elif tier == "moderate":
        return AttributeLoss(
            attribute=character.lowest_attribute(),
            amount=1
        )
    
    elif tier == "severe":
        options = [
            AttributeLoss(attribute=character.top_two_attributes()[random], amount=1),
            MortaenDebt(quest=generate_death_quest(character)),
            ItemLoss(item=character.most_valuable_item())
        ]
        return weighted_random(options)  # DM context may influence selection
    
    elif tier == "devastating":
        return CompoundCost(
            AttributeLoss(attribute=character.highest_attribute(), amount=2),
            MortaenWarning()
        )
```

### Resurrection Location

When a character returns from Mortaen's domain, they physically appear at the **nearest safe anchor point**. The world data defines these.

**Anchor point hierarchy** (engine checks in order, uses the first valid one):

| Priority | Location | Condition |
|---|---|---|
| 1 | **Where you fell** (the battlefield) | Only if combat is over AND the area is no longer hostile. Allies dragged you to safety |
| 2 | **Nearest allied camp or settlement** | If the area where you fell is still dangerous. The narrative is: your companions carried you, or a patrol found you |
| 3 | **Last settlement you rested at** | If no allied presence near the death site. You wake up where you last felt safe. Time has passed (DM narrates the gap) |
| 4 | **Starting region safe zone** | Absolute fallback. If everything else is compromised (deep in Hollow territory, no nearby settlements), you appear at the nearest starter zone. Mortaen's mercy — deposited where you can recover |

**Time cost:** Resurrection is not instant. In-game time passes based on how far the resurrection location is from the death site:

| Resurrection at | Time passed |
|---|---|
| Battlefield (allies present) | 1 minute (Revivify-like) |
| Nearby camp/settlement | 1d4 hours |
| Last rested settlement | 1 day |
| Starting region fallback | 1d4 days |

This time passes in the world simulation — NPC schedules advance, corruption spreads, quests may progress. Dying deep in Hollow territory and resurrecting at your last settlement means the world moved on while you were dead. The Ashmark shifted. The quest you were on has new complications. The enemy you were fighting has consolidated.

**Companion handling:** The companion appears with you. If the companion was also Fallen, they resurrect alongside you (companion death is narrative-only per GDD — they always come back with the player). If the companion was still standing when you died, they "carried you" or "stayed with you" — the narrative is seamless.

### Party Death (Total Wipe)

If all player characters and companions fall in the same encounter:

1. The encounter ends. The enemy does not pursue (Hollow creatures don't need to — they've won the ground; humanoid enemies may loot and leave)
2. ALL characters enter Mortaen's domain simultaneously. Each pays their individual death cost based on their own death counter
3. All characters resurrect at the **same location** — the highest-priority anchor point available to the party leader (or the player in solo)
4. The world reacts: the quest they were attempting has new complications, the enemy has advanced, NPCs comment on the defeat
5. In-game time passes (see resurrection location table)

**Total party wipes should be rare.** The DM is prompted to scale encounters fairly, the companion provides tactical guidance, and the encounter math in the bestiary is calibrated for 1 player + 1 companion. When wipes happen, they're dramatic setbacks in the story, not punishment.

### Companion Death in Combat

Companions can be **Fallen** in combat (unconscious at 0 HP). They make death saves like player characters. They can be healed. The player hears this happening and can direct their declaration toward saving the companion ("I heal Kael!").

If a companion reaches three failed death saves, they are **stabilized automatically by narrative protection** — companions cannot permanently die during normal combat. The companion is unconscious for the rest of the encounter and wakes after combat ends with 1 HP. The DM narrates the close call with appropriate weight.

**A companion's permanent death, if it ever occurs, is a scripted narrative event** — story-driven, emotionally devastating, and never random. It would be the defining moment of a story arc. The rules engine does not allow companion permadeath through normal combat resolution.

### Mortaen's Patron Interaction

Characters who follow **Mortaen** as their divine patron have a unique relationship with death:

- **Layer 1 gift (Deathsense):** Sense creatures below 25% HP. This means Mortaen followers always know when allies are near death — they can prioritize healing
- **Death save bonus:** +2 to death saves (the god of death knows you, and you know the threshold). This makes Mortaen followers significantly harder to kill
- **Mortaen's domain scene:** Instead of a stranger, the Fallen character meets their patron. The scene is more personal — Mortaen speaks to them as a follower, not a supplicant. The cost still applies, but the narration is warmer: "You again. I begin to wonder if you enjoy my company"
- **Reduced first death cost:** Mortaen followers' first death costs nothing — the god waives the fee for their faithful. Death counter still increments (second death is Moderate tier as normal), but the first return is free. This is the tangible benefit of worshiping the god of death
- **Mortaen's Debt quests** are different for followers — they're personal missions from the patron, not obligations from a stranger. Narratively richer and potentially more rewarding

### Death and Resurrection Spells

These spells (defined in `game_mechanics_magic.md`) interact with the death system:

| Spell | When Used | Effect on Death System |
|---|---|---|
| **Heal Wounds / Healing Touch** | While Fallen (0 HP) | Restores HP, ends Fallen state, resets death save counter. No death cost |
| **Revivify** (Divine, 5 Focus) | Within 1 minute of death (3 failed saves) | Returns to life with 1 HP at the battlefield. Death counter does NOT increment. No Mortaen visit. Requires diamond (50 gc). The "undo" button — but expensive |
| **Resurrection** (Divine, 8 Focus) | Up to 10 days after death | Returns to life with full HP at the caster's location. Death counter DOES increment (Mortaen still claims a cost). Requires diamond (500 gc). The "bring them back" option for when Revivify's window has passed |
| **Greater Restoration** | While Hollowed (any stage) | Clears Hollowed condition. Prevents Hollowed Death if used before character falls to 0 HP |
| **Divine Intervention** (Cleric reaction) | Ally drops to 0 HP | Immediately restores WIS mod HP. Prevents Fallen state entirely. The save |

### Implementation

```python
class DeathSystem:
    def on_hp_zero(self, character, damage_source, excess_damage):
        # Check instant death
        if excess_damage >= character.max_hp:
            return self.instant_death(character)
        
        # Check Hollowed Death
        if character.has_condition("Hollowed") and character.hollowed_stage >= 2:
            return self.hollowed_death(character)
        
        # Normal Fallen state
        character.set_condition("Fallen")
        character.death_saves = {"successes": 0, "failures": 0}
        return FallenResult(
            narrative_hint="fallen",
            narration_cue=f"{character.name} collapses. The world goes dark.",
            audio_cue="heartbeat_slow + ambient_fade"
        )
    
    def resolve_death_save(self, character):
        roll = d20()
        
        if roll == 20:
            character.hp = 1
            character.remove_condition("Fallen")
            return DeathSaveResult("critical_success", 
                narration_cue=f"{character.name}'s eyes snap open. Against all odds — alive.")
        elif roll == 1:
            character.death_saves["failures"] += 2
        elif roll >= 10:
            character.death_saves["successes"] += 1
        else:
            character.death_saves["failures"] += 1
        
        if character.death_saves["successes"] >= 3:
            character.set_condition("Stabilized")
            return DeathSaveResult("stabilized",
                narration_cue=f"{character.name}'s breathing steadies. Still unconscious, but alive.")
        
        if character.death_saves["failures"] >= 3:
            return self.character_death(character)
        
        return DeathSaveResult("ongoing",
            successes=character.death_saves["successes"],
            failures=character.death_saves["failures"],
            narration_cue=get_death_save_narration(roll, character.death_saves))
    
    def character_death(self, character):
        cost = determine_death_cost(character)
        resurrection_point = find_nearest_anchor(character.location, character)
        
        return DeathResult(
            mortaen_scene=True,
            cost=cost,
            resurrection_location=resurrection_point.location,
            time_passed=resurrection_point.time_cost,
            narration_cue=cost.narration_cue
        )
```

---

## Social Encounter Resolution

> **Design principle:** Social encounters are conversations, not menus. The player is actually talking — roleplaying the interaction. Mechanics flow underneath the dialogue, never interrupting it. The DM calls resolution tools behind the scenes; the player hears the NPC's reaction, not "roll Persuasion." Dramatic social moments get visible dice on the HUD, exactly like dramatic combat moments.

### The Dramatic Dice Rule for Social Encounters

Social checks follow the same Dramatic Dice System defined above. Most social checks are **invisible** — the engine resolves, the DM narrates the NPC's reaction seamlessly. Dramatic dice fire only for high-stakes social moments:

| Dice Visible (HUD + audio cue) | Dice Hidden (under the hood) |
|---|---|
| Convincing a faction leader to commit resources | Buying a discount from a friendly merchant |
| De-escalating combat (Diplomat) | Asking an innkeeper for directions |
| Extracting a critical secret (Spy) | Intimidating a single bandit into fleeing |
| Negotiating a surrender mid-battle | Persuading a guard to let you pass |
| Final argument in a structured social scene | Routine Deception to maintain cover |
| Contested exchange where margin is ≤ 1 | Background disposition checks |

In a typical social encounter, the player sees dramatic dice **0-1 times.** The bar is the same as combat: when the dice appear, it means this moment *actually matters.*

### Three Tiers of Social Resolution

#### Tier 1 — Simple Checks (80% of social interactions)

The player says something to an NPC. The DM judges whether a check is needed (trivial requests auto-succeed; impossible requests auto-fail). If a check is needed:

```python
def resolve_social_check(character, skill, npc, context):
    dc = calculate_social_dc(npc, context)
    roll = d20() + character.skill_modifier(skill)
    
    # Advantage/disadvantage from abilities
    if character.has_active("honeyed_words") or character.has_active("compelling_argument"):
        roll = max(roll, d20() + character.skill_modifier(skill))  # Advantage
    
    # Disposition modifier: friendly NPCs are easier to persuade
    dc += DISPOSITION_DC_MODIFIER[npc.current_disposition]
    
    success = roll >= dc
    margin = roll - dc
    
    dramatic = context.stakes >= "high" or abs(margin) <= 2  # Close calls are dramatic
    
    return SocialResult(
        success=success,
        margin=margin,
        dramatic=dramatic,
        narrative_hint=get_social_hint(margin),  # "overwhelming", "barely", "close but no"
        disposition_shift=calculate_disposition_shift(success, margin, skill, context)
    )
```

**Social DC modifiers by NPC disposition:**

| NPC Disposition | DC Modifier | Narrative Feel |
|---|---|---|
| Hostile | +6 | Almost impossible to persuade. They don't want to hear you |
| Unfriendly | +3 | Resistant. Arms crossed. Short answers |
| Neutral | +0 | Base DC. Open to hearing you out |
| Friendly | -3 | Receptive. Leaning in. Wants to help |
| Trusted | -6 | Almost automatic. They'd do it just because you asked |

**Disposition shift on success/failure:**

| Outcome | Persuasion Effect | Deception Effect | Intimidation Effect |
|---|---|---|---|
| Success by 10+ | +2 disposition (they're genuinely impressed) | +1 disposition (they believe completely) | +1 disposition (respectful fear) but -1 if they later learn the truth |
| Success by 5+ | +1 disposition | +1 disposition | +0 (compliance without warmth) |
| Bare success (0-4) | +0 (they agree but aren't moved) | +0 (they buy it, barely) | -1 disposition (resentful compliance) |
| Failure by 1-4 | +0 (they decline politely) | +0 (they don't believe but don't suspect) | -1 disposition (offended) |
| Failure by 5+ | -1 disposition (they feel pushed) | -1 disposition (they suspect deception) | -2 disposition (hostile now) |
| Failure by 10+ | -2 disposition (insulted or angry) | -2 disposition + NPC becomes alert to future deception | -2 disposition + NPC may attack or call guards |

**Intimidation's double edge:** Intimidation achieves compliance but damages the relationship. A merchant who's intimidated into a discount will sell to you — then charge double next time, refuse service, or report you to guards. Persuasion is slower but builds lasting goodwill. This creates meaningful skill choice in social situations.

#### Tier 2 — Contested Social Exchanges

When the player tries to manipulate, deceive, or read someone who's actively resisting, both sides roll.

**Contested check:** Player's skill vs NPC's opposing skill.

| Player Action | Player Rolls | NPC Resists With | When It Happens |
|---|---|---|---|
| Lie to an NPC | Deception | Insight | Any attempt to deceive |
| Read an NPC's motives | Insight | Deception | Trying to detect lies or hidden agendas |
| Extract hidden information | Deception (Spy) or Persuasion (Diplomat) | Insight + WIS save | Spy's Extract Information, probing for gated knowledge |
| Plant false information | Deception | Investigation | Spy's Misdirection ability |
| Force compliance through fear | Intimidation | WIS save | Threatening in a way that demands action |

**Contested resolution:**

```python
def resolve_contested_social(character, skill, npc, npc_resist_skill):
    player_roll = d20() + character.skill_modifier(skill)
    npc_roll = d20() + npc.skill_modifier(npc_resist_skill)
    
    success = player_roll > npc_roll  # Ties go to the defender (NPC)
    margin = player_roll - npc_roll
    
    return ContestedResult(
        success=success,
        margin=margin,
        dramatic=True,  # Contested exchanges are always dramatic
        narrative_hint=get_contested_hint(margin),
        consequence=get_failure_consequence(skill, margin)  # Failed Deception: NPC notices
    )
```

**Failure consequences by skill:**

| Skill | Failed By 1-4 | Failed By 5+ |
|---|---|---|
| Deception | NPC doesn't believe you but doesn't suspect malice | NPC realizes you lied. Trust broken. Disposition -2. May become hostile |
| Insight | You misread the NPC. DM gives you incorrect information about their motives | You misread badly. DM gives convincing but wrong information. You act on a false read |
| Persuasion (contested) | NPC declines firmly. No disposition change | NPC feels manipulated. Disposition -1. Won't engage on this topic again |
| Intimidation (contested) | NPC stands firm and calls your bluff. Disposition -1 | NPC turns hostile. May attack. Calls for allies. Situation escalates |

#### Tier 3 — Structured Social Scenes

High-stakes social encounters that play out over multiple beats — negotiating with a faction leader, convincing a hostile group to surrender, brokering peace between warring NPCs. These use a structure parallel to combat phases.

**When Tier 3 triggers:**
- The Diplomat uses De-escalate during combat
- The player attempts to negotiate with a named NPC over a major decision
- A faction negotiation scene begins
- The player tries to convince a group (not just one NPC)

**Structured Social Scene Flow:**

```
1. OPENING — DM narrates the social battlefield
   Who's present, what's at stake, what disposition you're starting from.
   Spy/Diplomat Read the Room fires automatically: reveals most influential 
   person, their disposition, and one thing they want.

2. ARGUMENT PHASES (2-4 rounds, like combat phases)
   Each phase:
   a. Player makes an argument (their "declaration")
   b. Engine resolves: skill check vs DC (modified by disposition, 
      prior arguments, and NPC personality)
   c. DM narrates NPC response — disposition shifts visible through 
      body language and tone, not numbers
   d. NPC may counter-argue: player gets a "social reaction" — 
      Insight check to read the counter, or ability use (Objection, 
      Compelling Argument, etc.)

3. RESOLUTION — DM narrates the outcome
   Based on cumulative disposition shift across all phases:
   - Shifted disposition 2+ steps positive: NPC agrees fully
   - Shifted 1 step: NPC agrees partially or with conditions
   - No shift: Stalemate. NPC's position unchanged. Can retry later
   - Shifted negative: NPC is now more opposed than before. May escalate
```

**Argument categories (what the player can say):**

| Argument Type | Skill | Best Against | Weak Against |
|---|---|---|---|
| Appeal to reason | Persuasion | Scholarly NPCs, pragmatists | Emotional NPCs, zealots |
| Appeal to emotion | Performance or Persuasion | Emotional NPCs, crowds | Cold logicians, soldiers |
| Appeal to self-interest | Persuasion or Deception | Merchants, politicians, pragmatists | Idealists, devout NPCs |
| Threat | Intimidation | Cowards, self-preservationists | Soldiers, zealots, anyone with backup |
| Bluff | Deception | Trusting NPCs, those without information | Spies, Seekers, Insight-trained NPCs |
| Evidence | Investigation or relevant knowledge skill | Anyone (evidence is persuasive universally) | Requires actual evidence in inventory/knowledge |

**NPC resistance personality:**

Each NPC has a social resistance profile (defined in the NPC schema) that determines how they respond to different argument types:

| NPC Personality Tag | Vulnerable To | Resistant To |
|---|---|---|
| Pragmatic | Self-interest, reason, evidence | Emotion, threats |
| Emotional | Emotion, performance, personal appeals | Cold logic, intimidation |
| Suspicious | Evidence only | Everything else (high Insight) |
| Cowardly | Threats, intimidation | Nothing (low WIS saves across the board) |
| Devout | Appeals aligned with their god | Appeals opposing their god, threats |
| Greedy | Self-interest, bribes | Emotion, duty appeals |
| Honorable | Reason, evidence, genuine respect | Deception, threats, manipulation |

**De-escalate in combat (Diplomat ability):**

When a Diplomat uses De-escalate during Beat 3 of a combat phase, combat pauses and a **mini-structured social scene** begins:

1. The Diplomat declares De-escalate (3 Focus cost)
2. CHA vs highest enemy WIS. Success: combat pauses for 1 round. All attacks stop
3. The Diplomat speaks — one argument phase. The player actually talks to the enemy
4. If the argument succeeds (disposition shifts positive): enemies may surrender, negotiate, or withdraw. Combat may end entirely
5. If the argument fails: combat resumes next phase. De-escalate can't be used again this encounter

This is the Diplomat's ultimate expression — ending a fight with words. In voice play, the player actually delivers the argument. The engine resolves whether it works. The DM narrates the enemy's response. When it works, it's the most satisfying moment in the game.

### Social Abilities Quick Reference

| Ability | Archetype | Tier | Effect in Social Resolution |
|---|---|---|---|
| Compelling Argument | Diplomat | 1 (Simple+) | Advantage on Persuasion/Deception + success shifts disposition 1 extra step permanently |
| De-escalate | Diplomat | 3 (Structured) | Pause combat, initiate social scene. CHA vs WIS. Can end combat |
| Diplomatic Immunity | Diplomat | 1 (Simple) | Can initiate conversation with hostile creature — 1 round of immunity from attack |
| Reputation Precedes You | Diplomat | 1 (Simple) | Starting disposition one step higher in civilized areas |
| Kingmaker | Diplomat | 1 (Simple) | Faction rep gains doubled. Disposition improvements are 2 steps instead of 1 |
| Voice of Authority | Diplomat | 3 (Structured) | De-escalate works on groups (up to 6). Auto-succeed Persuasion DC ≤ 15 in formal settings |
| Honeyed Words | Spy | 1 (Simple) | Advantage on next Deception/Persuasion/Intimidation |
| Read the Room | Spy/Diplomat | 1 (Simple) | Entering social encounter: DM reveals most influential NPC, disposition, one thing they want |
| Extract Information | Spy | 2 (Contested) | Deception vs Insight. Success: DM reveals one hidden thing from NPC's knowledge gates. Fail: NPC notices probing |
| Deep Cover | Spy | 2 (Contested) | Maintain 3 identities. Magical truth detection must beat Deception |
| Plausible Deniability | Spy | 2 (Contested) | When accused: Deception reaction. Success: accuser doubts their own evidence |
| Puppet Master | Spy | 3 (Structured) | Once/session: control one NPC's actions through social manipulation. No magic, no save — just words |
| Silver Tongue | Bard | 1 (Simple) | Advantage on next Persuasion/Deception outside combat. Reusable (2 Focus each) |
| Inspire | Bard/Diplomat | 1 (Simple) | Grant ally a die for any roll — including social checks |
| Countercharm | Bard/Diplomat | 2 (Contested) | When ally targeted by social magic (Charm, Command): advantage on save |
| Incite | Diplomat | 3 (Structured) | Turn a crowd to a specific emotion. Persuasion vs highest WIS. Lasts 10 minutes |

### Social Encounter and the Disposition System

Social resolution feeds directly into the NPC disposition system (defined in the GDD's world simulation). Every social check result can shift an NPC's disposition, which affects:

- **Prices** — Friendly merchants charge less (0.9×). Hostile merchants charge more (1.2×) or refuse service
- **Knowledge gates** — NPCs reveal information only at certain disposition thresholds. A successful Persuasion that shifts disposition from Neutral to Friendly may unlock gated knowledge
- **Quest access** — Some quests only become available at Friendly+ disposition
- **Workspace access** — Standing forge/lab access requires Trusted disposition (see crafting doc)
- **Mentor availability** — Technique mentors require specific disposition levels before they'll teach

This means every social interaction has potential mechanical consequences beyond the immediate conversation. Befriending the blacksmith over multiple visits doesn't just feel good — it unlocks cheaper repairs, standing forge access, and eventually a mentor relationship. Intimidating the blacksmith gets you what you want today and locks you out tomorrow.

### What Social Encounters Do NOT Include

- **No social HP.** NPCs don't have a "willpower pool" that depletes. Disposition shifts are the social currency
- **No social initiative.** The player always speaks first (they initiated). NPCs respond. The DM manages conversational flow naturally
- **No social combat grid.** No positioning, no flanking, no area of effect. Social encounters are pure dialogue
- **No forced outcomes.** The player can always walk away from a social encounter. A failed negotiation isn't a combat loss — it's a closed door that might open differently later
- **No mind control without magic.** Even the Diplomat's L20 Puppet Master is described as social manipulation, but mechanically it works because the NPC's disposition has been shifted so far that compliance is natural, not forced

---

## Travel and Exploration

> **Design principle:** Travel in a voice-first game is narration, not a loading screen. Safe routes are compressed ("Three days on the trade road. You arrive at sundown."). Dangerous routes are gameplay — encounters, decisions, resource management. The player never manages movement speed or hex grids. They say where they want to go; the engine and DM handle everything else.

### Travel Modes

The rules engine determines travel mode based on route danger level (from world data), player level relative to the region, and current world state (corruption levels, active events).

| Mode | When It Triggers | What Happens | Player Experience |
|---|---|---|---|
| **Compressed** | Safe routes between known settlements. Player level significantly above region threat | DM narrates a brief travel montage (2-3 sentences). Time passes. Arrive at destination | "The road south is quiet. Kael points out wildflowers he hasn't seen since childhood. By evening, the walls of the Accord rise ahead of you." ~15 seconds |
| **Scenic** | Moderate routes. First time traveling a path. Interesting terrain | DM narrates the journey with environmental detail and companion conversation. No combat, but atmosphere and worldbuilding. 1-2 decision points (route choice, camp location) | 2-5 minutes of narrated travel with ambient audio shifting. The journey IS content — the player learns about the world |
| **Dangerous** | Routes through hostile territory. Near the Ashmark. Hollow-corrupted regions. Night travel | Full gameplay: random encounter checks, navigation decisions, resource management, possible combat. The journey is an adventure | 5-15 minutes. Multiple encounters, skill checks, and decisions. Exhaustion tracking activates |

### Travel Time

Travel time is abstract — measured in narrative beats, not hours. The world simulation tracks in-game time for NPC schedules and world events, but the player experiences time through the DM's narration, not a clock.

| Distance | Compressed | Scenic | Dangerous |
|---|---|---|---|
| Short (within a region, e.g., Accord to nearby village) | Instant narration. "You arrive." | 1-2 minutes narration | 5-10 minutes gameplay |
| Medium (adjacent regions, e.g., Accord to Millhaven) | Brief montage. ~30 seconds | 3-5 minutes narration | 10-20 minutes gameplay (may span session break) |
| Long (distant regions, e.g., Accord to Keldaran Holds) | Extended montage. ~1 minute | Not used — long routes always have encounters | 20+ minutes, possibly multiple sessions. Async travel bridge: begin in one session, encounter during async check-in, arrive in next session |

**In-game time passed:**

| Distance | Time Passed (world simulation) |
|---|---|
| Short | 2-6 hours |
| Medium | 1-2 days |
| Long | 3-7 days |

Time passing matters: NPC schedules advance, corruption spreads, faction events progress, companion errands may complete during travel. A long journey to the Keldaran Holds means the world moved while you walked.

### Travel Encounters

During Scenic and Dangerous travel, the engine rolls for encounters based on the route's encounter table (defined in world data per region).

```python
def roll_travel_encounter(route, player_level, world_state):
    base_chance = route.encounter_frequency  # 0.0-1.0
    
    # Modifiers
    if world_state.region_corruption > route.corruption_threshold:
        base_chance += 0.2  # Hollow spreading increases encounters
    if player_level > route.threat_tier * 5:
        base_chance -= 0.1  # Overleveled players encounter less on easy routes
    if route.time_of_day == "night":
        base_chance += 0.15  # Night travel is more dangerous
    
    if random() < base_chance:
        encounter = weighted_random(route.encounter_table)
        return TravelEncounter(
            type=encounter.type,  # "combat" | "social" | "environmental" | "discovery"
            entities=encounter.entities,
            narration_cue=encounter.narration_cue
        )
    
    return None  # No encounter this segment
```

**Encounter types during travel:**

| Type | Examples | Resolution |
|---|---|---|
| **Combat** | Bandit ambush, Hollow creatures, aggressive wildlife | Normal combat flow (phase-based). Companion participates |
| **Social** | Traveling merchant, lost traveler, patrol checkpoint, refugee caravan | Social encounter resolution (Tier 1-2). May offer trade, information, or quests |
| **Environmental** | Collapsed bridge, sudden storm, fog bank, corruption patch | Skill checks: Athletics to climb, Survival to navigate, Nature to identify danger. Failure costs time or resources |
| **Discovery** | Abandoned camp, hidden cave entrance, ancient waystone, gathering node | Exploration and investigation. May lead to loot, lore, or a side quest hook |

### Navigation and Getting Lost

In safe territory and on known roads, navigation is automatic — the DM narrates the route and you arrive. Navigation checks only matter in wilderness, underground, and corrupted areas.

| Terrain | Navigation DC | Failure Consequence |
|---|---|---|
| Established road | Auto-success | — |
| Known wilderness trail | 8 | Minor detour: +2 hours travel time |
| Unmarked wilderness | 12 | Lost: +4-8 hours, possible encounter in unfamiliar terrain |
| Dense forest (Thornveld) | 14 | Disoriented: random direction, +1d4 hours, companion grows concerned |
| Underground (Umbral Deep) | 16 | Seriously lost: +1d8 hours, exhaust 1 ration, risk dangerous encounter |
| Hollow-corrupted territory | 18 | Drawn toward corruption: player wanders into a more dangerous zone. Survival check or Hollowed Stage 1 exposure |

**Skill interactions:**
- **Survival** is the primary navigation skill. Expert Survival: navigate without landmarks. Master Survival: always know where you are
- **Nature** identifies environmental dangers before they become problems. Expert Nature: predict weather 24 hours ahead
- **Perception** spots ambushes, hidden paths, and gathering opportunities during travel
- **Vaelti Keen Senses** grants advantage on all Perception during travel — the party's scout
- **Sable** automatically detects Hollow corruption within 120 ft during travel — the Veil Sense passive fires

### Exhaustion During Travel

Extended travel in dangerous conditions causes Exhaustion (defined in Status Effects — cumulative -1 to all checks per stack, max 5, long rest removes 1).

| Condition | Effect |
|---|---|
| Forced march (travel beyond 8 hours in a day without rest) | 1 Exhaustion stack per additional 4 hours. CON save DC 12 (+2 per additional 4 hours) to resist |
| Travel without rations | 1 Exhaustion stack per day without food. 2 stacks per day without water |
| Travel through extreme weather (blizzard, desert heat, magical storm) | 1 Exhaustion stack per 4 hours exposed. CON save DC 14 to resist. Draethar immune to cold-based weather exhaustion |
| Sleeping in the open without bedroll/tent | Short rest quality reduced. Long rest doesn't remove Exhaustion stack |

**Endurance skill interaction:**
- Expert Endurance: forced march 24 hours without Exhaustion
- Master Endurance (Iron Constitution): Exhaustion caps at 3 stacks instead of 5. Short rests take 30 minutes instead of 1 hour

### Camp and Rest During Travel

During Scenic and Dangerous travel, the DM offers rest opportunities. Camp setup is a brief interactive scene:

**Camp decisions:**
- **Where to camp:** The DM describes 2-3 options with different tradeoffs (sheltered cave = safe but cold; roadside clearing = comfortable but exposed; hidden grove = requires Survival check to find but best of both)
- **Watch rotation:** If in dangerous territory, someone watches while others rest. Perception check during watch determines if ambush is detected. Companion can take a watch (uses their Perception). Sable's Alarm ability eliminates surprise during rest
- **Campfire:** Provides warmth, enables Field-tier crafting, and enables basic gathering nearby. But visible to enemies at night — Stealth-conscious players may choose no fire

**Rest quality during travel:**

| Camp Quality | Short Rest | Long Rest |
|---|---|---|
| No camp (sleeping on ground, no shelter) | -1 to rest recovery | Doesn't remove Exhaustion |
| Basic camp (bedroll, no fire) | Standard | Standard |
| Good camp (bedroll, fire, shelter) | +1 to recovery rolls | Removes 1 Exhaustion + heals 1d4 extra HP |
| Tent + fire + watch | +1 to recovery + no surprise risk | Full benefits. The ideal |

---

## Gathering and Resource Discovery

> **Design principle:** Gathering happens during travel and exploration, not as a separate activity. The player says "I search for herbs while we travel" or "I look for ore in this cave." The engine resolves with a skill check. This connects Survival (finding things), Nature (identifying them), and Crafting (knowing what's useful) to the material pipeline.

### Gathering During Travel

When the player declares they want to gather during travel, or the DM offers a discovery encounter, the engine resolves a gathering check:

```python
def resolve_gathering(character, region, material_type=None):
    # What skill to use
    if material_type in ["metals", "stone", "gems"]:
        skill = "survival"  # Finding mineral deposits
    elif material_type in ["wood", "plant", "herbs"]:
        skill = "nature"    # Identifying useful plants
    elif material_type in ["arcane_components"]:
        skill = "arcana"    # Sensing magical residue
    elif material_type is None:
        skill = "survival"  # General foraging — find whatever's here
    
    dc = region.gathering_dc
    roll = d20() + character.skill_modifier(skill)
    
    if roll >= dc + 10:
        result = "rich_find"   # Double quantity or find a rare material
    elif roll >= dc:
        result = "success"     # Find what you were looking for
    elif roll >= dc - 5:
        result = "partial"     # Find something, but not what you wanted (common material instead of uncommon)
    else:
        result = "nothing"     # Area is depleted or you missed it
    
    materials = select_materials(region.resource_table, result, material_type)
    time_cost = roll_time_cost(result)  # 30 min to 2 hours
    
    return GatheringResult(
        result=result,
        materials=materials,
        time_cost=time_cost,
        narration_cue=get_gathering_narration(result, materials, region)
    )
```

### Regional Resource Tables

Each region in the world data defines what materials can be found there:

| Region | Common Materials | Uncommon Materials | Rare Materials | Gathering DC |
|---|---|---|---|---|
| **Greyvale / Farmlands** | Medicinal herbs, wood, fiber | Quality wood, iron ore | — | 10 |
| **Thornveld / Deep Forest** | Medicinal herbs, wood, fiber, plants | Thornveld ironwood, rare herbs, spider silk | Corrupted heartwood, Thornveld amber | 12 |
| **Drathian Steppe** | Hides, bones, sinew, herbs | Razorwing feathers, dire bear parts | Steppe crystals | 12 |
| **Keldaran Mountains** | Iron ore, stone, wood | Keldaran steel, quality gems, cave wyrm parts | Power crystals, rare ores | 14 |
| **Sunward Coast / Wetlands** | Fish, saltwater plants, driftwood | Coral, pearl, tidecaller eel parts | Sea crystals | 12 |
| **Ashmark / Hollow territory** | Corrupted materials (tainted) | Hollow residue (rend shards, wrack cores) | Veil shards, spatial residue | 16 |
| **Underground / Umbral Deep** | Stone, fungus, cave materials | Rare ores, crystals, umbral crawler parts | Deep gems, ancient materials | 16 |

### Gathering Rules

**Time cost:** Gathering takes 30 minutes to 2 hours of in-game time (added to travel time). During compressed travel, gathering extends the journey. During scenic/dangerous travel, it happens during rest stops or discovery encounters.

**One gathering attempt per travel segment.** A player can't spam "I search for herbs" every 5 minutes. One attempt per route segment (settlement to settlement, or per half-day of dangerous travel). The companion can gather simultaneously on a separate check if directed.

**Skill-gated materials:** Some materials require specific skill tiers to even attempt gathering (defined in `game_mechanics_bestiary.md` — Material Catalog):
- Untrained: common materials only
- Trained: uncommon materials accessible
- Expert: rare materials, Hollow materials (requires Crafting: Expert for safe handling)
- Master: always find something. Rich find threshold reduced by 5

**Gathering as companion errand:** Instead of gathering personally during travel, the player can send the companion on an Acquisition errand for specific materials. Tam has a bonus for wilderness gathering; Lira for arcane components; Sable for natural/primal materials via scent.

### Gathering Nodes (Fixed Locations)

Some locations in the world data have fixed gathering nodes — specific places where materials are reliably found:

| Node Type | Examples | Availability | Special Rules |
|---|---|---|---|
| **Ore vein** | Mine entrance, exposed cliff face, cave wall | Respawns on simulation tick (1-3 days) | Requires pickaxe or Athletics check. Keldaran Mountains have the richest veins |
| **Herb garden** | Forest clearing, riverside, temple garden | Respawns 1-2 days | Nature check to identify. Some herbs only grow in specific seasons (world simulation) |
| **Crystal deposit** | Deep cave, volcanic vent, ancient ruin | Respawns 3-7 days (rare) | Arcana check to safely extract. Hollow-adjacent deposits may be tainted |
| **Timber stand** | Forest edge, lumber camp, fallen ancient tree | Respawns 7+ days (slow growth) | Survival check. Thornveld ironwood only found in deep Thornveld |
| **Salvage site** | Battlefield, abandoned camp, shipwreck | One-time (doesn't respawn) | Investigation check. Quality depends on what happened there |
| **Hollow residue pool** | Near breaches, corrupted ground, creature remains | Persistent (corruption doesn't clean itself) | Crafting: Expert required. Arcana to identify type. Always tainted — requires purification |

**Discovery:** Nodes aren't marked on the map by default. Players find them through exploration (Perception checks during travel), companion scouting errands, NPC tips (an herbalist mentions a good patch), or quest rewards (a miner tells you about a hidden vein). Once found, a node is marked on the player's map for return visits.

**Node depletion:** Fixed nodes deplete when gathered and respawn on the world simulation tick. A player who finds a rich herb garden can return periodically, but not strip it bare in one visit. Other players in multiplayer (Phase 2) can also deplete nodes — creating competition for prime gathering spots.

