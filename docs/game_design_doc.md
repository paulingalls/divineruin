# Divine Ruin: The Sundered Veil — Game Design Document

## About This Document

This is the comprehensive game design document for **Divine Ruin: The Sundered Veil**. It defines every player-facing system: character creation, classes, progression, combat, navigation, async play, PvP, moderation, monetization, and the opening experience.

**Related documents:**
- *Product Overview* — What we're building and why (start here if you're new)
- *Aethos Lore Bible* — World history, cosmology, the pantheon, the core mystery
- *Audio Design Document* — Sound design philosophy, environmental soundscapes, voice design, combat audio, music system, AI generation prompts, MVP asset inventory
- *MVP Specification* — Scoped first build, success criteria
- *Technical Architecture* — DM agent architecture, orchestration, voice pipeline, multiplayer, infrastructure
- *World Data & Simulation* — Content authoring format (JSON schemas), world simulation rules, data model
- *Cost Model* — Per-session and subscriber unit economics

---

## Character Creation — A Narrated Experience

### Philosophy

Character creation is a **conversation with the DM**, not a menu. Every choice is made through voice interaction, immersing the player in the medium from the first moment.

### The Creation Flow

**1. Awakening — Race Selection**

The DM narrates the player into consciousness. Sensory details guide the choice:

> *"You open your eyes. The world sharpens around you. What do you see when you look at your hands?"*

The player is offered descriptions — not stat blocks — that convey the feel of each race:
- The warmth radiating from dense, powerful hands (Draethar)
- Long, fine fingers that tingle with awareness of something beyond the visible (Elari)
- Broad hands, skin with a faint mineral sheen, solid as the stone beneath you (Korath)
- Quick, nimble hands, every nerve alive to the air currents around them (Vaelti)
- Hands that feel... adaptable, as though they could become anything given time (Thessyn)
- Steady, capable hands — unremarkable except for the determination behind them (Human)

The DM elaborates on whatever interests the player. The choice is confirmed through conversation, not a button press.

**2. Origins — Culture Selection**

> *"Where do you call home? What sounds do you hear when you think of the place you grew up?"*

The DM paints each culture through its audio identity — the market bustle of the Sunward Accord, the wind and hoofbeats of the Drathian Steppe, the layered forest sounds of the Thornveld. The player chooses a cultural background that determines their starting region, initial worldview, and NPC connections.

Culture selection also establishes **starting relationships**: family, mentors, childhood friends — NPCs who will recur throughout the player's journey and give the early game emotional grounding.

**3. Calling — Class Archetype Selection**

> *"When danger comes — and it always comes — what is your instinct? To fight? To understand? To protect? To slip away unseen?"*

The DM explores the player's instincts through hypothetical scenarios rather than presenting a class list. The responses guide the player toward an archetype that fits their natural playstyle. Players can also simply state what they want to be.

**4. Devotion — Divine Patronage**

> *"Do you pray? And if so, who answers?"*

The player chooses a patron deity — or chooses none (a valid path with its own implications). The DM briefly introduces the gods relevant to the player's archetype and background, with personality-driven descriptions rather than mechanical ones. A player can also defer this choice, encountering the gods through play and committing later.

**5. Identity — Name and Backstory**

> *"And what do they call you?"*

The player names their character. The DM then collaboratively builds a brief backstory through conversation — a few key details that tie the character to the world. Where were you when the Ashmark last expanded? Do you know anyone who remembers Aelindra? What drives you forward?

This backstory feeds into the AI systems — the DM and NPCs will reference it throughout the game, making the player feel known.

### Creation Duration

Target: 10–15 minutes. Long enough to feel meaningful, short enough to not delay gameplay. Players who want to dive in fast can make quick choices; players who want to explore every option can take their time in conversation with the DM.

---

## Class System — Archetype + Divine Patronage

### Philosophy

A player's **base archetype** determines their mechanical toolkit. Their **divine patronage** flavors those abilities with unique powers, quest lines, and narrative identity. Any archetype can follow any god, but certain combinations have natural synergy.

### Base Archetypes

#### Martial Archetypes

**Warrior**
The front-line combatant. Excels at direct engagement, weapon mastery, and breaking through enemy defenses. In voice combat, the Warrior is decisive and aggressive — first to declare, first to strike.
- *Natural god synergy:* Kaelen (glory and martial excellence), Valdris (righteous combat)
- *Unexpected but viable:* Thyra (primal fury), Mortaen (death-dealer)

**Guardian**
The protector. Excels at defending allies, controlling space, and absorbing punishment. In voice combat, the Guardian is reactive — using the interrupt mechanic to shield others, calling out threats, directing the party's positioning.
- *Natural god synergy:* Valdris (defender of justice), Aelora (protector of community)
- *Unexpected but viable:* Orenthel (shield of hope), Kaelen (tactical defender)

**Skirmisher**
The mobile fighter. Excels at flanking, quick strikes, and exploiting openings. In voice combat, the Skirmisher is opportunistic — waiting for the right moment, then striking decisively.
- *Natural god synergy:* Kaelen (valorous strikes), Nythera (restless movement)
- *Unexpected but viable:* Syrath (shadow strikes), Thyra (predator instinct)

#### Arcane Archetypes

**Mage**
The classic spellcaster. Commands the ambient arcane energy of Aethos. In voice, casting is verbal — speaking incantations, describing intent, shaping magic through words. The most "voice-native" class.
- *Natural god synergy:* Veythar (arcane mastery), Zhael (fate-touched magic)
- *Unexpected but viable:* Thyra (elemental magic), Nythera (unknown energies)

**Artificer**
The maker of magical things. Crafts enchanted items, deploys constructs, and solves problems through invention. Bridges combat and the async crafting loop — an Artificer's between-session work directly produces session gear.
- *Natural god synergy:* Aelora (craft and innovation), Veythar (arcane engineering)
- *Unexpected but viable:* Kaelen (weapon-forging), Korath cultural affinity

**Seeker**
The arcane investigator. Uses magic to perceive, analyze, and uncover. The detective class — excels at finding hidden things, understanding magical phenomena, and piecing together clues. Central to the mystery questline.
- *Natural god synergy:* Veythar (pursuit of knowledge), Syrath (uncovering secrets)
- *Unexpected but viable:* Nythera (exploring the unknown), Zhael (reading the pattern)

#### Primal Archetypes

**Druid**
Channels the power of the natural world. Shapes terrain, commands weather, communicates with ecosystems. In voice, the Druid speaks *to* the world and it responds — a unique interaction style.
- *Natural god synergy:* Thyra (the wild mother's power)
- *Unexpected but viable:* Mortaen (cycle of decay and renewal), Orenthel (growth and renewal)

**Beastcaller**
Bonds with creatures of Aethos. Commands animal companions, communicates with wildlife, draws on bestial instincts. The companion adds a second voice to the party — the AI plays your bonded creature.
- *Natural god synergy:* Thyra (kinship with nature), Nythera (wild creatures of unknown places)
- *Unexpected but viable:* Kaelen (war beasts), Syrath (shadow creatures)

**Warden**
The primal guardian of places. Draws power from a specific location or region — a forest, a mountain, a stretch of coast. The Warden's strength is tied to the land, making them powerful in their home region and motivated to protect it.
- *Natural god synergy:* Thyra (steward of the wild), Valdris (guardian of sacred places)
- *Unexpected but viable:* Aelora (protector of settled lands), Mortaen (warden of burial grounds)

#### Divine Archetypes

**Cleric**
Channels divine power directly from a patron deity. The class most dramatically shaped by god choice — a Cleric of Orenthel heals, a Cleric of Kaelen inspires warriors, a Cleric of Syrath operates in shadow, a Cleric of Mortaen commands the boundary between life and death.
- *God synergy:* All gods. The Cleric is the universal divine class. God choice IS the subclass.

**Paladin**
The sworn champion. Combines martial prowess with divine mandate. Bound by an oath to their patron that grants power but constrains action — breaking the oath has consequences. In voice, the Paladin's oath is spoken aloud and becomes a narrative anchor.
- *Natural god synergy:* Valdris (oath of justice), Kaelen (oath of valor), Orenthel (oath of mercy)
- *Unexpected but viable:* Syrath (oath of shadows — covert divine agent), Thyra (oath of the wild)

**Oracle**
Touched by Zhael's domain regardless of formal patronage. Receives visions, reads patterns, speaks prophecy. The Oracle is a narrative wildcard — the DM can channel plot-relevant information through them, making them central to the mystery questline. Mechanically unpredictable — their abilities involve fate manipulation and probability shifting.
- *Primary god synergy:* Zhael (the Fatespinner's chosen)
- *Secondary patronage:* An Oracle can serve Zhael's domain while also following another god — a dual allegiance that creates unique roleplay tension.

#### Shadow Archetypes

**Rogue**
The classic skill specialist. Stealth, locks, traps, precision strikes. In voice, the Rogue excels at the quiet moments — scouting ahead, disabling traps before the party arrives, striking from surprise.
- *Natural god synergy:* Syrath (master of shadows), Nythera (scout and explorer)
- *Unexpected but viable:* Aelora (merchant-thief), Veythar (knowledge thief)

**Spy**
The social infiltrator. Disguise, deception, intelligence gathering. In a voice game, the Spy is remarkable — using their actual voice to deceive NPCs, talk their way past guards, and extract information through conversation. The PvP espionage layer's signature class.
- *Natural god synergy:* Syrath (the Veilwatcher's operative)
- *Unexpected but viable:* Valdris (undercover investigator), Veythar (academic spy)

**Whisper**
The shadow-magic hybrid. Uses subtle, undetectable magic — not fireballs but influence, misdirection, and manipulation. Spells that make guards look the other way, that plant suggestions, that erase memories. Ethically complex and narratively rich.
- *Natural god synergy:* Syrath (shadow magic), Zhael (fate manipulation)
- *Unexpected but viable:* Veythar (mind and memory magic), Mortaen (fear and death's touch)

#### Support Archetypes

**Bard**
The performer. In a voice-driven game, the Bard is the most natural class imaginable — you literally perform. Sing to inspire allies, tell stories to demoralize enemies, play music to heal or protect. Bard abilities could involve actual vocal performance by the player, with the AI DM and sound system responding to it.
- *Natural god synergy:* Aelora (the stories of civilization), Orenthel (songs of hope)
- *Unexpected but viable:* Kaelen (war songs), Zhael (songs of fate), any god (bards serve all stories)

**Diplomat**
The negotiator. Solves encounters through conversation, persuasion, and social leverage. In voice, the Diplomat is extraordinary — talking enemies into surrendering, brokering alliances mid-session, defusing conflicts through pure roleplay. May never swing a sword and still be the most valuable party member.
- *Natural god synergy:* Aelora (community builder), Valdris (arbiter of disputes)
- *Unexpected but viable:* Syrath (manipulation), Orenthel (compassionate mediation)

---

### Archetype Summary

| Category | Archetypes | Primary Combat Role |
|---|---|---|
| **Martial** | Warrior, Guardian, Skirmisher | Direct combat, protection, mobility |
| **Arcane** | Mage, Artificer, Seeker | Spellcasting, crafting, investigation |
| **Primal** | Druid, Beastcaller, Warden | Nature magic, companions, territorial power |
| **Divine** | Cleric, Paladin, Oracle | Healing, oaths, prophecy/fate |
| **Shadow** | Rogue, Spy, Whisper | Stealth, infiltration, subtle magic |
| **Support** | Bard, Diplomat | Performance, social problem-solving |

**Total: 16 archetypes across 6 categories, each modifiable by 10 possible divine patrons.**

---

## Progression System

### Philosophy

Progression should be tangible through audio. Attacks sound more powerful, spells more impressive, NPCs react to growing reputation, the DM's narration reflects evolution. Inspired by LitRPG/progression fantasy: leveling up should be visceral and satisfying.

### Dual-Track Progression

**Track 1: Archetype Mastery (XP and Levels)**
Traditional experience-based progression for the base archetype. Earned through combat, quest completion, exploration, and problem-solving. Each level unlocks new abilities, improves existing ones, and expands what the character can do mechanically.

- Level progression is steady and predictable — players always know they're growing
- Key level thresholds unlock archetype milestones (new ability tiers, specialization choices)
- XP is earned through all forms of play — combat, social encounters, crafting, exploration, mystery-solving
- No single playstyle is penalized; the Diplomat who never fights earns XP as readily as the Warrior

**Track 2: Divine Favor (Alignment and Devotion)**
Grows through acting in accordance with your patron deity's values — not just grinding, but *roleplaying in ways your god appreciates.* A follower of Kaelen gains favor through courageous combat and honorable conduct. A follower of Syrath gains favor through uncovering secrets and clever deception. A follower of Veythar gains favor through pursuing knowledge and solving mysteries. The god-agent heartbeat (simulation layer 3, every 15-30 minutes) evaluates player alignment and world state within each god's domain — see *World Data & Simulation — God-Agent Heartbeat*.

- Divine favor unlocks god-specific abilities, unique quests, and narrative rewards
- Favor can fluctuate — acting against your god's values can reduce it, creating meaningful roleplay tension
- High favor grants access to direct god interaction — whispers, visions, personal quests from your deity
- At peak favor, players may receive divine boons — powerful but temporary abilities granted for critical moments
- **Post-reveal implications:** Veythar's followers face a crisis when the truth emerges. Does their favor hold? Does Veythar withdraw? Do they choose a new patron?

**Track 3: World Reputation**
How the world perceives you. Built through actions, choices, and their consequences across sessions. Stored in the `player_reputation` state table per faction, with reputation tiers that unlock gameplay effects — see *World Data & Simulation — Faction Schema* for tier definitions and effects.

- Regional reputation: how each area of Aethos views you based on what you've done there
- Faction reputation: standing with each cultural group and divine following — tracked numerically, adjusted by simulation tick (layer 2) and player actions via game state mutation tools
- Personal legend: the stories NPCs tell about you, which grow and change over time
- Reputation affects NPC interactions, available quests, prices, access to restricted areas, and how the DM narrates your presence — the background process injects reputation context into the warm prompt layer
- In a voice game, reputation is *heard*: NPCs whisper your name, guards step aside, enemies hesitate

### Progression Audio Design

- **Level up:** A distinct, satisfying audio event. The DM acknowledges the milestone in narration.
- **New ability unlocked:** The first use of a new ability has enhanced audio — the player hears what they've become capable of.
- **Divine favor milestone:** The patron god speaks directly to the player. A personal, intimate moment.
- **Reputation shift:** NPCs begin reacting differently. The player hears their growing legend reflected in the world.
- **Thessyn adaptation:** For Thessyn characters, the DM narrates physical changes as they occur — a unique progression layer tied to race.

---

## Game Mechanics

### Philosophy: Narrative-First with Dramatic Dice

The fiction leads, not spreadsheets. Inspired more by lightweight systems (Powered by the Apocalypse) than heavy crunch (D&D 5e full rules). Heavy mechanical crunch doesn't translate well to voice-only interaction. The player should never need to do math, consult a table, or track complex resource pools. They describe what they want to do; the system handles the rest.

Mechanically, the DM requests checks and the rules engine resolves them — the DM never applies raw math. See *Technical Architecture — Dice & Mechanics Tools* for the hybrid model: the LLM decides *when* a check is needed, the rules engine decides *how* it resolves.

### Core Resolution Mechanic

**The d20 + modifier vs. difficulty class (DC) system.** Simple enough for the DM to apply consistently, familiar enough for RPG players to understand intuitively, and dramatic enough for the moments that matter. The player never needs to know the math — the DM narrates the tension and the result.

**How it works from the player's perspective:**
1. The player describes an action: "I try to convince the guard to let us through."
2. The DM decides if a check is needed. Trivial actions succeed automatically. Impossible actions fail automatically. Everything in between gets a roll.
3. The DM calls the appropriate mechanics tool (`request_skill_check`, `request_attack`, `request_saving_throw`). The rules engine rolls d20, adds the character's relevant modifier, and compares against the DC.
4. The result — and the `narrative_hint` — return to the DM. The hint tells the DM the emotional texture: "barely succeeded," "overwhelming success," "catastrophic failure," "close but not enough."
5. The DM narrates the outcome. A bare success sounds different from a triumph. A narrow failure sounds different from a disaster.

**The player hears:** "You step forward and meet the guard's eyes. There's a tense pause..." *[dice roll animation and audio cue on HUD]* "...and something in your voice convinces him. He steps aside — reluctantly, but he steps aside."

**What the player never hears:** "Roll a persuasion check. You got a 14, the DC was 13, so you pass by 1."

**Modifiers** come from three sources: base attribute (strength, dexterity, wisdom, etc.), skill proficiency (trained skills get a bonus), and situational modifiers (advantage from context, disadvantage from conditions). The rules engine calculates these automatically from the character sheet and current state.

**Difficulty classes** are set by the rules engine based on context, not arbitrary DM judgment. The DC for picking a simple lock is always 10. The DC for persuading a hostile NPC is based on their disposition score. The DC for a combat action accounts for the target's defenses. This keeps the system fair and consistent even though the DM is an AI that could otherwise drift.

### Skill System

Characters have a set of skills organized by attribute. Proficiency (trained vs. untrained) determines the modifier bonus. Skills are broad and overlap intentionally — the DM picks whichever skill best fits the player's described action.

**Physical:** Athletics, Acrobatics, Endurance, Stealth
**Mental:** Perception, Investigation, Arcana, Nature, History, Religion
**Social:** Persuasion, Deception, Intimidation, Insight, Performance

A player who says "I look around for anything unusual" might trigger Perception (noticing something) or Investigation (analyzing something) depending on the context. The DM decides; the player doesn't need to know which skill was used. This keeps the interaction conversational rather than mechanical.

**Proficiency grows through use.** The progression system (see above) includes skill advancement through practice — a player who frequently uses Persuasion gains proficiency faster than one who never talks to NPCs. This creates natural specialization without rigid class restrictions.

### Status Effects

Conditions that modify a character's capabilities. Applied by mechanics tools, tracked in the character's state, and automatically factored into future rolls by the rules engine. The DM narrates their presence; the persistent HUD bar shows active effect icons.

**Common effects:**

*Combat conditions:* Wounded (reduced max HP until rest), Stunned (skip next action), Poisoned (disadvantage on physical checks), Blessed (advantage on next roll), Shielded (damage reduction), Enraged (bonus damage, penalty to defense).

*Environmental conditions:* Exhausted (penalties accumulate with lack of rest), Blinded (disadvantage on attacks and perception), Frightened (disadvantage against the fear source, can't willingly move closer), Charmed (treats the source as a friendly ally, disadvantage on checks against them).

*Magical conditions:* Cursed (specific penalty defined by the curse source — could be anything), Inspired (bonus to creative or social checks), Hollowed (contact with Hollow corruption — escalates if untreated, eventually causing hallucinations and stat drain).

**The Hollowed condition** deserves special mention. It's unique to this game's fiction and creates a distinctive gameplay loop. Contact with Hollow creatures or prolonged exposure to corrupted areas risks Hollowing. Early stages are subtle — the DM narrates slight wrongness in how the player perceives the world. Middle stages introduce mechanical penalties and unreliable perception (the DM occasionally describes things that aren't there). Late stages are a crisis requiring urgent treatment. The tension between pushing deeper into corrupted territory and managing Hollowed status creates meaningful risk/reward decisions.

### Difficulty and Challenge Design

The rules engine scales challenge dynamically based on party composition and power level. The DM never needs to manually balance encounters.

**Encounter difficulty tiers:**
- **Trivial** — No rolls needed, automatic success, narrative flavor only
- **Easy** — Low DC, expected to succeed, builds confidence and teaches mechanics
- **Moderate** — Fair DC, success likely but not guaranteed, the baseline challenge
- **Hard** — High DC, failure is common, requires good tactics or character strengths
- **Deadly** — Very high DC, serious consequences for failure, reserved for climactic moments

**Scaling philosophy:** The world doesn't level with the player. The Greyvale ruins are dangerous for a level 1 character and trivial for a level 10 character. But the DM avoids sending players into content they can't handle by using the guidance system and quest design. If a player wanders toward a deadly area, the companion says "I have a bad feeling about this" and the ambient audio shifts to something menacing — clear signals without a "you must be level X to enter" gate.

**Failure is interesting.** A failed skill check should never dead-end the story. Failed to pick the lock? The guard heard you. Failed to persuade the merchant? They mentioned something useful while refusing you. Failed to sneak past the patrol? Combat begins — and combat is fun. The DM is prompted to treat failures as complications, not roadblocks.

### Visible vs. Hidden Mechanics

| Visible (HUD + Audio Cue) | Hidden (Under the Hood) |
|---|---|
| Key attack rolls (boss fights, clutch moments) | Minor damage calculations |
| Critical skill checks (persuasion, stealth, etc.) | NPC initiative ordering |
| Death saving throws | Loot randomization |
| Major contested rolls | Background stat adjustments |

- Visible rolls appear on the HUD with a dice animation — triggered by mechanics tools returning results with `narrative_hint`
- A **distinct audio cue** plays when dice hit the screen — `play_sound("dice_roll")` fires automatically. Builds Pavlovian tension over time
- Even eyes-free players know a key roll just happened and can glance down
- The HUD follows a **smartwatch interaction pattern** — glance, absorb, return to audio

---

## Session Structure

### Philosophy

A sync session should feel like a complete episode of a story — satisfying on its own while advancing the larger narrative. It has a beginning, middle, and end, with pacing managed by the AI DM. The technical session lifecycle (room creation, agent dispatch, prompt building, state persistence, narrative wrap-up, session summary compression) is detailed in *Technical Architecture — Session Lifecycle*.

### Target Session Length

**30–90 minutes**, with the DM able to scale content to available time. A player with 30 minutes gets a tight, focused experience. A group with 90 minutes gets a full adventure arc.

### Session Flow

**1. The Gathering (2–5 min)**
The party assembles. The DM recaps what happened last time. Players share what they've been doing in async. The DM sets the scene and establishes the session's initial hook.

**2. The Journey (variable)**
Exploration, travel, roleplay encounters, NPC interactions, environmental storytelling. The connective tissue between set pieces. Pacing is conversational — the DM reads the party's energy and adjusts.

**3. The Challenge (variable)**
The session's central encounter — combat, a puzzle, a social confrontation, a discovery. This is where the game's systems fully engage: dice rolls on the HUD, phase-based combat, dramatic narration.

**4. The Turn (variable)**
A narrative shift — a twist, a revelation, a consequence of the challenge's outcome. Something changes. The story moves forward in a way that sets up what comes next.

**5. The Hearth (2–5 min)**
The session winds down. The DM narrates the aftermath, distributes rewards, and plants seeds for next time. Players can discuss plans for async activities. The session ends on a note that makes players want to come back.

### Session Types — No Mode Selection

The player should never choose between "async" and "sync." Nobody opens a game thinking "I'd like an asynchronous experience." They think: "I have five minutes," or "I want to play for a while," or "I just want to hang out." The app should respond to *intent and available time*, not force a mode selection.

**When the player opens the app, they see two things:**

**1. The Catch-Up.** A glanceable summary of what happened since their last visit — world news, resolved activities, pending decisions. This is always there, always first. It takes 30 seconds to scan visually and a couple minutes to engage with fully (listening to narrated outcomes, making decisions). This is the current async hub content, but it's not a separate screen — it's the top of the home screen. The player can engage with it or scroll past it.

**2. "Enter the World" button.** One button. Prominent. Always available. Tapping it opens a LiveKit voice connection and puts the player into the world wherever they left off. The DM greets them, the companion says hello, ambient audio fades in. They're *in the game.*

There's no "start session" vs. "quick session" vs. "async check-in." There's just: catch up on what happened (always free, always available, tap-based) and enter the world (voice connection, live DM, you're playing).

**What "Enter the World" means at different time scales:**

**2 minutes:** The player enters, the DM greets them, they ask their companion a question or check on something in their current location, and they leave. The DM handles this gracefully: "Short visit today? No problem. I'll be here." No forced narrative structure. No session wrapper. Just a quick voice moment in the world.

**5-10 minutes:** The player enters, wanders to the market, talks to an NPC, overhears something interesting, maybe bumps into another player. No quest progression needed. The DM adapts to the casual pace — more ambient narration, more NPC color, no pressure toward objectives. If the player asks "what should I do?", the companion suggests something scaled to available time: "We could check in with Grimjaw about that blade, or just see what's happening in the square."

**30-60 minutes:** A full session. The DM structures it with a beginning, middle, and end. Quest progression, combat, exploration, story beats. The Gathering → The Journey → The Challenge → The Turn → The Hearth.

**Open-ended hang:** The player enters with no time limit and no goal. They want to exist in the world. The DM keeps the world alive around them — NPCs go about their business, the environment shifts with time of day, other players pass through. If something interesting happens (a world event, an NPC approaching them, another player nearby), the DM surfaces it naturally. If nothing happens, the companion fills the space. This is the "MMO tavern" experience — being present in a living world, not necessarily doing anything.

**How the DM knows what the player wants:** It doesn't need to ask. The DM reads behavioral signals:
- Player enters and immediately says "I want to go to the Greyvale" → quest mode, structure the session
- Player enters and says "hey, what's going on?" → casual mode, describe the surroundings, let them lead
- Player enters and says nothing for 10 seconds → the companion speaks first: "Hey. Quiet day so far. Want to do something or just take it easy?"
- Player enters and says "I only have a few minutes" → the DM acknowledges and keeps things light. No session wrapper, no narrative arc, just a moment in the world
- Player has been in-world for 5 minutes with no direction → the DM or companion gently offers a hook: "Heard there's something interesting at the docks today, if you're curious"

**The key insight: every voice connection is the same technical pipeline.** A 2-minute check-in and a 90-minute quest session use the same LiveKit room, the same DM agent, the same tools. The difference is entirely in the DM's behavior — pacing, narrative structure, and how actively it drives toward objectives. Short visits get a relaxed, ambient DM. Long sessions get a structured, story-driven DM. The player's behavior signals which mode is appropriate, and the DM adapts fluidly.

**The Catch-Up layer (no voice, always available):**

The non-voice layer handles everything that doesn't need a live DM connection:
- Resolved activity outcomes (pre-rendered audio + decisions)
- Pending decisions (faction messages, NPC requests, god whispers)
- New activity launching (crafting, training, companion errands)
- World news summary
- Guild/party messages
- Progress indicators on in-flight activities

This layer is free to use, always available, and tap-based. A player who only has 60 seconds can process their pending items here without ever opening a voice connection. A player who has more time can process the catch-up *and then* enter the world.

**What this replaces:**

| Old model (rigid) | New model (fluid) |
|---|---|
| "Start Session" button with expected duration | "Enter the World" — stay as long as you want |
| Separate "Async Hub" screen | Catch-Up layer integrated into home screen |
| Session types table (Quick Quest / Standard / Deep Dive / Raid) | DM adapts to player behavior and available time |
| Mode selection before playing | No selection — just enter |

**Session types still exist as DM behavior patterns**, not as player-facing categories. The DM internally recognizes when a player is in quick-visit mode vs. full-session mode and adjusts accordingly. The categories from the DM's perspective:

| DM Mode | Triggered By | DM Behavior |
|---|---|---|
| **Ambient** | Player enters with no stated goal, casual conversation, short visits | Relaxed narration, environmental color, companion chatter, no quest pressure. World lives around the player. |
| **Guided** | Player expresses a goal or asks what to do | Companion suggests options, DM offers hooks scaled to apparent available time. Light structure. |
| **Structured** | Player pursues a quest objective or enters a challenge area | Full session pacing: Gathering → Journey → Challenge → Turn → Hearth. Narrative arc with climax and resolution. |
| **Social** | Player seeks out other players or hangs out in populated areas | DM facilitates encounters, manages NPC background, keeps the space alive. Steps back when players are talking to each other. |

The DM can shift between modes mid-session. A player in Ambient mode who wanders into a quest area transitions to Structured. A player in Structured mode who finishes a quest and says "I'm just going to hang out for a bit" transitions to Ambient. The transitions are seamless — the DM adjusts pacing and narrative pressure without announcing a mode change.

### Silent Layer, Voiced Layer — Context-Aware Play

The two layers of the home screen map to real-world contexts, not game modes:

**Can't talk right now?** The Catch-Up layer is completely silent by default. Text summaries, decision buttons, activity launchers — all tap-based. The narrated audio clips are optional (play buttons, not auto-play-with-sound). A player on a bus, in a waiting room, in bed next to a sleeping partner, or sitting in a meeting can silently process their world updates, make decisions, and launch activities in two minutes without making a sound.

**Can talk?** "Enter the World" opens the voice connection. Headphones on, full immersion.

**The handoff is seamless.** Decisions made silently in the Catch-Up layer are already reflected in the world when the player enters via voice. The blade they chose to reinforce during their silent check-in is the blade Grimjaw presents when they enter the world. The errand they sent Kael on is already underway. The faction message they responded to has already shifted their reputation. The DM knows what the player decided — there's no "syncing" or re-explaining. Silent decisions and voiced experiences are one continuous thread.

**This means:**
- A player can engage with the game meaningfully every day, even on days they never speak
- The Catch-Up layer alone provides a complete, satisfying daily interaction for players who can't or don't want to use voice that day
- Voice sessions are richer because the player arrives having already processed their async outcomes and made their decisions — the DM can reference those decisions immediately instead of front-loading information
- The game fits into the cracks of real life — two minutes of silent tapping while waiting for coffee, then thirty minutes of voiced adventure that evening

---

## Combat Design — Voice-First Combat

### Design Philosophy

Audio's strengths are tension, intimacy, and imagination. Combat should feel like you're *in* the fight. Horror games and radio dramas prove audio can be more intense than visuals because the player's brain fills in the imagery. The system is inspired more by lightweight tabletop systems (Powered by the Apocalypse) than heavy crunch (D&D 5e full rules) — heavy mechanical crunch doesn't translate well to voice-only interaction.

### Phase-Based Rounds (Not Turn-By-Turn)

1. **Declaration phase:** All players quickly state intent — "I'm going for the shaman," "I'll hold the doorway." In multiplayer, the orchestrator's collection buffer extends to a configurable declaration timer (10-15 seconds) to gather all inputs.
2. **Resolution phase:** The DM calls mechanics tools (`request_attack`, `request_skill_check`, `request_saving_throw`) in initiative order. Each tool rolls, validates, and applies consequences atomically. Results include a `narrative_hint` ("barely hit," "critical failure") that guides the DM's narration.
3. **Outcome:** The DM narrates everything as one flowing scene, using the narrative hints and mechanical outcomes from all resolution tool calls.

This eliminates dead time. Instead of four players sitting through individual turns, everyone acts, then everyone hears what happened.

### Key Combat Mechanics

- **One clear action per round** + optional quick reaction. No bonus actions or movement calculations.
- **Interrupt / reaction mechanic:** During enemy narration, players shout reactions ("I block!"). The DM calls `request_saving_throw` or `request_skill_check` for the reaction.
- **Timer pressure:** Hesitate too long and the narrative advances: "You freeze and the goblin presses the advantage." The declaration timer enforces this.
- **DM narration shifts:** Shorter sentences, urgent cadence, present tense in combat. The `[CHARACTER, emotion]` tags in LLM output shift to high-energy emotions.
- **Creative actions encouraged:** "I kick the table into the goblin" → DM calls `request_skill_check(player, "athletics", "kick table into goblin")`, rules engine sets DC and resolves.

### Sound Design as a Combat System

The soundscape IS the tactical environment (headphones required):
- Spatial positioning of enemies — footsteps behind you, archer firing from your left
- Ambient combat layer running continuously
- Audio cues triggered automatically by mechanics tools — `play_sound("sword_clash")` on hit, `play_sound("critical_hit_sting")` on crit, health-low warning when HP drops below threshold
- Combat UI auto-pushes HP bars, turn order, and status effects via LiveKit RPC on every state mutation

### HUD in Combat

A **simplified tactical view** — not a full battle map, more like a radar:
- Shows who's where, who's hurt, what's threatening you — auto-updated by `update_combat_ui` on every mechanics tool call
- Key dice rolls animate with audio cue — driven by `narrative_hint` from tool results
- Delivering urgency information, not tactical complexity

### Boss Fights & Set Pieces

Boss encounters are the peaks of a session — the moments players remember and retell. They should feel fundamentally different from regular combat. The ambient audio shifts. The DM's narration becomes more elaborate and urgent. The HUD shows elements it normally hides — a boss health bar, a phase indicator. These visual flourishes are sparse throughout the game precisely so they feel special when they appear.

**Multi-phase structure.** Boss fights unfold in phases, each triggered by HP thresholds or narrative beats. Phase transitions are announced through audio and narration: the creature roars and the ground shakes, the sorcerer shatters their staff and the room fills with wild magic, the Hollow entity splits into two smaller forms. Each phase changes the tactical situation — new abilities, new environmental hazards, new audio cues warning of incoming attacks.

**Environmental hazards.** Boss arenas are active participants in the fight. Collapsing structures force repositioning. Arcane energy surges create zones the party must avoid. Fire spreads. Water rises. The DM narrates these hazards and the sound design reinforces them — the creak of a weakening ceiling, the hiss of encroaching flame. Players who pay attention to audio cues can anticipate hazards and gain advantage.

**God-agent intervention.** In significant boss encounters — especially those connected to the larger mystery — a player's patron deity may intervene. A Cleric of Orenthel receives a surge of healing power at a critical moment. A follower of Kaelen hears the war god's voice roaring encouragement, granting a temporary combat bonus. These interventions are triggered by the god-agent heartbeat evaluating the encounter state and the player's divine favor level. They should feel earned, not automatic.

**The Hollow as boss design.** Hollow bosses break the rules of the audio design itself. Normal enemies have recognizable sounds — footsteps, growls, weapon impacts. Hollow bosses produce sounds that feel wrong: frequencies that don't occur in nature, silence where there should be noise, audio that seems to come from inside the player's head rather than from a direction. This isn't just atmosphere — it's a gameplay signal. The wrongness of the audio tells the player this enemy is fundamentally different and demands different tactics.

**Set pieces beyond combat.** Not every climactic moment is a fight. A set piece could be: negotiating a peace treaty between two factions while a Hollow incursion approaches from the north (social encounter with a ticking clock), navigating a collapsing ruin while solving a puzzle to seal a breach (environmental challenge), or witnessing a god speak directly through a temple oracle (narrative event with player choices that have permanent consequences). These moments use the same heightened audio and HUD treatment as boss fights — the game signals "this matters" through presentation, not just difficulty.

---

## Navigation — Moving Through a Voice-First World

### Philosophy

Players express intent ("I want to find the blacksmith") rather than direction ("go north"). The DM interprets intent and narrates movement. Movement is mechanically resolved by the `move_player` tool, which validates the path exists and is accessible (locked doors require keys, blocked exits require conditions to be met), then updates the player's location in the database. The background process detects the location change and rebuilds the warm prompt layer with the new scene's NPCs, exits, and conditions.

### Macro Navigation — Between Regions and Locations

Travel decisions between major locations. The HUD map is most useful here.

- Player says "I want to head to the steppe" or "where can I go from here?"
- DM responds with context while the map highlights routes, distance, danger level, and points of interest
- **Safe, routine travel** is compressed narration: *"Three days along the southern trade road. The weather holds, and you arrive at Redmark as the sun sets."*
- **Dangerous travel** becomes an encounter: the DM narrates the environment, random encounters trigger, the party makes route and rest decisions
- **Async travel bridge:** Long journeys can begin in one sync session and complete in the next, with async check-ins during travel — camp decisions, roadside encounters, wayfaring merchants

### Micro Navigation — Within a Location

Contextual, conversation-driven movement through cities, dungeons, forests, and other locations.

**In settlements:**
- Navigation by intent: "I need to resupply" → market district. "I want to talk to the guard captain" → garrison.
- The DM narrates brief transitions between points of interest
- The player never needs to understand a grid or street layout

**In dungeons and wilderness:**
- The DM presents choices through sensory information: *"The corridor splits. Left, you hear dripping water and feel cold air. Right, there's a faint glow and the smell of something burning."*
- Players choose based on what they hear and what the DM describes
- The HUD fills in a simple map as you explore — glanceable reference for layout, not the primary navigation tool

**In combat spaces:**
- Tactical positioning is described by the DM and shown on the simplified HUD radar
- Movement is by intent: "I move behind the pillar" or "I close the distance to the archer"

### The Audio Compass — Spatial Audio as Navigation

A distinctive feature unique to the voice-first medium:

- Destinations and points of interest have **sound signatures** — the ring of a blacksmith's hammer, flowing water from a river, music from a tavern
- Sounds get louder and more directional as you move toward them (spatial audio in headphones)
- Tracking in the wilderness works through audio traces: broken branches, animal calls, distant footsteps
- **The soundscape itself guides you** — players develop a real skill of listening to the world for information
- Over time, experienced players navigate primarily by ear, creating a deeply immersive experience unique to this medium

### Navigation HUD — Visual Fallback

Always available for players who want concrete reference:

- Current location clearly marked
- Active quest objectives with directional indicators
- Nearby points of interest
- Breadcrumb trail of where you've been (especially useful in dungeons)
- Tap a location for a brief audio description from the DM
- The map is never the primary tool — voice and audio are. But it's always there for anyone who wants it.

---

## Player Guidance — Never Feeling Stuck

### Philosophy

A player who feels lost in a voice game has no screen to scan for buttons. The system must proactively guide without breaking immersion. Confident players never notice it. Uncertain players feel gently supported. No one is ever stuck.

### Always-Available Help

The player can always just ask:
- "What can I do here?"
- "Where should I go?"
- "I'm not sure what to do next."
- "What am I working on?" (triggers quest summary)
- "Help" or "I'm stuck" (triggers explicit guidance mode)

The DM responds in character with contextual suggestions. This mirrors real D&D — you ask the DM. The onboarding tutorial should establish this early: *"If you're ever unsure what to do, just ask me. I'm always here."*

### Proactive Escalating Guidance

If the player goes quiet, the system responds in graduated steps. The guidance system integrates with the background process (which tracks silence duration) and the quest schemas (which include `global_hints` per quest stage for when the player is stuck).

**Level 1 — Ambient Nudge (after ~15–20 seconds of silence)**
The DM redescribes the environment with embedded sensory hooks suggesting options. Subtle. Feels like the world breathing.

> *"The sound of the harbor drifts on the wind. Nearby, a notice board outside the guild hall catches your eye, and the smell of fresh bread wafts from a bakery where a familiar face seems to be waving you over."*

**Level 2 — Companion Suggestion (after another ~15–20 seconds)**
If the player has an NPC companion, the companion speaks up naturally.

> *"Maybe we should check out that smoke?"*
> *"I think the guild master wanted to see us."*
> *"Didn't the captain ask us to report back by sundown?"*

Feels completely natural — a party member offering a suggestion.

**Level 3 — Direct DM Guidance (after continued pause)**
The DM shifts to a warmer, more direct tone while remaining conversational.

> *"You've got a few options right now. You could follow up on the message from the guard captain, explore the ruins to the north, or head to the market to resupply. What sounds interesting?"*

Explicit help, but still a conversation — the DM offering choices through dialogue, not a system popup.

**Level 4 — Quest Journal (player-initiated or DM-offered)**
A concise summary of active objectives, ranked by proximity and urgency. Verbal from the DM, with an optional HUD quest list for glancing.

### The Companion as Guidance System

Every player receives an NPC companion early in the game. Beyond being a party member, the companion is a **narrative UI element disguised as a character:**

- Suggests destinations when the player wanders
- Reminds the player of active quests conversationally
- Reacts to the environment in ways that teach navigation: *"I hear something to the west"* teaches that audio cues matter
- Models behavior — interacting with NPCs, examining objects, commenting on points of interest shows the player what's possible
- Asks the player questions that are really prompts: *"Should we take the mountain pass or follow the river?"* teaches that routing choices exist
- **As the player gains confidence, the companion naturally becomes less directive and more of a peer**

### Guidance Gradient Summary

| Player State | System Response | Feels Like |
|---|---|---|
| Confident, active | No intervention | Pure immersion |
| Brief pause | Ambient environmental re-description | The world breathing |
| Extended pause | Companion suggestion | A friend helping |
| Prolonged uncertainty | DM offers clear options | A guide stepping in |
| Explicit request | Direct help / quest summary | Asking the DM at the table |
| Visual preference | HUD map and quest list | Glanceable reference |

---

## NPC Design — Characters, Not Furniture

### Philosophy

NPCs are the human texture of Aethos. The best tabletop DMs create NPCs that players remember for years — the gruff blacksmith with a soft spot, the nervous scholar who knows more than she's saying, the rival who earns grudging respect. Our AI DM must do the same. Every NPC the player talks to should feel like a person with a life that extends beyond the conversation.

In a voice game, NPC quality is make-or-break. Players can't skim past bad dialogue — they have to listen to every word. An NPC who sounds generic or robotic breaks immersion instantly. An NPC with a distinctive voice, memorable mannerisms, and something interesting to say becomes the reason players come back.

### NPC Categories

**Tier 1 — Authored Characters**
Major story NPCs with hand-crafted personalities, backstories, gated knowledge trees, and authored prose descriptions. These are the characters players form relationships with — quest givers, mentors, rivals, love interests, faction leaders. Each has a unique `voice_id` in the TTS pipeline for a distinct vocal identity. The DM agent receives their full personality, speech style, mannerisms, and secrets from the NPC schema and portrays them through the ventriloquism system: `[CHARACTER, emotion]: "dialogue"`. ~5-6 tier 1 NPCs for MVP.

Examples: the guild master who sends you to the Greyvale, the Aelindran scholar who recognizes the artifact, the companion who travels with you, the mysterious NPC who knows too much about the ruins.

**Tier 2 — Generated Characters**
Minor NPCs the DM improvises from structured tags and attributes — no authored prose, just enough data for a convincing performance. Guards, merchants, townsfolk, random travelers. They have personality tags (gruff, nervous, cheerful), a role, and maybe one interesting detail. The DM weaves them into the scene naturally. They share a small pool of generic voice profiles. ~15-20 tier 2 NPCs for MVP, with on-demand generation for unexplored areas.

Examples: the Millhaven innkeeper, the dock guard who gives directions, a traveling merchant with rumors, the temple acolyte who sells healing supplies.

**Ambient NPCs**
Not characters at all — just sound. Crowd noise, background conversations, market vendors calling out prices. The ambience layer creates the impression of a populated world without the DM needing to portray dozens of individuals. Players can "approach" ambient NPCs and the DM generates a brief interaction, promoting them to tier 2 on the fly if the conversation goes deeper.

### The Companion System

The companion is the most important NPC in the game — important enough to have its own dedicated design section. See *The Companion — Your Other Voice in the Dark* below.

### NPC Relationship Mechanics

NPCs remember the player through the `npc_dispositions` state table, which tracks a numerical disposition score per player per NPC. Disposition affects everything — dialogue tone, prices, available quests, willingness to share secrets, and how the DM narrates the NPC's reaction to the player's presence.

**Disposition flow:**
- Starts at the NPC's `default_disposition` (defined in schema, typically neutral)
- Modified by player actions via the `update_npc_disposition` tool — completing a quest for them, helping their faction, insulting them, stealing from them
- `disposition_modifiers` in the schema define which actions shift disposition and by how much
- Disposition decays toward the default at ~1 point per day (simulation layer 2), so neglected relationships cool but don't collapse
- At high disposition, the NPC unlocks gated knowledge — lore, secrets, quest hooks, and information they wouldn't share with a stranger
- At low disposition, the NPC becomes uncooperative, charges higher prices, or refuses service entirely

**The player never sees a number.** Disposition is communicated entirely through the DM's narration. An NPC with high disposition greets the player warmly, uses their name, offers discounts unprompted. An NPC with low disposition is curt, evasive, or hostile. The player reads social cues, not a relationship meter.

**Cross-NPC reputation:** Faction reputation (tracked in `player_reputation`) acts as a baseline disposition modifier for all NPCs in that faction. Help the Accord of Tides' trade routes, and merchants throughout the district start treating you better — even ones you've never met.

### NPC Voice and Personality Design

Every NPC the player converses with is voiced by the DM agent's ventriloquism system. The quality of the portrayal depends on the data the DM has to work with.

**Tier 1 NPCs** include rich personality data in their schema: `personality` (3-5 trait descriptors), `speech_style` (formal, colloquial, flowery, terse, etc.), `mannerisms` (verbal tics, catchphrases, habitual actions the DM narrates), and `backstory_summary` (motivations and history that inform how they react). The DM uses this data to create a consistent, distinctive character across sessions.

**Tier 2 NPCs** have only tags — `personality: [gruff, practical]`, `speech_style: "short sentences"`. The DM improvises a personality from these tags. Two "gruff, practical" NPCs in different locations will sound similar but not identical — the DM varies the performance based on context. This is intentional: minor NPCs don't need to be unforgettable, just believable.

**NPC schedules** (simulation layer 1) create the impression of independent lives. The blacksmith is at the forge during the day and at the tavern in the evening. If you visit the forge at night, it's closed — you hear the banked coals and silence. This creates a lived-in world where NPCs aren't just waiting for the player to show up. It also creates natural encounters — running into an NPC at the tavern leads to a different conversation than visiting them at work.

---

## The Companion — Your Other Voice in the Dark

### Why the Companion Exists

In a voice game with no visual interface, a solo player is alone with a narrator. That's a podcast, not a game. The companion transforms the experience from monologue into dialogue — a second presence in the world who reacts, disagrees, jokes, worries, and makes the player feel like they're sharing an adventure rather than receiving one.

The companion is also the game's most elegant design solution to its hardest UX problem: how do you guide a player through a voice-only world without breaking immersion? A tutorial popup is invisible. A help menu requires screen interaction. But a friend who says "maybe we should check the guild hall" is just... a friend helping. The companion is the guidance system wearing the disguise of a character.

But if the companion is *only* a guidance system, players will see through it in an hour. The companion must be a genuine character — someone the player develops a real relationship with, someone whose opinions matter, someone whose safety in combat creates real anxiety, someone whose secrets the player wants to uncover. The guidance function works *because* the player cares about the companion as a person first.

### What the Companion Does

The companion serves six simultaneous functions, layered so that the player experiences a character, not a system:

**1. Conversational partner.** The most basic and most important function. The companion talks — not just when prompted, but naturally. They comment on the environment ("This place gives me the creeps"), react to events ("Did you see the look on her face when you mentioned the ruins?"), ask the player questions ("What do you think she meant by that?"), and fill silence with personality-appropriate behavior (humming, muttering to themselves, pointing out details the player might have missed). In exploration and downtime, the companion is the texture of the experience.

The DM manages this through the ventriloquism system. The background process tracks conversational rhythm — if the player hasn't spoken in a while and there's no pending guidance trigger, the companion might offer an observation or a question. These aren't scripted lines; the DM generates them from the companion's personality, the current context, and the session's emotional arc. A nervous companion fidgets verbally. A confident companion cracks jokes. A scholarly companion muses about the history of wherever you are.

**2. Guidance system.** The companion is the primary delivery mechanism for level 2 escalating guidance. When the player is stuck, the companion suggests next steps in character. This works because it's the same voice that's been chatting naturally throughout the session — the shift from "idle conversation" to "here's what to do next" is invisible. The companion draws from `global_hints` in the quest schema, but the DM rephrases them in the companion's voice and style. A blunt companion says "We should talk to the innkeeper." A cautious companion says "I don't know... maybe the innkeeper knows something? She seems to hear everything."

**3. Emotional anchor.** The companion has opinions about the player's choices, and they express them. Help a refugee family and the compassionate companion is moved. Make a ruthless deal and the idealistic companion pushes back. Side with a faction the companion distrusts and they voice concern — not as a morality system, but as a person who cares about you disagreeing with your decision. These reactions make the player's choices feel consequential before the world responds, because someone they care about responds immediately.

The companion also processes the story's emotional beats alongside the player. When something frightening happens, the companion is scared too. When something wonderful happens, the companion celebrates. When the player faces a moral dilemma, the companion wrestles with it. This shared emotional experience is what creates attachment — the companion isn't observing the story, they're living it with you.

**4. Combat partner.** The companion fights alongside the player using the same mechanics tools. The DM calls `request_attack` or `request_skill_check` on the companion's behalf, and the companion's actions are narrated as part of the combat sequence. The companion has their own HP, abilities, and tactical personality.

In combat, the companion's voice changes — urgent, focused, reactive. They call out threats ("Behind you!"), suggest tactics ("Focus on the shaman — it's healing the others!"), and react to outcomes ("Nice shot!" or a panicked "I'm hurt, I'm hurt!"). Their voice in combat is a gameplay signal: if the companion sounds scared, the fight is going badly.

The companion can be knocked unconscious. This is one of the game's most powerful dramatic tools. When the companion goes down, their voice disappears from the audio. The player is suddenly alone — the silence where the companion's voice used to be is viscerally felt. The DM narrates the companion's fall with weight. The player has to decide: push through the fight, or break off to help their fallen friend.

**5. Story vehicle.** The companion has their own narrative arc that unfolds across sessions. They have a backstory the player gradually discovers — not through exposition dumps, but through offhand comments, reactions to specific situations, and moments where the companion's guard drops. They have a secret. They have a goal that may or may not align with the player's quest. They have a relationship with the world that predates the player.

A well-designed companion arc creates moments where the player cares more about the companion's reaction than the plot event itself. When the artifact from the Greyvale ruins is revealed, the companion's response — recognition, fear, anger, or silence — is the player's emotional anchor for processing what just happened.

**6. Voice variety.** In a solo session, without the companion, the player hears one voice: the DM narrator. With the companion, they hear a second distinct voice via the ventriloquism system's per-character `voice_id`. The contrast between the narrator's voice (authoritative, descriptive) and the companion's voice (personal, reactive, emotionally present) creates an audio landscape that feels populated rather than narrated.

### How the Companion Talks

The companion's dialogue is not scripted — the DM generates it in real-time from the companion's personality data in the NPC schema. But the *patterns* of when and how the companion speaks are designed:

**Proactive speech.** The companion doesn't wait to be spoken to. They initiate conversation based on context:
- Entering a new area: "Huh. Smells like sulfur. That's... not great."
- After a long silence: "You're quiet. Everything okay?"
- Noticing something: "Wait — do you hear that? Sounds like voices ahead."
- Reacting to a player decision: "Are you sure about this? Something feels off."
- After combat: "That was close. You alright?"

The background process manages companion proactivity. It tracks time since last companion utterance, current context (exploration, combat aftermath, social encounter), and emotional state. If the companion hasn't spoken in 30-60 seconds during exploration, the background process flags it and the DM generates an in-character comment on the next natural beat.

**Reactive speech.** The companion responds to what the player does and says:
- Player makes a joke: companion laughs, or groans, or delivers a deadpan response (personality-dependent)
- Player asks the companion's opinion: they give it, colored by their personality and current emotional state
- Player does something reckless: companion reacts with alarm, exasperation, or reluctant admiration
- Player asks "what do you think?": the companion offers a genuine assessment based on what they know

**Silence as character.** Sometimes the companion doesn't speak, and that silence IS the dialogue. After a shocking revelation, the companion might go quiet. The DM narrates: "Sable says nothing. Her ears are flat against her head." The player knows their companion well enough by now to read the silence.

### The Companion Across Contexts

**In exploration:** The companion is chatty, curious, and observant. They point out details, ask questions, and share their feelings about where you are. They're the color commentary of the experience. Their mood shifts with the environment — relaxed in safe areas, tense in dangerous ones, awed in beautiful or ancient places.

**In social encounters:** The companion has opinions about the people you talk to. They might whisper a warning ("I don't trust her"), offer encouragement ("You've got this"), or react visibly to what NPCs say (a sharp intake of breath when someone mentions the ruins). After the conversation, they debrief: "Did you notice how she changed the subject when you asked about her cousin?"

**In combat:** The companion is a tactical partner. They call out threats, suggest focus targets, warn about flanking. Their voice becomes urgent and clipped. They use their abilities to complement the player's class — a tank companion draws aggro for a mage player, a healer companion patches up a warrior. Their combat personality is consistent: a cautious companion fights defensively and worries about overextending, a reckless companion charges in and needs to be reined in.

**In downtime:** The companion relaxes. In the tavern, they order a drink and tell stories. At camp, they share something personal. During a quiet walk, they muse about the bigger picture. These are the moments where the relationship deepens — not through dramatic events, but through the accumulated texture of shared idle time.

**In crisis:** When something genuinely terrible happens — a party wipe, a major story revelation, an encounter with deep Hollow corruption — the companion drops their usual patterns. A normally chatty companion goes quiet. A normally stoic companion shows emotion. The shift signals to the player that this moment matters.

### Meeting the Companion

The companion shouldn't feel assigned. It shouldn't feel like a system. It should feel like the first meaningful thing that happens to you in the world.

**The player doesn't pick the companion.** No selection screen, no lineup, no "choose your partner." Picking from a list turns the companion into a loadout choice and breaks the fiction before it starts. Instead, the companion finds the player — or the player stumbles into the companion. The meeting happens organically during the opening experience's "normalcy" phase, after character creation but before the disruption that launches the main story.

**The meeting is engineered to feel like fate.** The assignment system selects the best companion archetype based on the player's class, patron, and starting culture. It then triggers a meeting scenario appropriate to that archetype. The DM narrates the encounter as a natural event — the player doesn't know this was inevitable. They experience it as: "I happened to meet this person, and we had a reason to stick together."

**The narrative reason is bidirectional.** The companion isn't assigned to help the player. The companion has their own reason for being in that place at that time — their own problem, their own quest, their own need. That need intersects with the player's situation. The companionship is mutually beneficial from the first moment, not a mentor-student dynamic. The player helps the companion with something immediate; the companion has skills or knowledge the player needs. Traveling together makes sense for both of them.

**The backstory creates shared vulnerability.** Both the player and the companion are, in different ways, at a turning point. The player just entered the world. The companion has a wound — something lost, something unresolved, something they can't face alone. They don't reveal this in session one. But the seed is planted immediately: this person has depth, and there's more to learn.

### Companion Archetypes and Their Introductions

The MVP needs 3-4 companion archetypes. Each is a fully authored tier 1 NPC with complete personality data, a backstory that intersects with the main mystery, and a specific meeting scenario for each starting culture. Below are the archetypes with their Sunward Accord meeting scenarios (the MVP starting culture).

**Kael — The Steadfast Partner**

A former caravan guard who lost his entire company to a Hollow incursion six months ago. He's the only survivor, and he doesn't know why. He's haunted by it — not in a dramatic, brooding way, but in the quiet way of someone who checks the exits when they enter a room and sleeps facing the door. He took work in the Accord of Tides as a dockside laborer because it's the safest place he could find. He hates that about himself.

*Meeting (Sunward Accord):* The player is exploring the market during the normalcy phase. A commotion near a stall — a vendor is being hassled by a pair of rough dockworkers. Kael is nearby, clearly wanting to intervene but hesitating. If the player steps in (or even just moves closer to watch), Kael joins them — and together they defuse the situation. Afterward, Kael is grateful but embarrassed. He introduces himself. He asks where the player is headed. When the disruption happens and the call to action sends the player north, Kael volunteers — not because he's brave, but because he's tired of hiding. He needs someone to travel with. He can't do it alone again.

*Why he's there:* He needs to prove he can face danger again. The player gives him a reason to try.
*What he offers:* Combat experience, practical survival knowledge, and a steady presence.
*His secret:* His company wasn't destroyed randomly. They found something before the Hollow came. He has a fragment of a journal he's never shown anyone.
*Matched with:* Mages, Seekers, Bards, Diplomats — players whose classes lack frontline combat strength.

**Lira — The Skeptical Scholar**

An Aelindran academic who studies residual Veil energy. She was part of a research team that was quietly shut down by temple authorities for asking uncomfortable questions about why the Veil shattered. She's convinced the official story is incomplete — not conspiratorially, but with the frustrated certainty of a scientist whose funding was pulled. She's sharp, occasionally condescending, and deeply passionate about understanding what happened to her people's city. She works in the Accord's archives now, cataloging recovered Aelindran artifacts. She's bored, underutilized, and itching for fieldwork.

*Meeting (Sunward Accord):* The player's character creation or early exploration leads them near the archives or a scholar's stall. Lira notices something about the player — their race, their patron, something they said — and approaches with a question. Not friendly small talk. A pointed, specific question about something most people wouldn't care about. If the player engages, Lira lights up. She's found someone who might actually be useful. When the disruption happens and the Greyvale reports come in, Lira immediately recognizes the significance — the Greyvale ruins were an old Aelindran research outpost. She *has* to go. She asks to come along, framing it as practical ("you need someone who can read old Aelindran, and I need someone who can keep me alive").

*Why she's there:* The Greyvale anomaly is connected to her banned research. This is her chance to find answers.
*What she offers:* Lore knowledge, investigation skills, the ability to read and analyze arcane phenomena.
*Her secret:* Her research team didn't just get shut down. Her mentor disappeared. Lira suspects the mentor found something and was silenced — and the Greyvale ruins might hold the proof.
*Matched with:* Warriors, Guardians, Skirmishers, Rogues — players whose classes lack investigation and lore capability.

**Tam — The Reckless Heart**

A young Vaelti scout who left the northern frontier because they couldn't stand watching the Ashmark creep south one more mile. They're impulsive, emotionally transparent, and ferociously loyal to anyone they decide is worth their loyalty — which happens fast, sometimes too fast. They laugh too loudly in taverns, pick fights with people who disrespect refugees, and cry openly when sad. They're exhausting and endearing in equal measure. They came to the Accord of Tides looking for someone — anyone — with a plan that wasn't "hold the line and hope."

*Meeting (Sunward Accord):* Tam is in trouble. The player encounters them in the market or dockside quarter, mid-argument with someone bigger than them — defending a refugee, or calling out a merchant for price-gouging, or just being Tam in a way that's about to get them hit. The situation is about to escalate. The player can intervene, defuse, or just watch (in which case Tam handles it messily and approaches the player afterward with a split lip and a grin). Tam decides immediately that the player is someone worth following. When the disruption happens, Tam doesn't ask to come along — they announce they're coming, and the player would have to actively refuse them.

*Why they're there:* They need direction. They have courage but no mission. The player gives them both.
*What they offer:* Scouting, tracking, sharp senses (Vaelti), fearlessness, and an emotional openness that draws out other characters.
*Their secret:* They didn't just leave the frontier. They ran. Someone they loved went into the Ashmark on a mission and never came back, and Tam couldn't bring themselves to follow. The recklessness is penance for the one time they were a coward.
*Matched with:* Clerics, Artificers, Druids, Oracles — players whose classes are cautious, methodical, or whose playstyle benefits from someone who forces action.

**Sable — The Quiet Watcher**

Not a person — a shadow-fox. One of the semi-sentient animals of Aethos, bonded to the ambient arcane energy of the world. Shadow-foxes are rare and considered omens by most cultures. Sable doesn't speak in words — the DM narrates her body language, sounds, and behavior, and occasionally translates her meaning. ("Sable's ears flatten. She doesn't like this." or "Sable yips once, sharply — she's found something.") She communicates through action, not dialogue.

Sable is an unusual companion because she shifts the audio dynamic. Instead of a second voice in conversation, the player gets a second *presence* — one that the DM narrates around. Sable's silence is loud. When she growls at someone the player is talking to, that's information. When she curls up beside the player at a campfire, that's emotion. She's the companion for players who want a relationship built on instinct and trust rather than conversation.

*Meeting (Sunward Accord):* Sable finds the player, not the other way around. During the normalcy phase, the player notices something following them — a flicker of movement in an alley, a shadow that doesn't match its source. If the player investigates, they find Sable watching them from the rooftop. She doesn't approach immediately. She follows at a distance for a few minutes. Then, during the disruption — when the rider arrives and the market goes silent — Sable appears at the player's side, pressing against their leg. She chose them. The DM narrates: "The fox looks up at you with eyes that seem to understand exactly what's happening. She's not afraid. She's waiting for you to decide what to do next."

*Why she's there:* Shadow-foxes are drawn to Veil disturbances and to people who are about to matter. Sable senses something about the player — something connected to the larger mystery.
*What she offers:* Perception that borders on supernatural (she hears and smells things before anyone else), the ability to sense Hollow corruption, and a bond that the DM can use for environmental storytelling (Sable's reactions are a gameplay signal system).
*Her secret:* Sable was bonded to someone before — someone connected to the Greyvale ruins. That person is gone. Sable remembers, and there are places she will react to with grief, fear, or recognition that the player will need to understand.
*Matched with:* Spies, Whispers, Paladins, Wardens — players who already have strong verbal presence and benefit from a non-verbal companion that adds a different texture.

### If the Player Says No

The companion can be refused. Forcing a relationship on a player is the fastest way to make them resent it. But the game is designed so that refusal is a choice with texture, not a binary off-switch.

**Soft refusal — "not right now."** The player doesn't engage with the meeting scenario, or acknowledges the companion but doesn't invite them along. The companion respects it. They're disappointed but not crushed — they have their own reasons for going north, after all. The DM narrates their departure gracefully. But the companion doesn't vanish from the world. They're heading the same direction for their own reasons. The player might spot them on the road, hear about them from an NPC in Millhaven, or find them already at the Greyvale ruins investigating independently. The world keeps putting the companion in the player's path — not aggressively, but naturally, because they share the same destination. Most players who soft-refuse will eventually gravitate toward the companion when they realize this person keeps showing up and is genuinely interesting.

**Hard refusal — "leave me alone."** The player explicitly rejects the companion. The companion leaves the narrative entirely. No further appearances, no showing up uninvited. The player's choice is respected.

The game adapts: the guidance system shifts so that level 2 (companion suggestion) is skipped. Level 1 ambient nudges carry more weight, and level 3 DM guidance activates sooner. The DM itself takes on more of the conversational role — commenting on the environment, offering observations, asking the player questions. It's a lonelier, harder experience, but a valid one. Some players will prefer it.

**The door stays open.** Even after a hard refusal, the companion exists in the world. If the player returns to the Accord of Tides, they might hear about the companion from another NPC — "There was someone asking about you at the guild hall." If the player seeks them out, the companion is available for a second meeting, now with a different dynamic: the player is coming to them. This reversal — the player choosing to initiate the relationship — often creates a stronger bond than the original engineered meeting would have.

**No-companion as an option, not a punishment.** The game never punishes the player for refusing. It's slightly harder without the guidance layer, and solo combat is tougher without a partner, but the DM compensates — scaling encounters, providing more environmental cues, and stepping in with direct suggestions when needed. The player who refuses the companion is telling the game "I want to be a lone wolf," and that's a playstyle worth supporting. If it becomes too difficult, the player can always seek the companion out.

### The Relationship Over Time

The companion relationship has a designed emotional arc that unfolds across sessions:

**Sessions 1-2: The Meeting and First Steps.** The companion is met during the opening experience through their archetype-specific meeting scenario. The tone is: two people (or a person and a fox) who've just decided to travel together for practical reasons. There's warmth but also distance — the familiarity of shared purpose without the intimacy of shared history. The companion guides heavily but naturally, because the player is new and the companion knows the area. The player is learning who this person is. Small moments hint at depth: a reaction that seems disproportionate, a topic quickly changed, a moment of surprising competence or vulnerability.

**Sessions 3-5: Building Trust.** The companion starts to relax. Humor emerges. Opinions become stronger. They begin sharing fragments of their backstory — not in monologues, but in context. Visiting a location that reminds them of something. Reacting to an NPC who resembles someone from their past. The guidance becomes less frequent as the player gains confidence; the companion transitions from helper to peer.

**Sessions 6-10: Deepening.** The companion reveals more of their inner life. Their secret starts to surface — obliquely at first, then more directly. They have moments of vulnerability. They express care for the player in ways that go beyond their assigned role. The relationship starts to feel earned. The companion disagrees with the player more, because they care enough to be honest.

**Sessions 10+: Partnership.** The companion feels like a true partner. They challenge the player. They have emotional reactions that surprise the player. Their personal story arc reaches pivotal moments — a confrontation with their past, a decision that tests their values, a moment where they need the player's help instead of giving it. The player is now invested in the companion's story as much as their own.

**The Long Arc.** Over many sessions, the companion's relationship with the player becomes one of the game's primary retention drivers. The companion remembers everything — inside jokes, shared defeats, moments of triumph. They reference past events naturally. "Remember the last time we were in a place like this? That didn't go well." The accumulated history creates a bond that makes the player reluctant to stop playing — not because of progression systems, but because they'd miss the companion.

### The Companion in Multiplayer

When the player joins a party with other humans, the companion's role shifts but doesn't disappear:

**Small party (2 players):** Both players' companions are present, both ventriloquized by the DM. The companions interact with each other as well as with the players — bickering, coordinating, or bonding depending on their personalities. The DM manages four voices (narrator + two companions + any NPCs). This is near the limit of the ventriloquism system's complexity.

**Full party (3-4 players):** Companions fade to the background. They're still narratively present (the DM might mention them in passing) but they don't speak often. The social dynamic between human players replaces the companion's conversational function. The companion steps forward only when their unique knowledge or abilities are relevant — or when the player directly addresses them.

**Post-MVP extraction:** In multiplayer, extracted companions (running as independent agents) can whisper to their linked player on a private audio track. "I don't trust the new guy" or "Did you notice the symbol on her armor?" These private asides create a sense of conspiracy and intimacy even in a group setting.

### The Companion in Async

Between sessions, the companion is available for brief interactions through the async hub:

**Check-in conversations.** Short voiced exchanges (30-60 seconds of audio, not a full LiveKit session). The player opens the app, the companion has a comment about what's been happening in the world while the player was away. "While you were gone, I heard a rumor about..." or "I've been thinking about what happened at the ruins. I have a theory."

**Companion errands.** The player can send the companion on tasks: "Scout the northern road" or "Ask around about the merchant's cousin." The companion departs (narratively) and returns after a real-time timer with results — information, an item, a new contact, or trouble they got into. The return is a short voiced scene.

**Relationship maintenance.** The companion's disposition doesn't decay the way other NPCs' do — the bond is deeper. But the companion notices absence. After a long break, the companion acknowledges it naturally: "It's been a while. I was starting to worry." This is a re-engagement hook disguised as character.

### Making the Player Care

The companion's emotional design follows a simple principle: **the companion must need the player as much as the player needs the companion.**

A companion who's purely competent and helpful is a tool. A companion who has fears, weaknesses, blind spots, and moments where they rely on the player is a person. The companion should ask the player for advice. Should admit when they're scared. Should make a mistake and need the player to bail them out. Should have a moment where the player's words visibly affect them.

The game's most emotionally powerful moments won't be plot revelations or boss fights. They'll be the companion going quiet after you say something that hits close to home. The companion shouting your character's name when you go down in combat. The companion saying "I'm glad it's you I'm doing this with" on the road between locations, unprompted, because the DM knows the emotional arc calls for it.

The companion is how the game loves the player back.

---

## Asynchronous Play — The Living World Between Sessions

### Philosophy

Sync sessions are the main event. Async is what makes the player open the app every day.

The mental model isn't "I'll play my RPG tonight." It's "I wonder what happened while I was gone." The world runs on a real-time clock (1 game-minute = 1 real minute, 24/7) — see *World Data & Simulation — World Simulation Rules*. That means the world genuinely changes while the player is away. Corruption drifts. NPCs move through their schedules. Merchants restock. Factions advance. Gods make decisions. The player's crafting finishes, their companion returns from an errand, their training completes. When the player opens the app, they're not greeted with a frozen world waiting for them — they're catching up on a world that's been living without them.

The async loop is: **check in → discover what changed → make decisions → set things in motion → close the app.** Five minutes. While walking the dog, waiting in line, lying in bed before sleep. Every check-in should feel valuable — not "let me collect my daily reward" but "let me see what happened and decide what to do next."

### The Five-Minute Check-In

The async hub is designed around a single question: **what can a player meaningfully do in five minutes?**

When the player opens the app between sync sessions, they land on the **Async Hub** — a screen organized around what needs their attention right now. Not a menu of systems. A feed of events, outcomes, and decisions, presented in priority order.

**What the player sees (in order):**

**1. World News (30 seconds).** A brief narrated summary of what changed in the world since their last check-in. Not a text wall — a short audio clip (pre-rendered, not a live voice session) from the DM or their companion: "While you were away, the corruption in the northern Greyvale pushed another mile south. Millhaven's erected a barricade on the north road. And your friend at the guild hall left you a message." This orients the player in the living world. It takes half a minute and immediately answers "what happened while I was gone?"

**2. Resolved Activities (1-2 minutes).** Anything the player set in motion that has completed. Each resolved activity is a short narrated scene — 15-30 seconds of audio — followed by a decision.

Examples:
- *Crafting completed:* "Grimjaw holds up the blade. 'It's done. But the tempering threw a surprise — the hollow-bone you added reacted with the steel. It's sharper than I planned, but brittle at the hilt. I can reinforce it with leather for durability, or leave it as-is for maximum edge. Your call.'" → **Decision: Reinforce (balanced) or Leave it (glass cannon)**
- *Training completed:* "Your mentor nods slowly. 'You've got the basics. Now — do you want to specialize in precision strikes, or keep training the fundamentals for a broader foundation?'" → **Decision: Specialize or Generalize**
- *Companion errand returned:* "Kael's back. He's muddier than when he left. 'The northern road is worse than we thought. But I found something interesting at the crossroads — tracks. Not Hollow. Human. Someone's been going back and forth to the ruins regularly.' He shows you a torn piece of cloth caught on a branch." → **Decision: Investigate the tracks next session, or Send Kael to follow them (new errand)**

Each resolution creates a new decision point. The player is never just collecting — they're always choosing.

**3. Pending Decisions (1-2 minutes).** Things that arrived while the player was away and need a response:
- A faction message requesting help or offering a deal
- A guild notification about territory or resources
- A god whisper — a cryptic, atmospheric audio clip from the player's patron deity
- A voice message from a party member or guild mate
- An NPC who reached out (a merchant with a rare item, a contact with information)

Each decision takes 15-30 seconds: listen to the message, make a choice, move on.

**4. Set New Activities (1 minute).** With the outcomes processed and decisions made, the player can set new things in motion:
- Start a new crafting project
- Send the companion on another errand
- Begin a training cycle
- Commission a merchant for a specific item
- Assign resources to a guild project

Each activity has a real-time duration (30 minutes to 48 hours) and an expected outcome range. The player makes their choices, and the app confirms: "Your blade will be ready in about 6 hours. Kael will report back by morning."

**5. Close.** The player closes the app knowing: what happened in the world, what their resolved activities produced, what decisions they made, and what's now in motion. Total time: 3-7 minutes. Every minute felt productive.

### Async Activity Types

#### Crafting and Workshop

The FarmVille core — you plant something, time passes, you harvest. But every step has a decision, and the AI narration makes every outcome unique.

**How it works:**
1. **Choose a project.** The player selects what to craft from available recipes (unlocked through progression and quest rewards). Projects range from quick and simple (sharpen a blade, 30 minutes) to ambitious and complex (forge a custom weapon, 24-48 hours).
2. **Make decisions that influence the outcome.** Before the timer starts, the player makes 1-2 choices: material selection (common materials = safe outcome, rare materials = higher ceiling but risk of failure), technique choice (aggressive = faster but riskier, careful = slower but reliable), and optional skill check (spend a few seconds making a voiced skill check that modifies odds).
3. **Wait.** Real time passes. The simulation tracks the project.
4. **Return to a narrated outcome.** The crafting NPC (voiced, 15-30 seconds) describes what happened. Success, partial success, unexpected results, or failure — each narrated uniquely by the AI. Success isn't just "you got the item" — the NPC describes a specific moment in the process that went well. Failure isn't just "try again" — the NPC explains what went wrong and offers a choice: salvage the materials and try a different approach, or accept a lesser result.
5. **Make the next decision.** The outcome always presents a choice: finish the item as-is, modify it further (new timer), or start something new.

**The emotional hook:** The crafting NPC becomes a character. The blacksmith who remembers your last three projects and comments on your improving technique. The alchemist who gets excited about an unusual ingredient you brought back. The relationship with the crafter is part of the reward — you're not interacting with a crafting menu, you're collaborating with a person.

#### Training and Skill Development

Investing in your character's growth between sessions. The sync session reveals what you can do; async training expands what you *will* be able to do.

**How it works:**
1. **Choose a skill or ability to train.** The player visits a mentor NPC (or their companion, for certain skills) and selects a training focus. Options are contextual — a warrior who just struggled with a particular enemy type might see a training option specifically for countering that threat.
2. **Brief voiced scene.** A 20-30 second scene where the mentor sets up the training. "We're going to work on your footwork. You're strong, but you plant your feet. That'll get you killed against something fast. I want you moving, always moving." This isn't just flavor — it establishes what the training will improve.
3. **Timer.** Training takes 2-12 hours depending on what's being learned. Longer for new abilities, shorter for refinements.
4. **Return to a culmination scene.** The mentor assesses progress. Three possible outcomes: breakthrough (skill improved, new ability unlocked, mentor pleased), plateau (progress made but not complete — continue training or try a different approach?), or redirection (the training revealed a different weakness — the mentor suggests pivoting). Each is narrated, each presents a choice.

**Progression connection:** Training unlocks abilities and stat improvements that are immediately available in the next sync session. A player who trains a counter-technique before their next session and then uses it successfully in combat feels the direct value of the async loop.

#### Companion Errands

Sending the companion out into the world while the player is away. This is one of the most narratively rich async activities because the companion returns with a *story*, not just a result.

**Errand types:**
- **Scouting:** "Check the northern road." The companion investigates a location or route and returns with information — safe/dangerous, who they saw, what they found, potential opportunities or threats. Information errands are short (1-4 hours).
- **Social:** "Ask around about the merchant's cousin." The companion talks to NPCs and gathers intelligence. They might return with a new contact, a piece of gossip, a quest lead, or a warning. Social errands depend on the companion's personality — a charming companion gets better social results than a gruff one.
- **Acquisition:** "Find me some hollow-ward herbs." The companion searches for a specific resource or item. Success depends on the companion's skills and the difficulty of the request. They might return with the item, a lead on where to find it, or a story about why they couldn't get it.
- **Relationship:** "Go check on Elder Yanna." The companion visits an NPC the player has a relationship with. They return with news about that NPC — how they're doing, whether anything's changed, messages or requests. This maintains NPC relationships during the player's absence.

**The return scene:** When the companion returns, the player gets a 30-60 second voiced scene. The companion describes what happened — not as a report, but as a story. "So I went to the northern road like you asked. It's bad. The barricade's holding but barely. And I ran into someone interesting at the crossroads — an Aelindran woman asking questions about the ruins. She wouldn't give her name." The scene always ends with information that creates a decision or a hook for the next sync session.

**Companion risk:** Some errands carry risk. A scouting mission into dangerous territory might result in the companion returning injured (reduced capability at the start of the next sync session) or getting into trouble that becomes a side quest. The player learns to weigh risk against reward — and to worry about their companion while they're gone.

#### World Events and God Whispers

The world reaching out to the player. These aren't player-initiated — they arrive while the player is away.

**God whispers:** The player's patron deity sends a brief audio message — 15-30 seconds, atmospheric, in the god's voice. These range from cryptic guidance ("Something stirs in the deep places. Be wary of what you trust.") to direct instruction ("My followers in the northern holds need aid. Your strength would be welcome.") to emotional moments ("You have done well. I see you."). God whispers are triggered by the god-agent heartbeat evaluating the player's divine favor, recent actions, and world state. They serve as re-engagement hooks (a notification that sounds like "Kaelen, the Ironhand, has a message for you" is far more compelling than "daily login reward available") and as narrative threads that connect async to the larger mystery.

**World event alerts:** Major simulation events that affect the player's region. "The Hollow pushed further south overnight — the northern Greyvale road is now considered dangerous." "A trade caravan was lost on the eastern route. Prices at the market have risen." "The Thornwatch has called for volunteers to reinforce the Millhaven barricade." These create urgency without demanding immediate action — the player absorbs the information and factors it into their next session's plans.

**Faction and guild updates:** In the MMO context, what happened in the player's guild and faction while they were away. Territory changes, resource reports, messages from guild leaders, requests for help. For solo players, faction standing updates based on accumulated reputation from previous actions.

#### Mini-Quests (5-10 minutes)

Short, self-contained voice encounters for players who want more than a check-in but don't have time for a full sync session. These are optional — a player who only does the 5-minute check-in never misses essential content.

**How they work:** The player selects a mini-quest from the async hub. A lightweight voice session starts — not a full LiveKit room, but a short pre-orchestrated encounter using the same DM voice. The player speaks a few decisions, hears narrated outcomes, and resolves the quest in 5-10 minutes.

**Types:**
- **Patron god tasks:** Veythar asks you to examine an artifact and report your findings. Kaelen challenges you to a brief combat trial. Aelora asks you to mediate a merchant dispute. These build divine favor and deepen the patron relationship.
- **NPC favors:** An NPC you've befriended asks for help with something personal. Brief, emotional, and relationship-deepening. The innkeeper needs help moving crates before a storm. The scholar wants your opinion on a translation. The guard captain needs someone to deliver a message to a family member.
- **Intel gathering:** A quick investigation. Talk to 2-3 NPCs, piece together information, report back. Results feed into the main questline or unlock new options for the next sync session.
- **Companion moments:** A brief scene with your companion that deepens the relationship. Not task-oriented — just two people talking. The companion shares something personal, asks about the player's plans, or reacts to recent events. These are rare and valuable — they only appear when the companion's emotional arc calls for it.

### The Catch-Up Layer (Home Screen Integration)

The async content isn't a separate screen — it's the **Catch-Up layer** integrated into the top of the home screen. When the player opens the app, this is what they see first, above the "Enter the World" button. It's designed to be **silent-first** — every element works as a tap-based, text-visible interface without any audio. Narrated audio is available via play buttons but never auto-plays with sound. A player in a quiet environment can process everything visually and make all their decisions without producing a single sound.

The feed is organized by urgency:

**Top — What happened.** World news audio clip (auto-plays if something significant changed), followed by resolved activity cards. Each card has a brief text summary, a play button for the narrated scene, and decision buttons. If nothing changed since the last check-in, this section shows companion idle chatter or a world micro-observation instead.

**Middle — What needs you.** Pending decisions: messages, requests, choices. Each is a card with a brief text preview and a play button for the full audio. Empty if nothing pending — no placeholder, just not there.

**Bottom — What to do next.** Available activities: crafting projects, training options, companion errands. Each shows the expected duration and a brief description. Tap to start, make initial decisions, confirm. In-flight activities show progress indicators with intermediate narrative states.

**Below everything — "Enter the World."** The single prominent button that opens a voice connection. Always there, always visible even before scrolling through catch-up content. A player who doesn't care about async can tap it immediately. A player who wants the full check-in scrolls through the catch-up first and then enters.

**Background:** The home screen shows a stylized view of the player's current location, time of day, and weather. It shifts in real-time — if the player checks in at night, it looks and sounds different from a morning check-in. Ambient audio from the player's location plays softly behind the interface.

**Notifications:** The app sends push notifications for significant events only — resolved activities, god whispers, urgent world events, guild messages. Each notification is a narrative hook: "The blade is done. Grimjaw says it's his best work yet." / "Kael returned from the northern road. He looks worried." / "Kaelen has words for you." Never: "Your timer is complete!" or "Daily reward available!" Tapping a notification opens the app directly to the relevant catch-up card.

### Async Technical Implementation

Async activities are **not** full voice sessions. They don't use LiveKit rooms or real-time LLM inference for the core check-in loop. This is critical for cost control — if every async check-in cost as much as a sync minute, the economics would break.

**Pre-rendered audio:** The DM narrates async outcomes during the simulation tick, not during the player's check-in. When a crafting project completes, the simulation generates the outcome (success/failure/partial) and then makes a single LLM call to generate the narration. That narration is synthesized to audio via TTS and stored. When the player opens the app, they're playing back pre-rendered audio, not running a live voice pipeline.

**Batch processing:** Async narrations are generated in batch during low-traffic periods. A 30-second crafting outcome narration costs ~$0.002 in LLM + TTS. A player with 3 resolved activities and a god whisper costs ~$0.01 per check-in. At one check-in per day, async adds ~$0.30/month to a player's cost — negligible.

**Mini-quests are the exception.** These are lightweight voice sessions with real-time LLM and TTS. They're short (5-10 minutes) and optional, so their cost is bounded. They use the same DM agent architecture as sync sessions but with simpler prompts and fewer tools active.

**Decision inputs are REST, not voice.** The choices the player makes during a check-in (crafting options, companion errands, faction responses) are tapped on the screen, not spoken. This is intentional — async is a quick, tactile experience. Voice is reserved for sync sessions where the full immersion matters. The companion errand selection might be: tap "Scout" → tap "Northern Road" → tap "Confirm." Three taps, done.

### The Frequent Checker — Handling High Check-In Rates

A player who checks in every 30 minutes will often find nothing has resolved — most timers run 1-48 hours. If frequent check-ins consistently deliver empty screens, the player learns not to bother. The async system must make every check-in feel like *something*, even when nothing actionable has changed.

**The problem in detail:** World news only regenerates when the simulation ticks and something actually changed. Resolved activities don't appear until timers complete. Pending decisions arrive organically from world events and NPC messages. A frequent checker clears pending decisions quickly, has nothing resolved yet, and sees the same world news. Three empty check-ins in a row teaches them: stop checking.

**Solution 1 — Companion idle presence.** When there's nothing pending, the companion fills the space. Not with system information — with personality. A short pre-rendered audio clip drawn from a rotating pool: "Still waiting on Grimjaw. You know he won't rush it." / "I've been thinking about what that scholar said. Something doesn't add up." / "Quiet day. Almost suspicious." These are texture, not content — they take 5-10 seconds and make the check-in feel like visiting a friend rather than refreshing an inbox. The pool is generated in batch (dozens of companion idle lines for ~$0.05 total) and rotated so the player rarely hears the same one twice in a week.

**Solution 2 — World micro-observations.** The simulation generates small ambient details on every tick — weather shifts, market price changes, NPC movements, overheard rumors, environmental flavor. These aren't decisions, just texture: "The wind shifted from the north. Rain by evening, the shepherds say." / "More guards on the south gate today. Something has them nervous." Cheap to generate in batch, served from a pool, and they make the world feel alive even when nothing actionable happened. A new micro-observation appears every 1-2 hours, so a player checking every 30 minutes sees a fresh one roughly every other check-in.

**Solution 3 — Soft timer ranges.** Instead of "your sword is ready in exactly 6 hours," the system uses ranges with variance: "Grimjaw says it'll take 4-8 hours." Internally, the actual completion time is randomized within the range. This means a frequent checker occasionally gets a pleasant surprise — something resolved early. Checking often has a small reward probability, which creates gentle stickiness without predatory mechanics. The variance is genuine (the crafting NPC's process actually varies), not artificial.

**Solution 4 — Activity density encouragement.** The more concurrent activities a player has running, the more likely any given check-in has something resolved. One crafting project means long stretches of nothing. A crafting project, a companion errand, a training cycle, and a pending faction thread means four independent timers, each of which could resolve. The system gently encourages running multiple activities — not by nagging, but by making it natural. After resolving a crafting project: "While the next one's in the forge, want to send Kael to look into something?" The companion suggests errands. The mentor mentions a training opportunity. The goal is 3-4 concurrent activities as the natural baseline.

**Solution 5 — Progress indicators, not just resolution.** Activities in progress show meaningful intermediate states, not just timers. "Grimjaw's started the tempering — says the hollow-bone is reacting differently than he expected. He's adapting." These progress updates are pre-rendered at activity start (2-3 intermediate states per activity, served at appropriate intervals). A frequent checker sees the narrative unfold gradually rather than staring at a countdown.

**Cost impact:** Frequent checking is nearly free. All content is pre-rendered and cached — the cost is in generation (which happens on simulation ticks regardless of check-in frequency), not in serving. A player who checks 20 times a day costs almost nothing more than one who checks once. The companion idle pool and micro-observations are generated in batch at negligible cost (~$0.10/month for a pool large enough to avoid repetition). The only cost risk would be generating content per check-in, which the system explicitly does not do.

1. **Async must matter to sync.** Crafted gear used in the next dungeon. Training unlocks an ability just in time. Scouting intel that changes the player's approach. Every async activity should make the next sync session richer.

2. **Async must not be required.** Sync-only players should never feel punished. Async provides lateral advantages — more options, more information, better preparation — not mandatory power. A player who never touches async can still enjoy the full story and combat. They'll just have fewer resources and less intel than a player who checks in daily.

3. **The timer isn't the content. The decisions on either side are.** A 6-hour crafting timer is meaningless. The choice of materials, the risk/reward tradeoff, and the narrated outcome with its follow-up decision — that's the content. The timer is just the space between decisions.

4. **Every check-in ends with something in motion.** The player should never close the app with nothing pending. There should always be a crafting project ticking, a companion on an errand, a training cycle running, or a decision they chose to defer. This creates the "I should check back" pull that drives daily engagement.

5. **Notifications are narrative hooks, never system alerts.** Every push notification is a tiny story. "The blade is forged — Grimjaw awaits your inspection." Not "Crafting complete. Tap to collect." The notification should make the player curious, not obligated.

6. **The world doesn't wait.** If the player doesn't check in for three days, the crafting project is done and the result is sitting there. The companion returned and has been waiting. The world events happened. Notifications accumulated. Nothing is lost or punished — but the backlog of "what happened" is longer and richer. The world moved on, and catching up feels like returning from a trip, not like logging into a game.

7. **Absence is acknowledged, never punished.** After a long break, the companion's greeting changes: "Where have you been? Things happened while you were gone." The world news summary is longer. But nothing decayed, nothing was lost, no progress was reversed. The player returns to more content, not less. Re-engagement should feel like coming home, not like damage control.

8. **Every check-in has something, even when nothing happened.** A check-in with no resolved activities and no pending decisions should still feel like a moment in the world — companion idle chatter, a micro-observation, a progress update on an in-flight activity. The player should never open the app and see an empty screen. Frequent checkers are rewarded with texture and presence; infrequent checkers are rewarded with a backlog of outcomes and decisions. Both patterns feel natural.

---

## The Economy — Currency, Trade, and Value

### Philosophy

The economy exists to make choices meaningful. Every purchase is a tradeoff. Every item found has a value the player understands. The economy should feel like a living system — prices change based on supply, demand, and world events — without requiring the player to study spreadsheets. The DM handles all transactions conversationally: "Grimjaw offers 12 silver for the wolf pelts. He's being generous — the market's been flooded with hides from the northern hunters."

### Currency

A single primary currency keeps things simple: **silver pieces (sp).** The denominations create natural price intuition:

- **Copper pieces (cp)** — 10 cp = 1 sp. Pocket change. A meal, a drink, a night at a cheap inn.
- **Silver pieces (sp)** — The baseline. A good weapon, a day's skilled labor, a useful potion.
- **Gold crowns (gc)** — 1 gc = 100 sp. Significant wealth. Property, rare items, major services.

The player doesn't need to track currency precisely. The DM narrates financial state naturally: "You've got enough coin for supplies and a comfortable room" or "That enchantment would cost more than everything in your pack." The exact numbers live on the character sheet for players who want them.

### Pricing and Trade

Item values are defined in the `value_base` field of the item schema, modified by `value_modifiers` that adjust price based on context:

- **Supply and demand:** Healing potions cost more in a town near the Ashmark (high demand) than in the Dawnspire Highlands (plentiful supply). Weapons are cheap where the military is strong and expensive in peaceful regions.
- **Merchant disposition:** NPCs with high disposition toward the player offer better prices. A merchant you've helped gives you the "friend discount." One you've offended charges extra or refuses to sell.
- **Faction reputation:** High standing with a faction's merchants reduces prices across the board. The Keldaran Holds' forges offer discounts to allies of the Holds.
- **World events:** A Hollow incursion disrupts trade routes, raising prices in affected regions. A successful defense restores them. The economy simulation tick (layer 2) handles these adjustments automatically.
- **Rarity context:** A common sword is cheap everywhere. A relic from Aelindra is priceless in the Diaspora quarter and merely expensive elsewhere.

**Merchants restock over time.** A merchant who sells their last healing potion won't have more until the next simulation tick restocks their inventory. This creates organic scarcity without artificial limits.

### Earning Money

Players earn currency through several channels, all designed to reward engagement without creating a grind:

- **Quest rewards** — The primary income source. Completing quests awards currency scaled to difficulty.
- **Loot** — Items found during exploration and combat can be sold to merchants. The DM narrates the value: "This is a well-crafted Hollow-bone dagger — unusual material. A collector would pay well for it."
- **Trade skills** — Crafted items (via async crafting) can be sold. Higher skill produces more valuable goods.
- **Faction bounties** — Standing tasks from factions that reward currency for specific actions (clearing Hollow nests, delivering supplies, gathering information).
- **Services** — Some class abilities have economic value. A Cleric can offer healing. A Bard can perform at a tavern for tips. An Artificer can repair equipment. These are narrated interactions, not menu-driven transactions.

### The Sync/Async Economy Loop

Sync sessions generate wealth (quest rewards, loot) and create spending needs (gear upgrades, supplies for the next adventure, services). Async activities provide the production loop — crafting items, training skills that reduce future costs, managing resources. The two reinforce each other without either being mandatory.

A player who only does sync sessions earns and spends during adventures. A player who also engages with async activities has more options — better gear, more potions, a crafted item that provides an edge. But the sync-only player can buy what the async player crafts, so both paths work.

---

## Death and Resurrection — Consequences with Compassion

### Philosophy

Death must matter or combat has no stakes. But permanent death in a voice RPG — where the player has built a character through hours of conversation, formed relationships with NPCs, and invested emotionally in a story — is too harsh for most players. The design threads the needle: death has real consequences that create dramatic tension, but doesn't end the character's story.

### The Death Sequence

When a character's HP reaches zero, they're **Fallen** — unconscious and dying. This triggers a dramatic shift in the audio: the ambient sounds fade, the companion's voice becomes urgent, and the DM's narration slows and drops in pitch. The player is still listening, still present, still experiencing the story.

**Death saving throws** begin. Three rolls, visible on the HUD with heightened audio treatment — these are the most dramatic dice rolls in the game. The companion and any party members narrate their attempts to help. Success stabilizes the character. Three failures means **death**.

### What Death Means

A dead character enters **Mortaen's domain** — the border between life and death, tended by the god of endings. This is not a game-over screen. It's a narrative experience.

The player hears Mortaen's voice (or one of Mortaen's aspects) — calm, ancient, not unkind. They're offered a choice, and the choice has consequences:

**Return with a cost.** Mortaen allows the character to return to life, but something is taken. Possible costs, narratively appropriate to the situation:

- A permanent stat reduction (small but meaningful — a reminder)
- Loss of a treasured item (Mortaen claims something from the character's inventory)
- A mark of death visible to NPCs who know what to look for (changes some NPC interactions)
- A fragment of memory lost (the DM occasionally references something the character "can't quite remember")
- A debt to Mortaen — a task the god requires, which becomes a personal quest

The cost escalates with repeated deaths. The first death is a gentle warning. The third death takes something significant. This creates real consequence without permanent loss.

**Linger in the between.** For players who want a more dramatic experience, lingering in Mortaen's domain offers a short narrative encounter — a conversation with the death god, a vision of something important, a glimpse of a dead NPC or a lost memory. This is optional, atmospheric content that rewards the emotional investment of dying rather than punishing it.

### Party Death Mechanics

If the entire party falls, the encounter ends in defeat. The party wakes up somewhere safe — dragged to safety by NPCs, rescued by a patrol, or simply deposited at the edge of Mortaen's domain and returned. The world reacts: the quest they were attempting has new complications, the enemy they were fighting has advanced their plans, and NPCs comment on the defeat.

Total party wipes should be rare — the DM is prompted to scale encounters fairly, and the companion provides tactical guidance. When they happen, they should feel like a dramatic setback in the story, not a punishment.

### Companion Death

Companion NPCs can be knocked unconscious in combat (creating intense dramatic moments) but cannot permanently die during normal play. A companion's death, if it ever occurs, is a major narrative event — scripted, story-driven, and emotionally devastating. It should never happen randomly in a routine encounter. If the story demands it, the companion's death becomes the defining moment of that chapter of the player's journey.

---

## PvP Design — Structured, Opt-In, Story-Driven

### Philosophy

PvP serves the narrative, never undermines it. No open-world ganking. PvP exists as a meaningful story layer for players who want it, always structured around faction conflict with real narrative stakes. Players who opt out miss nothing essential.

### Opt-In at Multiple Levels

**Player-level setting:**
- Players flag themselves as open to PvP encounters or not
- PvP-flagged players gain access to faction conflict content others don't see
- Non-PvP players have a fully cooperative experience with no penalty

**Session-level consent:**
- When a potential PvP encounter arises, all parties confirm before escalation
- The DM frames consent naturally: "The warriors of the Iron Pact block your path. Their captain's hand rests on her sword. This could turn violent. Do you stand your ground?"
- Both a consent check and a narrative beat

### Faction Conflict as the PvP Framework

PvP is always *about something* — a contested resource, a disputed territory, a relic two factions both claim. Diplomacy is attempted first — persuasion checks, negotiation, roleplay. If it fails, combat. The winner's faction gains control, affecting the world state.

### Structured PvP Modes

**Arena Combat**
- In-world fighting pits and tournament grounds
- Own ranking system, seasonal tournaments, rewards
- DM narrates with sports-announcer energy
- Pure skill-based PvP in a controlled, consensual setting

**Territory Control**
- Guilds/factions compete for control of regions
- Mix of sync PvP sessions (battles) and async strategy (fortification, resource allocation, alliances)
- God-agents orchestrate flashpoints where faction interests collide
- Controlling territory grants async benefits: better crafting resources, unique quests, strategic advantages against the invasion

**Heists & Espionage**
- One party defends (vault, convoy, VIP NPC), another party tries to take it
- DM runs both sides simultaneously
- Inherently dramatic in voice — planning, deception, adapting when things go wrong

**Social & Political PvP**
- Spying on factions by infiltrating sessions
- Spreading misinformation, brokering alliances
- "PvP" without swinging a sword — player-driven intrigue and politics
- Voice makes persuasion and deception feel real

### Voice Changes PvP Fundamentally

No mechanical skill gap from mouse accuracy or button timing. What differentiates players: decision-making, creativity, teamwork, persuasion. Players can potentially *talk their way out* of PvP encounters — a high-charisma bard defusing a faction confrontation through pure roleplay is a peak experience unique to this game.

### PvP Toxicity Guardrails

- DM moderates all PvP encounters — can de-escalate or end encounters that cross behavioral lines
- Post-PvP ratings feed into reputation system
- God-level intervention for griefing — repeatedly targeting the same player triggers deity response
- Session tone system applies — "heroic adventure" keeps PvP chivalrous; "gritty and dark" allows harder edges
- The invasion as pressure valve — if faction infighting gets too intense, void creatures escalate and gods call a truce

---

## Seasonal Arc Structure

The overarching narrative unfolds across seasons. Each season shifts the world state and meta-narrative while providing a natural content and monetization cadence.

| Season | Theme | World State |
|---|---|---|
| **Season 1** | First Contact | Creatures appear, chaos and survival, nobody knows what they are |
| **Season 2** | Patterns Emerge | Enough intel gathered that gods form theories, factions solidify |
| **Season 3** | Expedition to the Source | High-level players push into dangerous territory, seeking answers |
| **Season N** | The Reckoning | The guilty god is exposed, the community fractures and reforges around new allegiances |

### The Slow Burn

| Phase | What Players Experience |
|---|---|
| **Early game** | Veythar is helpful, beloved. Players who chose this patron feel good about it. |
| **Mid game** | Cracks appear. Contradictions. Quests that lead *away* from certain discoveries. |
| **Community theorizing** | Players compare notes across factions. Theories circulate. |
| **The reveal** | Season-defining moment that hits differently depending on allegiance. |
| **Post-reveal** | Do followers abandon their god? Civil war? Forgiveness? The reveal begins a new story. |

### Collective Discovery

Across thousands of sessions, parties discover clues that feed into the world state. God-agents synthesize discoveries and adjust the narrative. No single player sees the whole picture — the community collectively drives the story forward.

---

## Content Moderation — Layered Approach

### Core Challenges

1. **Player-to-NPC abuse** — Players will test AI boundaries; need to distinguish harmless fun from genuinely toxic behavior
2. **Player-to-player toxicity** — Voice chat is the primary input, not just communication; can't simply mute and keep playing
3. **Narrative edge cases** — Morally gray roleplay vs. using fiction as cover for toxic behavior

### Moderation Layers

**Layer 1: The AI DM as First Line of Defense**
- The DM is present in every session, listening to everything, with narrative authority
- Inappropriate behavior triggers in-world consequences, not system pop-ups
- Player does something awful → NPC reacts with disgust, town guard intervenes, reputation suffers

**Layer 2: AI Behavioral Guardrails**
- NPCs and DM have hard content boundaries baked in
- Will not narrate graphic sexual content, child abuse scenarios, or generate hate speech regardless of provocation

**Layer 3: Real-Time Voice Analysis (Player-to-Player)**
- Speech-to-text with toxicity classification on voice streams
- Targets clear violations: slurs, targeted harassment, threats
- Graduated response: quiet warning → temporary mute → session removal → account consequences

**Layer 4: Reputation & Social Systems**
- Post-session ratings with specific feedback ("great roleplayer," "disruptive")
- Reputation score affects matchmaking — good players matched with good players
- Toxic players face longer matchmaking times or restricted pools

**Layer 5: Party-Level Controls**
- Party leaders can kick players mid-session
- Sessions can be set to friends-only or invite-only
- Player flagging for review

### In-World Consequences as Moderation (The God Layer)

For moderate behavioral issues, the world responds narratively:
- God of justice sends paladins after persistently antisocial players
- Patron deity withdraws favor
- The player becomes a narrative villain — NPCs refuse service, bounties placed
- Not banned, but *narratively cornered*
- Hard system enforcement still exists for truly toxic behavior

### Session Tone System

- Sessions have a tone rating at creation (similar to movie ratings)
- **Heroic Adventure:** Tighter guardrails, lighter themes
- **Gritty & Dark:** More moral ambiguity, betrayal, darker themes — but still has hard limits
- Sets expectations for all players joining; AI DM calibrates narration and boundaries to match

---

## Monetization

### Cost Reality

Higher per-user costs than a traditional MMO. Every session involves real-time AI inference for the DM, NPCs, and god-agent interactions. Every async check-in is an AI call. Voice synthesis and speech-to-text run continuously. Monetization must cover this sustainably.

### Free Trial — Time-Limited, Full Experience

- **7-day free trial** of the complete game — not a crippled free tier
- Full sync sessions, async activities, world access
- Enough time for character attachment and a few sessions
- Treat trial cost as marketing spend

### Subscription — The Core Revenue Stream

**Premium Subscription (~$15–20/month, subject to cost modeling)**
- Unlimited sync sessions
- Full async activity access with reasonable default timers
- Full world and storyline access
- Premium DM narration quality (better voice models, more detailed descriptions)
- Priority matchmaking

**Guild / Group Subscription**
- Discounted rate for parties that play together regularly
- Incentivizes committed social groups — the exact behavior that drives retention
- Could include shared guild benefits (guild hall access, group async bonuses)

### Battle Pass — Seasonal Narrative Model

Paired with seasonal story arcs:
- Tracks engagement and rewards progression through the season
- Free track: basic cosmetic rewards for subscribers
- Premium track: exclusive voice cosmetics, narrative rewards, unique companion content

### Voice Cosmetics — The Killer Category

In a game with no visual character model, your voice IS your identity:
- Character voice options — deep resonant warrior, ethereal mage, grizzled ranger
- Accent and speech pattern options
- Weapon and spell sound effects — a sword that hums, a spell that crackles distinctly
- Critical hit signature sounds
- Ambient personal themes
- DM narration style preferences for personal moments

### Narrative Cosmetics

- Personalized backstory integration woven into DM narration by the AI
- Unique titles and epithets NPCs use when addressing you
- Personal legends that bards in taverns literally sing about (AI-composed and performed)
- Custom god-whisper tones from patron deity
- Gear narration — rare cosmetic gear gets described to the whole party ("a warrior enters wearing black dragonscale, her blade trailing frost")

### Property System — Inspired by Second Life

**Dual acquisition path:**
- **Earn through play:** Dedicated async work over time — grinders feel rewarded
- **Purchase to accelerate:** Spend to acquire faster — spenders get convenience
- Neither feels unfair because property is lateral (status and experience, not combat power)

**Property types:** Personal spaces (cottages, towers, workshops), commercial (shops, taverns, trading posts), guild-level (guild halls, fortresses, territory headquarters).

**Audio-defined spaces:** Property IS its soundscape — seaside cottage with waves and gulls, mountain forge with hammering and wind. Customizing the soundscape IS decorating your home.

### Premium Content (À La Carte)

**Campaign Modules:** Self-contained premium storylines with higher production value. Potentially guest-written by D&D adventure designers or fantasy authors. Solo, party, or special event formats.

**Companion Unlocks:** Rare NPC companions with deeper personalities, unique abilities, elaborate relationship arcs. Base companions are solid; premium companions have the most compelling stories and best banter.

### Whale Strategy — Social and Positive

High-spender content focused on guild and community, not individual power:
- Premium guild halls with exclusive features
- Exclusive guild storylines
- Commission custom narrative events (guild founding story becomes world canon, narrated by the gods)
- Patron-level world event sponsorship — a guild funds a city's defense and receives narrative credit

### Monetization Red Lines

- **No pay-to-win.** No stat boosts, no stronger weapons, no mechanical power for money. Ever.
- **No pay-to-skip-grind on core mechanics.** Async timers must be reasonable by default. Small convenience acceleration is acceptable; "pay or wait forever" is not.
- **All purchases are lateral** — cosmetic, narrative, experiential, or convenience. Never mandatory for competitive play or story progression.

---

## The Opening Experience — First 30 Minutes

### Philosophy

The opening must accomplish five things in roughly 30 minutes:
1. Give the player enough context about Aethos to make meaningful choices
2. Immerse them in their culture and make them care about it
3. Teach basic navigation and interaction through play, not tutorials
4. Introduce the reality of the invasion through a personal, emotional moment
5. Deliver a call to action that sends them into the wider world

The structure follows: **prologue → creation → normalcy → disruption → call to action.**

### Phase 1: The Prologue (60–90 Seconds)

Before character creation, the game opens with a **narrated prologue** — grander than the DM's voice, establishing scale and stakes. Think the opening of a film or the first page of a novel. Atmospheric sound design underneath: the sounds of a living world gradually overtaken by the wrongness of the Hollow.

The prologue establishes:
- Aethos was a living, beautiful world tended by gods
- The Veil broke (no one knows why or how — seeds the mystery)
- The great city of Aelindra fell — now only the Voidmaw remains
- Something pours through that doesn't speak, think, or stop
- The gods disagree on what it is; the peoples disagree on how to fight it
- The world needs heroes — and that's where you come in

**No choices required.** The player just listens and is drawn in. By the end they have enough context to engage: fantasy world, something terrible happened, nobody understands it, and you matter.

### Phase 2: Transition to Creation (~30 Seconds)

The narrator's voice shifts to the DM's voice. Scale shifts from epic to personal:

> *"But before we begin... who are you?"*

Now we're in character creation. The player already knows the stakes. They know about the Veil and the Hollow. They don't need to understand every faction and god — just enough to make their first choices meaningful.

### Phase 3: Character Creation (10–15 Minutes)

*(Detailed in Character Creation section above.)*

Race → Class → Divine Patronage → Starting Placement → Name & Backstory

### Phase 4: Starting Culture Placement (Hybrid Approach)

New players should not choose a starting culture from a list of unfamiliar names. Instead:

**Default: The story places you.** Your race, class, and divine patronage imply a natural starting culture. The system selects the most narratively coherent option and the DM narrates you into it. An Elari Seeker who chose Veythar → Aelindran Diaspora. A Draethar Warrior who chose Kaelen → Drathian Clans. It feels like destiny, not a menu.

**For ambiguous combinations:** The DM offers a light narrative choice between 2–3 options that make sense:

> *"A scholar like you... where did you study? The great libraries of the Accord of Tides? The quiet archives of the Dawnspire? Or among the Aelindran refugees, carrying the torch of a lost city?"*

The player chooses between vivid images, not unfamiliar names. The DM has already narrowed options to what fits.

**Override always available:** If a player says "actually, I had something else in mind," the DM pivots. Experienced players and those with strong preferences can redirect.

### Starter Zone Safety Rules

All starting placements must be in regions safe enough for new players. Dangerous regions are never starting zones.

**Valid Starter Zones:**

| Culture | Region | Safety | Notes |
|---|---|---|---|
| **Sunward Accord** | Sunward Coast / Accord of Tides | Safe | Default fallback for any combination. Most common start. |
| **Drathian Clans** | Drathian Steppe (settled areas) | Safe-Mid | Clan camps and garrison towns are safe. Danger is at the Ashmark edge. |
| **Thornwardens** | Thornveld (southern communities) | Safe-Mid | Established communities near southern edges. Deep forest comes later. |
| **Keldaran Holds** | Keldara Mountains (established holds) | Safe-Mid | Mining towns and holds are safe. The deep places are not. |
| **Dawnsworn** | Dawnspire Highlands | Safe | Inherently safe — healing and pilgrimage region. |
| **Tidecallers** | Shattered Isles (port towns) | Safe-Mid | Individual islands and ports are fine. Open sea danger comes later. |
| **Marsh Kindred** | Pale Marshes (Kindred settlements) | Mid | Viable but must start in a safe settlement, not the open marshes. |
| **Aelindran Diaspora** | Sunward Coast / Accord of Tides | Safe | Refugees settled in safe southern regions. |

**Never Starting Zones:** The Voidmaw, the Ashmark, the Northern Reaches, the Umbral Deep.

**Displacement as backstory:** If a character's ideal placement would be too dangerous, the system places them in the nearest safe region with a narrative reason. A Korath whose combination points toward the Northern Reaches: *"Your family fled south when the Ashmark expanded. You grew up in the Keldaran Holds, but the stories your parents tell of a homeland you never knew drive you forward."* The displacement itself becomes compelling backstory and motivation.

### Phase 5: Normalcy (5 Minutes of Play)

The player experiences a brief slice of life in their starting culture. Interactive, not narrated — this is where they learn core mechanics through natural activity:

- Navigate a familiar environment (teaches navigation)
- Interact with 1–2 NPCs (teaches conversation mechanics)
- Perform a simple task or skill check (teaches dice/action mechanics)
- Meet your starting companion NPC (establishes the guidance system)
- The world feels warm, alive, and worth protecting

### Phase 6: Disruption

The Hollow intrudes. Suddenly, personally, terrifyingly. The specific disruption varies by starting culture but always accomplishes the same thing: the world you just learned to care about is under threat.

### Phase 7: Call to Action

An NPC — mentor, family member, companion, or authority figure — gives you a personal, class-appropriate reason to act. Everyone leaves their starting area not because a quest marker says to, but because the story made it necessary.

**The Mystery Seed:** Somewhere in the opening, the DM plants a detail that doesn't add up. A question without an answer. A moment where someone changes the subject too quickly. The mystery starts whispering from the first session, even if the player doesn't realize it yet.

### Culture-Specific Opening Sketches

**Sunward Accord**
You're in the market at the Accord of Tides. Vendors calling, music playing, harbor sounds. You run an errand — learn navigation by finding your way through the market. Meet your companion. The world is warm and safe. Then a rider arrives from the north — wounded, horse lathered. The market falls silent. The Ashmark has expanded. A town that was safe last week is gone. The rider collapses. The market doesn't go back to normal. Your mentor tells you something that sets you on your path.

**Drathian Clans**
You're riding with your clan on the steppe. Wind, hoofbeats, easy banter. Your clan chief gives you a routine patrol task. You ride out, learn navigation and your first skill check. Then you find a Hollow incursion — a small breach, a few creatures that shouldn't be this far south. The land is wrong around them. Your first combat encounter: brief, terrifying. You report back. The clan chief's face tells you everything — this has never happened this far from the front.

**Thornwardens**
You're in the canopy, helping your community with a seasonal task. The forest sounds layered and alive. Your mentor teaches you to listen to the forest. Then the forest *reacts* — trees groaning, birds scattering, a silence spreading from the north. Something is pushing against the Thornveld's edge. The forest is resisting, but it's afraid. Your mentor has never seen this before.

**Keldaran Holds**
You're in the mines or a forge, learning your craft. The sounds of industry, echoing stone. A routine day. Then a tremor — not an earthquake, something else. The Korath feel it first: something wrong in the deep stone. An expedition returns from the Umbral Deep with news — a tunnel that's been stable for centuries has... changed. The stone is wrong. Something is seeping up from below.

**Marsh Kindred**
You're navigating the marshes on an errand. Fog, water, the sound of secrets. Your companion guides you through hidden paths. You deliver a message — or retrieve one. Then you stumble on something you weren't meant to find: a meeting between two people discussing something they clearly want kept quiet. Information about the invasion that doesn't match the official story. You've been seen. Now you have a secret — and a target on your back.

**Dawnsworn**
You're in a monastery, tending to the wounded. Dawn light, bells, chanting. A healer's routine. Then a new wave of casualties arrives from the Ashmark — worse than before, and with wounds that don't heal normally. The Hollow is changing, adapting. Your mentor is troubled — the old methods aren't enough. You're sent out not to fight, but to find answers about why the wounded aren't recovering.

**Tidecallers**
You're on a ship or an island shore. Waves, wind, the thrill of open water. A routine voyage or fishing expedition. Then you find something in the water — or on a previously charted island — that shouldn't be there. A substance, a creature, a wrongness in the sea itself. The Hollow's influence has reached the ocean. Nythera's domain is no longer safe. Your captain sends you to the mainland with a warning no one has heard yet.

**Aelindran Diaspora**
You're in a refugee quarter, sorting recovered relics for a scholar. The bittersweet atmosphere of people preserving what they've lost. An older Elari NPC tells you about Aelindra. Then you find something in the relics that doesn't make sense — an artifact with unrecognizable markings, or a journal entry contradicting the official Voidfall story. The NPC goes pale. *"Where did you find this?"* Your story begins with a mystery, not a battle.

### Post-Opening: Into the World

After the opening, every player has:
- A character they built through conversation
- A companion NPC who grounds them
- An emotional connection to what's at stake
- Basic mastery of navigation, interaction, and their first mechanics
- A personal reason to leave home and enter the wider world
- A seed of mystery planted in their mind

The game opens up. The DM offers paths forward. The wider world of Aethos awaits.


## Open Game Design Questions

*Resolved:*

- [x] **Combat resolution mechanics** — Hybrid model defined: LLM decides when, rules engine resolves how. Tools: `request_attack`, `request_skill_check`, `request_saving_throw`. See *Tech Architecture — Dice & Mechanics Tools*.
- [x] **Core game mechanics** — d20 + modifier vs. DC system, skill list, status effects, difficulty scaling, and failure-as-complication philosophy. See *Game Mechanics* section above.
- [x] **NPC persistence** — `npc_dispositions` state table with per-player scores, decay toward default. NPC schedules driven by simulation layer 1. See *World Data & Simulation — NPC Schema*.
- [x] **NPC design** — Tier 1/2 NPC categories, companion system (five functions), relationship mechanics, voice and personality design. See *NPC Design* section above.
- [x] **World simulation model** — Four-layer system: time-driven, simulation tick, god-agent heartbeat, event-driven cascades. See *World Data & Simulation — World Simulation Rules*.
- [x] **Session lifecycle** — Start, mid-session persistence, narrative end, reconnection, cross-session continuity. See *Tech Architecture — Session Lifecycle*.
- [x] **The economy** — Silver-based currency, context-dependent pricing via `value_modifiers`, merchant disposition and faction reputation affecting prices, sync/async economy loop. See *The Economy* section above.
- [x] **Death and resurrection** — Fallen → death saves → Mortaen's domain → return with escalating cost. Companion death is narrative-only. See *Death and Resurrection* section above.
- [x] **Client/mobile architecture** — Expo React Native, layered HUD system, reactive data flow, four-channel audio mixing, full session flow. See *Tech Architecture — Client Architecture*.

*To be developed as design continues:*

- [ ] **Detailed ability design** — Specific abilities for each archetype × god combination. The skill system and status effect framework are defined; individual ability lists per class are not.
- [ ] **The crafting system** — How crafting works mechanically, what can be made, how async timers integrate with the real-time clock. The economy section defines crafting's role; the mechanics are undesigned.
- [ ] **The party system** — Matchmaking, AI companion behavior in groups, party roles, group dynamics. Companion extraction from ventriloquism to independent agent is a post-MVP decision (see *Tech Architecture — Open Questions*).
- [ ] **Onboarding flow** — The first 30 minutes from installation to first session. The Opening Experience section defines the narrative flow; the client UX for onboarding (permissions, tutorial overlays, first-time setup) is undesigned.
- [ ] **The mystery questline** — How clues are discovered, shared, and synthesized across the player base. The seasonal arc structure outlines the macro narrative; the mechanics of collective discovery are undesigned.
- [ ] **Seasonal content structure** — How seasons work mechanically, what resets, what persists. The seasonal arc provides the narrative framework; the technical implementation is undesigned.
- [ ] **Accessibility** — Audio-first design for visually impaired players; options for hearing-impaired players (real-time captions from STT, text-input mode as voice alternative).
- [ ] **Tutorial and early game** — How to teach voice-first RPG mechanics to players new to the genre. The Opening Experience handles narrative onboarding; mechanical onboarding (how to use the HUD, what dice rolls mean, how combat works) needs design.
- [ ] **Cold start / player density** — AI NPC parties help, but how to seed the world and encourage organic grouping at launch.

---

*This document is living — it will be expanded as game design continues.*
