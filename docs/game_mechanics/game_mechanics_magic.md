# Divine Ruin — Game Mechanics: Magic System & Spell Catalogs

> **Claude Code directive:** Read `game_mechanics_core.md` first for foundational systems. This document defines the three magic sources, the Resonance system, racial Veil interactions, and all spell catalogs.
>
> **Related docs:** `game_mechanics_core.md` (required), `game_mechanics_archetypes.md` (archetype spell progression tables), `game_mechanics_patrons.md` (patron Resonance modifiers)

---

## Magic System — The Three Sources and Resonance

### Cosmological Foundation

All magic in Aethos flows from the same ultimate origin — the **Wellspring**, the raw creative energy the Architects used to forge the world. But magic reaches practitioners through three fundamentally different channels. These are not flavor categories. They interact differently with the Veil, respond differently to the Hollow, and create different risks.

> **Before the Sundering:** The Veil was intact. It functioned like perfectly insulated shielding between Aethos and the Wellspring's residual energy beyond. Casters pulled from residue safely contained inside the barrier. No ripples escaped. No Resonance accumulated. Magic was reliable, predictable, and safe — studied like physics at Aelindra.
>
> **After the Sundering:** The Veil is cracked. When a caster reaches for energy, some of that reach leaks through the cracks. The Hollow — which fills available space like water fills a crack — notices. That leaking disturbance is **Resonance**.
>
> **The gods' paradox:** The cracked Veil means more raw Wellspring energy is accessible than in millennia. The gods are actually slightly *stronger* in the short term — but every divine miracle ripples through the damaged Veil. The gods are burning their own prison walls for fuel. Veythar's original goal (restoring divine power via the Wellspring) was tragically successful — at catastrophic cost.

### The Three Sources

#### Arcane Magic

**Source:** Ambient Wellspring residue woven into reality's fabric during creation.

**How it works:** Arcane casters reach into the world's structure and pull residual creative energy into patterns. They don't pray or commune — they manipulate the world's underlying magical substrate.

**Why Veythar governs it:** The Lorekeeper understood the Wellspring better than any other god. Arcane magic is applied Wellspring theory.

**Resonance interaction:** **Highest rate.** Arcane casting makes direct contact with ambient energy entangled with the Veil. Every spell sends ripples through the cracks.

**Resonance formula:** `Focus cost × 0.6` (round up)

**Hollow interaction:** Most vulnerable. The Hollow feeds on arcane disturbance.

**Overreach flavor:** Reality glitches — visual distortion, wrong colors, alien sounds.

**Archetypes:** Mage, Artificer, Seeker

#### Divine Magic

**Source:** Channeled through a god's divine filter, directly into the caster via the bond of patronage.

**How it works:** Divine magic doesn't touch the ambient field. It flows from deity → patron bond → caster. The god acts as a buffer, filtering Wellspring energy into safe, structured power.

**Why it's safer:** The divine filter absorbs most Veil disturbance. But the filter has limits — chain enough high-cost spells and the god's capacity to buffer is temporarily exceeded.

**Why it's weaker overall:** The gods are fading. Their capacity to channel power is slowly diminishing. Divine magic is reliable and uncorrupted but bounded by the patron's declining strength.

**Resonance formula:** `Focus cost × 0.3` (round up)

**Hollow interaction:** Most protected. The divine filter blocks Hollow attention.

**Overreach flavor:** Divine static — the god's voice cracks, the channel distorts, prayer echoes wrong.

**Archetypes:** Cleric, Paladin, Oracle

**Post-reveal implication:** When the truth about Veythar emerges, Veythar's divine filter is compromised. Resonance reduction for Veythar's followers worsens from 0.3× to 0.7× (approaching arcane rates). Other gods' followers are unaffected. This creates immediate mechanical pressure on Veythar Clerics: do they switch patrons (losing divine favor), keep faith in a weakened god, or embrace the danger?

#### Primal Magic

**Source:** The world's own immune response. Aethos is alive — its ecosystems actively resist the Hollow.

**How it works:** Primal casters don't reach for energy or channel a god. They listen to the world's protective response and amplify it. The Thornveld resists the Hollow; a Druid channels that resistance into power.

**Why it's geographically dependent:** Primal magic draws from the health of the local environment. In ancient, uncorrupted nature: abundant power, minimal Resonance. In cities: diminished, normal Resonance. Near the Hollow: the land is fighting for its life, and drawing on it further strains both the land and the caster.

**Resonance formula:** `Focus cost × (0.1 to 0.8)` based on terrain

| Terrain | Primal Resonance Multiplier |
|---|---|
| Ancient forest / sacred grove | 0.1 (near zero) |
| Healthy natural terrain | 0.2 |
| Farmland / settled natural areas | 0.3 |
| Small town / village | 0.4 |
| Large city | 0.5 |
| Damaged / scarred terrain | 0.6 |
| Hollow-adjacent territory | 0.7 |
| Actively Hollow-corrupted terrain | 0.8 |

**Hollow interaction:** Complex. The Hollow and nature are at war. Drawing primal power near corruption strains both sides.

**Overreach flavor:** Nature recoil — plants wither, animals flee, the ground shudders, the land is exhausted by the caster's demands.

**Archetypes:** Druid, Beastcaller, Warden

#### The Bard Exception

Bards draw from all three sources simultaneously — ambient energy shaped through performance (arcane), emotional resonance echoing the gods' creative act (divine), and the primal response of living things to music and story (primal). Their Resonance rate is **0.4× Focus cost** — between divine and arcane. They are the generalists of the magic system as they are the generalists of everything else.

---

### Resonance System

#### Overview

**Resonance** is a hidden per-caster stat that measures how much the local Veil fabric has been disturbed by the caster's magic in the current encounter. It is tracked by the rules engine and narrated by the DM. The player never sees a number.

#### Resonance States

| State | Resonance | Mechanical Effect | DM Narration |
|---|---|---|---|
| **Stable** | 0–4 | None. Normal casting. | Magic feels clean and controlled. No narration needed. |
| **Flickering** | 5–8 | All spells gain **+1 damage die** (free power) | Colors shift, sounds echo wrong, faint wrongness at edges. Elari sense it immediately. |
| **Overreach** | 9+ | All spells gain **+2 damage dice, +2 to spell DCs**. Each spell triggers a **Hollow Echo** roll. | Reality warps visibly. Sounds from nowhere. The air tastes wrong. Something is watching. |

#### Resonance Generation

```python
def resonance_generated(focus_cost: int, source: str, terrain: str = "normal") -> int:
    if focus_cost == 0:
        return 0  # cantrips generate no resonance
    
    multipliers = {
        "arcane": 0.6,
        "divine": 0.3,
        "primal": PRIMAL_TERRAIN_TABLE[terrain],
        "bard": 0.4,
        "divine_veythar_post_reveal": 0.7  # compromised filter
    }
    
    return math.ceil(focus_cost * multipliers[source])
```

#### Resonance Decay

- **Standard:** -1 per round at end of caster's turn
- **Human racial (Adaptive Resonance):** -2 per round
- **Full reset:** On short or long rest

#### Resonance Cap

No hard cap. Resonance can climb indefinitely. At 12+, Hollow Echo rolls get -3 modifier (worse outcomes). At 15+, -6 modifier. At 15+, the DM may also trigger a **Veil Fracture** event (narrative-scale consequence beyond the encounter).

#### Spell-to-Resonance Map

| Spell | Focus Cost | Arcane Res. | Divine Res. | Primal Res. | Notes |
|---|---|---|---|---|---|
| Any cantrip | 0 | 0 | 0 | 0 | Free cast, no Veil disturbance |
| Shield Spell / Bark Skin | 1 | 1 | 1 | 0–1 | Minimal defensive casting |
| Detect Magic | 1 | 1 | 1 | 0–1 | Sensing magic barely disturbs the Veil |
| Heal Wounds / Healing Touch | 2 | — | 1 | 1 | Healing is low-resonance (restorative, not destructive) |
| Mist Step | 2 | 2 | — | — | Teleportation tears the Veil locally — high Resonance for cost |
| Elemental Burst / Entangle | 3 | 2 | 1 | 0–2 | First meaningful Resonance cost |
| Bless / Inspire | 3 | — | 1 | — | Buff spells generate very low Resonance |
| Call Lightning | 4 | — | — | 1–3 | Nature-channeled. Outdoors near-free; indoors strains connection |
| Spiritual Weapon | 4 | — | 2 | — | Sustained conjuration. Moderate divine Resonance |
| Wild Shape | 4 Focus + 3 Stam | — | — | 1–2 | Transformation, not destruction. Low Resonance |
| Fireball | 5 | 3 | — | — | The benchmark. 3 Resonance pushes toward Flickering |
| Hypnotic Pattern | 5 | 3 | — | — | Mind-affecting magic disturbs the Veil significantly |
| Wall of Force | 5 | 4 | — | — | Creating solid reality from nothing. Very high disturbance |
| Mass Heal | 6 | — | 2 | — | Large divine channeling. Moderate Resonance despite high cost |
| Chain Lightning | 7 | 5 | — | — | Massive arcane expenditure. One cast can push into Flickering |
| Banishment | 7 | — | 3 | — | Sending something through the Veil. High Resonance even divine |
| Avatar (Cleric L20) | 3 rounds free | — | 5 | — | Channeling a god fully. The Veil screams |

#### Typical Encounter Resonance Progression (Arcane Mage)

- Round 1: Arcane Bolt (0) + Shield (1) = **1 total**. Stable.
- Round 2: Fireball (3) − 1 decay = **3 total**. Stable, but warming.
- Round 3: Chain Lightning (5) − 1 decay = **7 total**. **Flickering.** +1 damage die. DM narrates Veil shuddering.
- Round 4: Fireball (3) − 1 decay = **9 total**. **Overreach.** +2 dice, +2 DC. Roll Hollow Echo.

---

### Hollow Echo Table

Rolled on **d20** when a spell is cast at Resonance 9+. Apply modifiers: at Resonance 12+, subtract 3. At Resonance 15+, subtract 6.

| Roll | Echo Name | Mechanical Effect | Narrative Flavor |
|---|---|---|---|
| **17–20** | Nothing stirs | No side effect | The spell resolves cleanly — this time. The tension doesn't break. |
| **14–16** | Whisper | No mechanical effect. DM plants a narrative seed. | A voice that isn't a voice. A pressure behind your eyes. Something noticed you, but moved on. |
| **11–13** | Veil scar | A small patch of wrongness lingers where the spell was cast. Persists 1 hour. Creatures with Veil-sense feel it. | The air where your spell hit looks faintly bruised — a discoloration that shifts when you try to focus on it. |
| **8–10** | Sympathetic resonance | One random ally within earshot takes **1d4 psychic damage**. The Veil ripple hit them. | Your companion flinches, hand to their temple. "What was that?" The magic echoed through them. |
| **5–7** | Hollow attention | Caster gains **stage 1 Hollowed condition** (disadvantage on WIS checks until short rest). Something looked directly at you. | For a heartbeat, you see through the Veil. What looks back has no face, no form — just attention. Cold, vast, interested. |
| **2–4** | Reality fracture | Spell effect is **doubled** (damage, duration, area) — but Focus cost is retroactively doubled. If you can't pay the deficit, take the difference as psychic damage. | The spell tears open wider than intended. Power floods through — beautiful, terrifying, far more than you asked for. |
| **1 or less** | Breach | **Hollow creatures manifest.** Within 1d4 rounds, 1–3 minor Hollow creatures appear at the spell's location. The DM runs this as a combat complication. | The Veil splits. For one second, something pours through — not much, not yet, but enough. The wrongness has weight and it stays. |

**Table design notes:**
- Weighted toward mild/narrative effects (60% chance of nothing or whisper at Resonance 9)
- Severe consequences become likely only at high Resonance (12+, 15+) via the modifier
- Reality Fracture (2–4) is deliberately rewarding AND punishing — the peak risk-reward moment
- Breach (1 or less) is the only result affecting the whole party — memorable, rare, terrifying

---

### Veil Ward — Local Veil Reinforcement

A castable or deployable effect that locally stabilizes the Veil in an area.

#### Ward Effects

| Property | Without Ward | With Ward Active |
|---|---|---|
| Resonance generation | Standard rates | **Halved** (round down) |
| Hollow Echo rolls | Standard | **+4 bonus** (milder results) |
| Spell damage | Normal | **-1 damage die** |
| Spell DCs | Normal | **-1 DC** |

#### Ward Sources

| Source | Cost | Available At | Duration | Notes |
|---|---|---|---|---|
| Cleric (Divine Ward variant) | 4 Focus | Level 7 | Encounter or dismissed | Divine filter extended to area. Most reliable source |
| Druid (Nature's Bastion) | 5 Focus | Level 9 | Encounter (natural terrain only) | Stronger in old-growth / sacred groves |
| Artificer (Veil Anchor) | Crafted item | Level 7 | Placed object, 1 hour | Craftable, deployable, plannable. The tactical option |
| Paladin (Sanctified Ground) | 3 Focus + 3 Stam | Level 10 | 3 rounds | Expensive, short, powerful. The emergency option |
| Sacred sites (world entity) | Passive | Always | Permanent | Temples, sacred groves, Dawnspire sanctuaries. Natural wards in the world |

#### Strategic Implications

- **Near the Ashmark / Hollow territory:** Veil Wards become near-mandatory. Ambient Resonance rates are elevated and every spell is more dangerous.
- **Clean territory (Sunward Coast, Accord of Tides):** Wards are unnecessary overhead. Mages can blast freely.
- **Boss fights:** Parties may deliberately choose to fight *without* a ward for the higher power ceiling, accepting Overreach risk.
- **Seasonal escalation:** As the Veil weakens across seasons, Wards become more necessary and more common — players feel world deterioration through gameplay.

---

### Racial Resonance Integration

Every race has a unique, mechanically distinct relationship with Resonance and the Veil.

#### Elari — Veil-sense (Passive)

**Mechanic:** Automatically sense Resonance states of self and all nearby casters. Sense Veil integrity in the local area. No check required — always on.

**Scaling with Arcana skill:**
- Innate (no Arcana needed): sense own state, sense nearby casters' states (Stable/Flickering/Overreach)
- Expert Arcana: sense approximate Resonance *levels* (not just state) of nearby casters
- Master Arcana: sense regional Veil integrity — the Elari becomes a walking Veil-weather station

**Bonus:** Arcana starts at Trained at character creation (free). +1 to all Resonance-related Arcana checks.

**Narrative:** The Elari feels the Veil the way others feel temperature. Near the Ashmark, the constant wrongness is physically uncomfortable.

#### Human (Thael'kin) — Adaptive Resonance (Passive)

**Mechanic:** Resonance decay rate is **2 per round** instead of 1. Humans acclimate to Veil disturbance faster than any other race.

**Practical effect:** A Human Mage can spike into Flickering, get the +1 die power boost, and drop back to Stable in 2 rounds instead of 3-4. Enables an aggressive "dip and recover" casting pattern.

**Narrative:** Humans don't sense the Veil, but their magic recovers from disturbance faster — the same adaptability that defines the race in everything else.

#### Vaelti — Hyper-awareness (Passive)

**Mechanic:** When a Hollow Echo is rolled, the Vaelti gets a **1-round advance warning** before the effect manifests. Advantage on saves against Hollow Echo effects.

**Practical effect:** The Vaelti is the party's early warning system against Overreach consequences. "Something is coming through" gives the party one round to prepare — reposition, ready defenses, brace.

**Narrative:** The Vaelti's sharp senses catch the ripple before the wave. When the Mage's Overreach triggers a Breach, the Vaelti shouts warning a heartbeat before the creatures appear.

#### Korath — Earth-anchored (Passive)

**Mechanic:** When in contact with earth or stone (underground, outdoors on natural ground), generate **-1 Resonance** on primal spells (minimum 0). The earth absorbs Veil disturbance.

**Practical effect:** Most impactful for Druids and Wardens. Underground, Korath casters are the safest in Aethos.

**Narrative:** "The stone absorbs it," a Korath Druid explains simply. Underground, their magic barely disturbs the Veil.

#### Draethar — Inner Fire (Active, 1/encounter)

**Mechanic:** Once per encounter, reduce current Resonance by **3**, but take **1d6 fire damage** (self-inflicted, cannot be reduced). The inner fire purges Veil disturbance.

**Practical effect:** A pressure valve for Draethar casters who push too hard. Can drop from Overreach back to Flickering, or from Flickering to Stable, at the cost of HP.

**Narrative:** The Draethar's skin glows. Heat ripples outward. The wrongness recoils from the fire — ancient, primal, incompatible with the Hollow's cold strangeness.

#### Thessyn — Deep Adaptation (Evolving, Long-term)

**Mechanic:** After **10+ sessions** with regular Overreach exposure, a Thessyn gains a permanent **+1 to the Flickering threshold** (shifts from 5–8 to 6–9). Their body acclimates to the damaged Veil.

**Practical effect:** The only race that becomes mechanically better at handling Resonance over time. Long-term investment that rewards committed players who push their limits.

**Narrative:** "Your fingers have developed a faint luminescence that wasn't there six months ago. The wrongness doesn't feel as wrong anymore." The DM narrates physical changes as the Thessyn adapts.

---

### Resonance Sensing (Non-Elari)

For non-Elari characters, sensing Resonance requires investment in the **Arcana skill**.

| Arcana Tier | Self Resonance | Others' Resonance | Veil Condition |
|---|---|---|---|
| Untrained | DM narrates own state automatically | Cannot sense | Cannot sense |
| Trained | Own state narrated | Vague sense on check ("something feels off") | Vague on check |
| Expert | Own state narrated | Tactical info on check ("one more big spell and things get dangerous") | Meaningful detail on check |
| Master | Own state narrated | Near-Elari sensitivity, but still active (requires check) | Near-Elari sensitivity on check |

**Key difference from Elari:** Non-Elari sensing is always *active* (requires an Arcana check and deliberate attention), never passive. The Elari advantage is that their sense is always on — they never have to ask.

**DM implementation:** The DM always narrates a caster's own Resonance state without a check (every caster feels their own magic straining). Sensing others or the environment requires either Elari heritage or an Arcana check.

---

## Arcane Spell Catalog

> **Casting model:** Players name spells explicitly. Spells appear on the character sheet as they're learned and prepared. The DM calls the rules engine with the exact spell name. No fuzzy matching, no intent resolution.

### Catalog Structure

Every spell entry includes:
- **Focus cost** and **Resonance generation** — for the rules engine
- **Narration cue** — for the DM's narrative packet (not a script, a mood/image to draw from)
- **Audio cue** — maps to the audio design doc's SFX catalog, auto-pushed to client on cast

### Cantrips (0 Focus, 0 Resonance)

| Spell | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|
| **Arcane Bolt** | Single | 60 ft | Instant | Ranged spell attack. 1d6 force + INT mod. Scales: 2d6/L5, 3d6/L11, 4d6/L17. | A streak of raw arcane energy — crackling, colorless, fast. | CMB-008 |
| **Frost Touch** | Single (melee) | Touch | Instant | Melee spell attack. 1d6 cold + target speed -10 ft until end of next turn. Scales with level. | Your hand closes and the cold bites deep — frost crackles across skin. | CMB-007 |
| **Spark** | Single | 30 ft | Instant | Ranged spell attack. 1d4 lightning + target can't take reactions until your next turn. Scales with level. | A snap of electricity leaps — brief, blinding, disorienting. | CMB-008 variant |
| **Prestidigitation** | Object/area | 10 ft | 1 hour | Minor trick: light candle, clean, warm/cool, small sensory effect. No combat use. | A flick of the wrist and the candles catch, or the mud slides from your boots. | None (silent) |
| **Mage Light** | Object/point | Touch | 1 hour | 20 ft bright light + 20 ft dim. No concentration. | Light blooms from your fingertip — warm, steady, obedient. | Soft chime |

### Minor Spells (1-2 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Shield Spell** | 1 | 1 | 1 | Self | Self | Next turn | Reaction: +3 AC until start of next turn. Cast when attacked. | A shimmer of force snaps into existence — translucent, geometric, instant. | CMB-008 (soft) |
| **Detect Magic** | 1 | 1 | 1 | 30 ft radius | Self | Conc, 10 min | Sense presence and school of magic. Reveals items, spells, enchantments, wards. | Everything touched by magic shimmers faintly, each with different light. | Subtle shimmer |
| **Mage Hand** | 1 | 1 | 1 | Object | 30 ft | 1 min | Spectral hand manipulates objects up to 10 lbs. Can't attack. Sleight of Hand at -2. | A translucent hand materializes, fingers flexing with your intent. | Soft hum |
| **Magic Missile** | 2 | 1 | 1 | 1-3 targets | 60 ft | Instant | 3 darts auto-hit, 1d4+1 force each. Split between targets. L5: 4 darts, L11: 5, L17: 6. | Darts of light streak out, each finding its mark with perfect inevitability. | CMB-008 (triple) |
| **Mist Step** | 2 | 2 | 2 | Self | 30 ft (visible) | Instant | Teleport to visible location. Breaks line of sight. High Resonance for cost (Veil tear). | You dissolve into a smear of light and reconstitute somewhere else. | Displacement whoosh |
| **Arcane Lock** | 2 | 1 | 2 | Door/container | Touch | Until dispelled | Magically seal target. Force DC +10. Bypassed by Expert Arcana or Master Sleight of Hand. | The magic sinks in — the lock clicks with finality beyond any key. | Lock + magic hum |

### Standard Spells (3-4 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Elemental Burst** | 3 | 2 | 1 | 15 ft sphere | 60 ft | Instant | Choose fire/ice/lightning. DEX save. Fail: 2d6. Half on success. L7: 3d6, L13: 4d6. | Fire erupts / ice crystallizes / lightning arcs across the space. | CMB-006/7/8 |
| **Hold Person** | 3 | 2 | 3 | Single humanoid | 60 ft | Conc, 1 min | WIS save. Fail: Paralyzed (can't act, attacks have advantage, melee auto-crits). Re-save each turn. | They freeze mid-motion, eyes still moving, mouth struggling. | Low thrum + lock |
| **Counterspell** | 3 | 2 | 1 | Casting creature | 60 ft | Instant | Reaction: INT check vs DC 10 + enemy spell Focus cost. Success: spell negated. | You feel the magic building and reach out to unravel it. | Sharp crack + silence |
| **Dispel Magic** | 3 | 2 | 3 | Spell/effect | 60 ft | Instant | End one spell or magical effect. Higher-cost targets: INT check DC 10 + cost. Reduces target Resonance by 2. | The spell collapses inward like a knot pulled free. | Reverse shimmer |
| **Fly** | 3 | 2 | 4 | Self or willing | Touch | Conc, 10 min | Flying speed = walking speed. Falls if concentration broken. | Your feet leave the ground — the air holds you. | Rising wind |
| **Invisibility** | 3 | 2 | 3 | Self or willing | Touch | Conc, 1 hour | Invisible. Breaks on attack/offensive spell. Stealth advantage. Attacks against have disadvantage. | Light bends around you — first translucent, then gone. | Displacement hiss |

### Major Spells (5-6 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Fireball** | 5 | 3 | 5 | 20 ft sphere | 120 ft | Instant | DEX save. Fail: 3d6 fire. Half on success. Ignites. L11: 4d6, L17: 5d6. | A bead of light detonates — heat, light, the roar of air consumed. | CMB-006 (powerful) |
| **Lightning Bolt** | 5 | 3 | 5 | 100 ft line | Self (line) | Instant | DEX save. Fail: 3d6 lightning. Half on success. Line shape rewards positioning. L11: 4d6, L17: 5d6. | Lightning erupts in a searing line — everything struck simultaneously. | CMB-008 (sustained) |
| **Wall of Force** | 5 | 4 | 7 | 30 ft wall/dome | 60 ft | Conc, 10 min | Invisible, impassable. Nothing passes. Cannot be dispelled. 4 Resonance. | The air hardens. An absolute boundary. | Deep resonant hum |
| **Haste** | 5 | 3 | 5 | Single willing | 30 ft | Conc, 1 min | 2× speed, +2 AC, advantage DEX saves, extra action/turn. Ends: can't move/act 1 round. | Time bends — they blur, existing faster than the world allows. | Accelerating pulse |
| **Slow** | 5 | 3 | 5 | Up to 3 creatures | 60 ft | Conc, 1 min | WIS save. Fail: speed halved, -2 AC, no reactions, action or quick action (not both). Re-save each turn. | The air thickens — movements drag, thoughts struggle. | Decelerating tone |
| **Arcane Eye** | 5 | 2 | 6 | Conjured sensor | 120 ft | Conc, 1 hour | Invisible sensor, see through it. 30 ft/round, passes through 1-inch gaps. Expert+ Arcana detects it. | You close your eyes and open another — somewhere else, silent, watching. | Soft hum |

### Supreme Spells (7+ Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Chain Lightning** | 7 | 5 | 9 | 1 primary + 3 secondary | 120 ft | Instant | Primary: 4d6 lightning (DEX half). Arcs to 3 within 30 ft: 2d6 each (DEX half). Can't arc same target. | Lightning strikes the first and leaps — finding the next body and the next. | CMB-008 + arcs |
| **Disintegrate** | 7 | 5 | 9 | Single | 60 ft | Instant | Ranged spell attack. Hit: 5d6+20 force. If reduces to 0 HP: disintegrated (no body, no death saves). Miss: nothing. | A thin green ray — where it touches, matter ceases. Absence. | Charge → silence |
| **Teleport** | 7 | 5 | 9 | Self + up to 4 | Touch | Instant | Teleport to previously visited location. Familiarity affects accuracy. 5 Resonance. | The world folds. An instant of being in both places. | Reality bending |
| **Power Word: Stun** | 7 | 4 | 9 | Single | 60 ft | Until saves | If target ≤75 HP: auto-Stunned. CON save each turn. If >75 HP: fails silently. Caster doesn't know HP — a gamble. | A syllable that collapses thought. They stop. Everything stops. | Subsonic pulse |
| **Maze** | 7 | 4 | 8 | Single | 60 ft | Conc, 10 min | Target vanishes into extradimensional maze. No initial save. INT check DC 20 each round to escape. | Space opens beneath them — they fall into somewhere that shouldn't exist. | Spatial distortion |
| **Meteor Swarm** | 8 | 6 | 10 | 4 × 20 ft spheres | 300 ft | Instant | 4 meteors, DEX save each. Fail: 4d6 fire + 4d6 bludgeoning. Half on success. Areas can overlap. 6 Resonance. | The sky splits. Four streaks descend like the fists of an angry god. | Whistle → quad detonation |
| **Time Stop** | 8 | 6 | 10 | Self | Self | 1d4+1 turns | Time stops for all except you. Directly affecting another creature ends it. Preparation, not attack. 6 Resonance. | The world freezes mid-breath. Only you move, alone in a silent instant. | All sound ceases → heartbeat |

### Arcane Catalog Summary

| Tier | Count | Focus Range | Resonance Range |
|---|---|---|---|
| Cantrip | 5 | 0 | 0 |
| Minor | 6 | 1-2 | 1-2 |
| Standard | 6 | 3 | 2 |
| Major | 6 | 5 | 2-4 |
| Supreme | 7 | 7-8 | 4-6 |
| **Total** | **30** | | |

> **Remaining catalogs (Divine, Primal) are NOT YET DESIGNED.** They follow this same structure but with different spell identities. Divine spells emphasize healing, protection, anti-Hollow effects, and lower Resonance. Primal spells emphasize terrain manipulation, summoning, environmental control, and terrain-variable Resonance. Bard cross-source access draws from all three catalogs.

---

## Divine Spell Catalog

> **Source:** Divine magic is channeled through a god's filter. Resonance rate: Focus cost × 0.3 (halved vs Arcane). Several anti-Hollow and healing spells generate 0 Resonance — restoration stabilizes the Veil. Casting model: players name spells explicitly.
>
> **Identity:** The healer, protector, and authority. Divine spells are about relationships — with your god, your allies, and the forces that threaten them. Divine casters have the strongest anti-Hollow toolkit and the safest Resonance profile.

### Divine Cantrips (0 Focus, 0 Resonance)

| Spell | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|
| **Sacred Flame** | Single | 60 ft | Instant | WIS save (ignores armor). 1d6 radiant + WIS mod. Scales: 2d6/L5, 3d6/L11, 4d6/L17. | A pillar of golden light descends — not from the sky, but from somewhere beyond it. | CMB-009 variant (offensive radiance) |
| **Guiding Light** | Single ally | 30 ft | 1 round | Next attack roll against the target has advantage. No damage. | A faint halo settles over your ally's target — subtle, warm, marking them. | Soft radiant chime |
| **Mend** | Object/construct | Touch | Instant | Repair a single break or tear in an object. No combat application. | Your fingers trace the crack and the material remembers what it was. | Quiet crystalline tone |
| **Sacred Word** | Self (area) | 10 ft radius | Instant | Undead and Hollow within 10 ft take 1d4 radiant. Scales: 2d4/L5, 3d4/L11, 4d4/L17. Living unaffected. | You speak a word that has weight. The Hollow things recoil — not from sound, but from meaning. | Resonant spoken tone + radiant pulse |

### Divine Minor Spells (1-2 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Heal Wounds** | 2 | 1 | 1 | Single | Touch | Instant | Restore 1d8 + WIS mod HP. The fundamental healing spell. | Warmth flows from your hands into the wound. Flesh knits. Color returns. | CMB-009 (healing) |
| **Shield of Faith** | 2 | 1 | 1 | Single ally | 30 ft | Next turn | Reaction: +2 AC to an ally when attacked. May cause miss retroactively. | A shimmer of golden force interposes itself — not your shield, but your god's. | CMB-009 variant + deflection |
| **Bless** | 2 | 1 | 1 | Up to 3 allies | 30 ft | Encounter | Up to 3 allies gain +1d4 on attack rolls and saving throws. Concentration. | You speak their names and your patron hears. Each feels subtle warmth — certainty settling into bones. | Ascending choral tone |
| **Sanctuary** | 1 | 1 | 1 | Single | 30 ft | 1 minute | Enemies must WIS save before attacking target. Fail: must choose different target. Breaks if protected creature attacks. | A quiet falls around them. Something about them makes violence feel wrong. | Soft bell tone |
| **Detect Hollow** | 1 | 0 | 1 | Self (60 ft) | Self | Conc, 10 min | Sense presence, direction, intensity of Hollow corruption. Reveals hidden Hollow creatures, corrupted objects, Veil stress. 0 Resonance — divine sensing stabilizes the Veil. | Your perception shifts. Clean light where reality is whole, darkness where it frays. | Low harmonic drone |
| **Command** | 2 | 1 | 2 | Single | 60 ft | 1 round | One-word command (Halt, Flee, Drop, Kneel, Approach). WIS save. Fail: obeys next turn. Won't obey directly harmful commands. | You speak one word with divine authority. The target's body obeys before their mind can object. | Resonant authoritative tone |

### Divine Standard Spells (3-4 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Turn Undead/Hollow** | 3 | 1 | 2 | Area (30 ft) | Self | 1 minute | Undead and Hollow: WIS save. Fail: Frightened, must flee 1 min. At L5+: if creature HP < 5× your level, destroyed outright. | You raise your holy symbol and divine light pours out. The unnatural things shriek and scatter. | Radiant surge + creature recoil |
| **Spiritual Weapon** | 4 | 2 | 5 | Conjured weapon | 60 ft | 3 rounds | Spectral weapon themed to patron. Attacks independently: 1d8 + WIS/round. No concentration. Appearance matches patron. | A weapon forms from light and will — not yours, but your god's. It strikes with quiet, absolute purpose. | Weapon SFX + radiant shimmer |
| **Dispel Corruption** | 3 | 1 | 3 | Single/area | Touch | Instant | Remove Hollow corruption from object, area (10 ft), or creature. Ends stage 1 Hollowed. Stage 2+ needs Greater Restoration. Cleanses materials for crafting. Only 1 Resonance — purification stabilizes Veil. | Your hand presses to the corruption and light flows in. The wrongness resists — then breaks. | Reverse Hollow audio — wrongness unwinding |
| **Zone of Truth** | 3 | 1 | 3 | 15 ft radius | 60 ft | 10 minutes | All creatures: CHA save. Fail: cannot deliberately lie. Can be evasive, silent, or misleading by omission. Creatures know they're affected. | The air clears. Something in the space demands honesty — with the quiet insistence of a judge's gaze. | Subtle bell + low harmonic |
| **Prayer of Healing** | 4 | 1 | 3 | Up to 6 allies | 30 ft | 10 min (ritual) | Out-of-combat only. Over 10 minutes, restore 2d8 + WIS mod HP to up to 6 creatures. Deliberate rest and restoration. | You kneel and pray. The divine warmth seeps in slowly — not battle healing, but the steady warmth of being tended. | Extended gentle choral tone |
| **Beacon of Hope** | 3 | 1 | 4 | Up to 3 allies | 30 ft | Conc, 1 min | Advantage on WIS saves and death saves. Any healing received restores maximum HP (no roll — always max on dice). | Hope is not a feeling. It's a decision. Your prayer makes that decision easier. | Warm sustained tone |

### Divine Major Spells (5-6 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Mass Heal** | 6 | 2 | 5 | All allies in earshot | 60 ft | Instant | Restore 2d8 + WIS mod HP to all allies within earshot. The benchmark group heal. | The light finds every wound, every bruise, every ache. Everyone feels it at once. | CMB-009 (powerful, wide) |
| **Divine Ward** | 4 | 2 | 7 | Single ally | 30 ft | 1 round | One ally gains resistance to all damage (half) for 1 round. Patron interposes their will between ally and harm. | A shield that isn't a shield. The blow lands and seems diminished. Reduced. Judged insufficient. | Heavy radiant impact absorption |
| **Flame Strike** | 5 | 2 | 5 | 10 ft radius cylinder | 60 ft | Instant | DEX save. Fail: 2d6 fire + 2d6 radiant. Success: half. Radiant portion damages Hollow creatures even if fire-resistant. | A column of fire falls from above — not natural fire. This burns with purpose. | Descending fire + radiant harmonic |
| **Veil Ward** | 4 | 1 | 7 | 30 ft radius | Self | Encounter | Locally reinforce the Veil. All Resonance halved. Echo rolls +4. But spell damage -1 die, DCs -1. See Veil Ward section. | The Veil's cracks close slightly. Magic here is safer. Weaker. Controlled. | Deep stabilizing harmonic |
| **Revivify** | 5 | 2 | 5 | Single (dead) | Touch | Instant | Touch creature dead within last minute. Returns with 1 HP. Doesn't work on Hollow-killed (disintegrated, consumed, Hollowed 3+). Requires diamond (50 gc, consumed). | You press your hand to the still chest and refuse the threshold. A gasp. A heartbeat. They're back. | Silence → heartbeat → breath |
| **Commune** | 5 | 2 | 7 | Self | Self | 1 minute | Contact patron deity. Ask 3 yes/no questions. God answers truthfully but may answer "unclear." Veythar's answers may be deliberately misleading. | The world falls away. You are alone with your god — vast, attentive, ancient. | STG-006 (god whisper) + deity voice |

### Divine Supreme Spells (7+ Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Banishment** | 7 | 3 | 9 | Single | 60 ft | Conc, 1 min | Hollow creature: CHA save. Fail: sent beyond the Veil. If concentration held full minute, permanent. Non-Hollow: banished to demiplane for duration only. | You point and speak with your god's voice. Reality opens beneath the creature — a rejection. | Veil tearing (controlled) |
| **Greater Restoration** | 7 | 2 | 9 | Single | Touch | Instant | Remove one: any curse, disease, ability drain, Hollowed (any stage), Charmed, Petrified, or extra exhaustion reduction. The only reliable Hollowed cure. | Light that goes deeper than flesh — reaching into the pattern and straightening what was bent. | Deep healing tone + radiant surge |
| **Resurrection** | 8 | 3 | 10 | Single (dead) | Touch | Instant | Return creature dead up to 10 days to life, full HP. Diamond (500 gc, consumed). Soul must be willing. Doesn't work if soul passed beyond Mortaen's domain. Returns with 1 exhaustion. | This is negotiation with death itself. You reach across Mortaen's threshold and ask for them back. | Silence → STG-006 (Mortaen) → heartbeat |
| **Holy Aura** | 7 | 3 | 9 | All allies (30 ft) | Self | Conc, 1 min | Allies: advantage on saves, attacks against have disadvantage. Undead/Hollow that hit in melee: CON save or Blinded 1 round. Supreme protection. | Your god's presence fills the space — warm, golden, absolute. | Sustained radiant harmonic |
| **Divine Judgment** | 7 | 3 | 9 | Single | 60 ft | Instant | WIS save. Fail: 6d8 radiant + Stunned 1 round. Success: half, no stun. Against Hollow: damage increases to 8d8. | Your god looks through your eyes. The judgment is instant, absolute, and searing. | STG-006 (patron) → radiant detonation |
| **Miracle** | 8 | 4 | 10 | Varies | Varies | Varies | Request divine intervention. DM (as god) decides response. Can replicate any Standard-or-lower spell at 0 Focus. Can produce unique effects per patron domain. Can fail if it conflicts with god's agenda. Once per session. 4 Resonance. | You pray — truly, desperately — and your god answers. What happens next is theirs, not yours. | Full STG-006 → deity audio → effect audio |

### Divine Catalog Summary

| Tier | Count | Focus Range | Resonance Range |
|---|---|---|---|
| Cantrip | 4 | 0 | 0 |
| Minor | 6 | 1-2 | 0-1 |
| Standard | 6 | 3-4 | 1-2 |
| Major | 6 | 4-6 | 1-2 |
| Supreme | 6 | 7-8 | 2-4 |
| **Total** | **28** | | |

> **Key difference from Arcane:** Divine Resonance ranges are significantly lower. Multiple spells generate 0 Resonance (Detect Hollow, healing at Orenthel modifier). The highest Divine Resonance (Miracle at 4) is lower than the highest Arcane (Meteor Swarm at 6). Divine casters trade raw power for safety and anti-Hollow specialization.

---

## Primal Spell Catalog

> **Source:** Primal magic is the world's immune response. Resonance rate: Focus cost × 0.1 to 0.8, terrain-dependent (see terrain multiplier table in Resonance System section). Casting model: players name spells explicitly.
>
> **Identity:** Terrain as weapon. The world fights back. Primal spells are geographically dependent — devastating in ancient forests, diminished in cities, strained in Hollow territory. Several nature-communion spells generate 0 Resonance in natural terrain. Resonance values shown as ranges reflecting the terrain multiplier.
>
> **Druid preparation constraint:** Druids can only change spell preparation in natural terrain (must commune with the land).

### Primal Cantrips (0 Focus, 0 Resonance)

| Spell | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|
| **Thorn Whip** | Single | 30 ft | Instant | Melee spell attack at range. 1d6 piercing + pull 10 ft closer + WIS mod. Scales: 2d6/L5, 3d6/L11, 4d6/L17. | A vine lashes out — thorned, fast, hungry. It strikes and drags them toward you. | Whip crack + organic tearing |
| **Druidcraft** | Area/object | 30 ft | Instant/1 hr | Minor nature effect: bloom a flower, create sensory effect, predict weather 24 hours, light/snuff small flame. Utility. | You whisper to the world and it responds — a flower opens, a breeze shifts. | None (natural ambient) |
| **Produce Flame** | Self or single | 30 ft (thrown) | 10 min/instant | Conjure flame in hand (10 ft light). Can throw as ranged spell attack: 1d6 fire. Scales with level. | Fire blooms in your palm — drawn from the heat of the earth. It doesn't burn you. It knows you. | Soft ignition + crackling |
| **Shillelagh** | Staff/club held | Touch | 1 minute | Staff becomes magical. Uses WIS for attack/damage. Damage die becomes 1d8. Enables Druids to melee with WIS. | You grip the staff and the wood responds — harder, heavier, alive. | Wood resonance hum |
| **Gust** | Single or area | 30 ft | Instant | Push creature 5 ft (STR save), or push objects 10 ft, or create harmless wind. Minor control/utility. | The air obeys — a sharp push, scattered leaves, a campfire bending wrong. | Sharp wind gust |

### Primal Minor Spells (1-2 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Healing Touch** | 2 | 1 | 1 | Single | Touch | Instant | Restore 1d8 + WIS mod HP. Primal healing — the body remembers wholeness. | Your hand presses to the wound and the flesh remembers what it was. | CMB-009 variant (organic) |
| **Bark Skin** | 2 | 1 | 1 | Self | Self | Rest of round | Reaction: when hit, +2 AC for rest of round. Skin hardens to bark momentarily. | Your skin darkens, hardens — bark spreading from the point of impact. | Crackling organic armor |
| **Entangle** | 3 | 0-2 | 1 | 20 ft square | 60 ft | Conc, 1 min | Vines erupt. All in area: STR save. Fail: Restrained. Re-save each turn. Difficult terrain. Resonance: 0 natural, 2 urban. | The ground opens and vines pour upward — thick, thorned, grasping. | Erupting vegetation |
| **Speak with Animals** | 1 | 0 | 1 | Self | Self | 10 minutes | Communicate with animals. They understand speech, can communicate back (limited by intelligence). 0 Resonance. | The birdsong sharpens into meaning. The fox stops and really looks at you. | Nature ambient shift |
| **Goodberry** | 1 | 0 | 1 | Creates items | Touch | 24 hours | Create 5 berries. Each restores 1 HP and provides full day's nourishment. 0 Resonance — growth magic. | You cup your hands and life gathers — five small berries, warm, faintly glowing. | Soft organic growth chime |
| **Faerie Fire** | 2 | 1 | 2 | 20 ft cube | 60 ft | Conc, 1 min | DEX save. Fail: outlined in bioluminescent light. Can't be invisible. All attacks against have advantage. Potent group debuff. | Drifting motes of cold light cling to everything, outlining bodies in eerie luminescence. | Shimmering bioluminescent hum |

### Primal Standard Spells (3-4 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Call Lightning** | 4 | 1-3 | 3 | Single (repeated) | 120 ft | Conc, 10 min | Outdoor only. 2d8 lightning, DEX half. Subsequent rounds: another bolt for 2 Focus (no added Resonance). Res: 1 outdoors, 3 indoors. | The sky answers. A pause, then a focused lance of light finds exactly what you pointed at. | Atmospheric charge → targeted strike |
| **Plant Growth** | 3 | 0-1 | 3 | 100 ft radius | 120 ft | Instant/8 hr | Combat: area becomes difficult terrain (4× movement cost). Non-combat: double crop yields 0.5 mile radius 8 hours. Near-zero Resonance in nature. | The forest surges. Every vine thickens, every root rises. The land becomes its own fortress. | Deep organic growth rumble |
| **Conjure Animals** | 3 | 2 | 3 | Summoned creatures | 60 ft | Conc, 1 hour | Summon 2 wolves, 1 bear, or 4 hawks. Obey verbal commands, act on your turn. Disappear at 0 HP or when duration ends. | You call, and the wild answers — from the earth itself. Real, warm, willing. | Animal calls (species-appropriate) |
| **Protection from Hollow** | 3 | 0 | 3 | Single | Touch | Conc, 10 min | Advantage on saves vs Hollow effects. Hollow creatures have disadvantage attacking target. 0 Resonance — reinforces Veil around target. | You trace a pattern and the wrongness parts around them like water around stone. | Stabilizing hum + Hollow receding |
| **Water Breathing** | 3 | 1 | 3 | Up to 6 creatures | 30 ft | 24 hours | Breathe underwater for 24 hours. Also breathe normally above water. No concentration. | You press their chest and their lungs expand — the water will be air to them now. | Water bubble + breath shift |
| **Nature's Grasp** | 2 | 0-1 | 5 | Single | 30 ft | Instant | Reaction: enemy moves through natural terrain near you — roots restrain them. STR save. Fail: Restrained until end of turn. 0 Resonance in nature. | The ground reaches up and grabs — with the patient, absolute grip of ancient roots. | Sudden root eruption |

### Primal Major Spells (5-6 Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Wild Shape** | 4+3 Stam | 1-2 | 5 | Self | Self | Until 0 HP or dismissed | Transform to beast form with separate HP pool, natural attacks, beast senses. Focus AND Stamina cost. Can't cast in beast form until L10 (cantrips) or L20 (all). | Bones shift. Skin ripples. One terrible, exhilarating moment of being neither — then something new. | Organic transformation |
| **Wall of Thorns** | 5 | 1-3 | 7 | 60 ft wall | 60 ft | Conc, 10 min | Thorn barrier. Passing through: 2d6 piercing (DEX half). Full cover. Can encircle. Res: 1 forest, 3 urban. | A hedge of thorns thick as your arm, higher than a house, absolutely impassable. | Rapid violent plant growth |
| **Commune with Nature** | 3 | 0 | 5 | Self | 3 miles | Instant | Learn 3 facts about territory: terrain, water, plants/animals, Hollow corruption, settlements, powerful creatures. 0 Resonance — listening, not casting. | You press palm to earth. The land speaks in impressions — water here, corruption there, something wrong to the north. | Deep earth resonance |
| **Blight** | 5 | 2-4 | 5 | Single | 30 ft | Instant | CON save. Fail: 4d8 necrotic. Success: half. Plant creatures: max damage, no save. Nature's dark side — decay as weapon. Higher Resonance. | You reach for the opposite of growth. The target withers — color draining, life pulled out like thread. | Organic decay — drying, cracking |
| **Guardian of Nature** | 5 | 1-2 | 7 | Self | Self | Conc, 1 min | Choose: Great Tree (+10 temp HP, advantage CON saves, advantage attacks, difficult terrain 15 ft) or Primal Beast (+10 ft speed, advantage WIS, +1d6 force on weapons, darkvision 120 ft). | Nature pours into you — bark hardening skin, or predator instinct sharpening every sense. | Organic transformation (by form) |
| **Ice Storm** | 5 | 2-3 | 5 | 20 ft radius | 120 ft | Instant | DEX save. Fail: 2d8 bludgeoning + 2d6 cold. Success: half. Area becomes difficult terrain 1 round. The primal weather attack. | The temperature drops. Fist-sized hail hammers everything below. | CMB-007 variant + hail impact |

### Primal Supreme Spells (7+ Focus)

| Spell | Focus | Res | Level | Target | Range | Duration | Mechanic | Narration Cue | Audio |
|---|---|---|---|---|---|---|---|---|---|
| **Earthquake** | 8 | 3-5 | 10 | 100 ft radius | 500 ft | Conc, 1 min | All creatures: DEX save each round or prone + 2d6 bludgeoning. Structures take massive damage. Fissures open. Concentration spells broken. Res: 3 nature, 5 urban. | The earth moves. The ground buckles, cracks, rises and falls like a breathing thing. | Deep seismic rumble → cracking |
| **Tsunami** | 8 | 3-5 | 10 | 300 ft wide wall | Sight | Conc, 6 rounds | Wall advances 50 ft/round. STR save. Fail: 3d8 bludgeoning + carried. Success: half, not carried. Requires nearby water. Res: 3 near water, 5+ forced. | The ocean rises. Not a wave — a wall. It hangs, then comes for everything. | Building roar → crashing impact |
| **Regenerate** | 7 | 2 | 9 | Single | Touch | 1 hour | 4d8+15 HP immediately. Then 1 HP/round for 1 hour. Regrows severed limbs over full duration. Supreme primal healing. | Life flows in and doesn't stop — the body repairs with the patience of a forest regrowing after fire. | Sustained organic healing tone |
| **Animal Shapes** | 7 | 3 | 9 | Up to 6 willing | 30 ft | Conc, 24 hours | Transform up to 6 creatures into beast forms (max CR = level/4). Each has separate beast HP. Tactical party transformation. | You speak beast names and allies hear the call in their bones. One by one they change. | Cascading organic transformations |
| **Feeblemind** | 7 | 4 | 9 | Single | 120 ft | Instant | INT save. Fail: INT and CHA drop to 1. Can't cast, use magic items, understand language. Save repeats every 30 days. Only Greater Restoration ends it. High Resonance — tears at fundamental nature. | You reach into their mind and pull. Not a thought — the capacity for thought. | Psychic collapse |
| **Storm of Vengeance** | 8 | 5 | 10 | 360 ft radius | Sight | Conc, 1 min | Escalates each round. R1: DEX or Deafened. R2: acid rain 1d6. R3: lightning 3d6 to 6 targets. R4: hail 2d6. R5+: blizzard, difficult terrain, 1d6 cold/round. Mounting apocalypse. | You give the sky permission. What follows is weather with intent. | Building storm: wind → rain → thunder → hail → blizzard |

### Primal Catalog Summary

| Tier | Count | Focus Range | Resonance Range |
|---|---|---|---|
| Cantrip | 5 | 0 | 0 |
| Minor | 6 | 1-3 | 0-2 |
| Standard | 6 | 2-4 | 0-2 |
| Major | 6 | 3-5 | 0-4 |
| Supreme | 6 | 7-8 | 2-5 |
| **Total** | **29** | | |

> **Key difference from Arcane and Divine:** Primal Resonance is shown as ranges because it depends on terrain. The same spell can generate 0 Resonance in an ancient forest and 4 in Hollow-corrupted territory. This makes the Druid's geographic position a core tactical consideration. Multiple communion spells (Speak with Animals, Commune with Nature, Goodberry, Protection from Hollow) generate 0 Resonance in natural terrain — the world wants to be listened to.

---

## Three-Source Catalog Comparison

| Property | Arcane (30 spells) | Divine (28 spells) | Primal (29 spells) |
|---|---|---|---|
| **Damage ceiling** | Highest (Meteor Swarm 8d6) | Moderate (Divine Judgment 6d8/8d8 vs Hollow) | High but terrain-dependent (Storm of Vengeance escalating) |
| **Healing** | None | Best (Mass Heal, Greater Restoration, Resurrection) | Good (Healing Touch, Regenerate) |
| **Control** | Strongest single-target (Hold, Maze, Time Stop) | Moderate (Command, Banishment, Zone of Truth) | Strongest area in nature (Entangle, Plant Growth, Earthquake) |
| **Anti-Hollow** | None specific | Best (Turn Hollow, Dispel Corruption, Protection, Banishment) | Good in nature (Protection from Hollow, 0-Res sensing) |
| **Resonance risk** | Highest and fixed (0.6× cost) | Lowest and filtered (0.3× cost) | Variable by terrain (0.1× to 0.8× cost) |
| **Total spells** | 30 | 28 | 29 |
| **Bard access** | Yes (cross-source) | Yes (cross-source) | Yes (cross-source) |

> **Total spell catalog: 87 spells** across all three sources. Each source has a distinct identity, Resonance profile, and tactical role. The Bard's cross-source access (electives from any catalog) makes them the most versatile caster at the cost of smaller pools.

