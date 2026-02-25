# Divine Ruin: The Sundered Veil — Game Design Document

## About This Document

This is the comprehensive game design document for **Divine Ruin: The Sundered Veil**. It defines every player-facing system: character creation, classes, progression, combat, navigation, async play, PvP, moderation, monetization, and the opening experience.

**Related documents:**
- *Product Overview* — What we're building and why (start here if you're new)
- *Aethos Lore Bible* — World history, cosmology, the pantheon, the core mystery
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

The fiction leads, not spreadsheets. Inspired more by lightweight systems (Powered by the Apocalypse) than heavy crunch (D&D 5e full rules). Heavy mechanical crunch doesn't translate well to voice-only interaction. Mechanically, the DM requests checks and the rules engine resolves them — the DM never applies raw math. See *Technical Architecture — Dice & Mechanics Tools* for the hybrid model: the LLM decides *when* a check is needed, the rules engine decides *how* it resolves.

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

### Session Types

| Type | Duration | Party Size | Description |
|---|---|---|---|
| **Quick Quest** | 20–30 min | 1–2 players + AI companions | A focused encounter or short mission. Solo-friendly. |
| **Standard Session** | 45–60 min | 2–4 players + optional AI | A full adventure arc with exploration, challenge, and narrative. |
| **Deep Dive** | 75–90 min | 3–5 players | Extended session for major story beats, boss encounters, or complex challenges. |
| **Raid** | 60–90 min | 5+ players | Large-scale encounters against major Hollow threats. Requires coordination. |
| **Solo Async** | 5–15 min | 1 player | Async check-ins: crafting, training, side quests, god whispers. |

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

Boss encounters are events: music shifts, narration elaborates, god-agents may intervene. Multi-phase structures with environmental hazards announced through audio cues. HUD may briefly show boss health bar or phase indicator — keep visual flourishes sparse so they feel special.

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

## NPC Design

- AI-driven NPCs with persistent personality, backstory, and relationship memory — implemented as tier 1 and tier 2 NPC entities in JSON schemas (see *World Data & Simulation — NPC Schema*). Tier 1 NPCs have authored prose descriptions, backstories, and gated knowledge trees. Tier 2 NPCs have tags and attributes only; the DM improvises dialogue from structured data.
- NPCs remember past interactions across sessions via the `npc_dispositions` state table, which tracks per-player disposition scores with decay toward default (~1 point/day). The `update_npc_disposition` tool modifies these in real-time.
- NPC companions fill party slots when human players aren't available — ventriloquized by the DM agent using `[CHARACTER, emotion]: "dialogue"` tags routed to per-character `voice_id` in the TTS pipeline.
- NPCs must feel like characters with motivations, not stat blocks that talk — the NPC schema includes `personality`, `speech_style`, `mannerisms`, and `secrets` fields that inform the DM's portrayal.
- Companion NPCs double as guidance systems (see Player Guidance above) and emotional anchors for new players
- NPCs follow time-driven schedules (simulation layer 1) — their location changes based on time of day, creating a living world where the blacksmith closes shop at night and the bartender appears in the evening.

---

## Asynchronous Play — The Living World Between Sessions

Sync is the main event; async is the connective tissue that keeps players engaged between sessions. The core loop: **make a strategic decision → wait for it to resolve → receive a narrated outcome → make the next decision.** AI narration means every check-in feels unique, not repetitive. The world simulation runs on a real-time clock (1 game-minute = 1 real minute, 24/7) — see *World Data & Simulation — World Simulation Rules* — so async activities resolve against a living world, not a frozen one.

### Async Activity Types

**Crafting & Workshop Management**
- Choose what to craft: higher risk/longer wait/rare materials vs. safe/quick options
- Make a skill check that influences odds, then the item "cooks" over real time
- Return to a narrated outcome — success, partial success, unexpected results
- Each check-in presents a new decision point

**Training & Skill Development**
- Visit a mentor NPC, choose a skill tree to work on, have a brief voiced scene
- Character trains over a real-time period
- Return to a culmination scene — mastery, plateau, or a new approach needed

**Side Quests & Mini-Quests (5–10 min)**
- Solo errands: patron god tasks, NPC companion favors, intel gathering
- Quick self-contained voice encounters (just you and the DM)
- Results feed back into the main storyline — a clue, a shortcut, a new ally

**Resource & Territory Management**
- Guild/party claims territory (village, keep, trade route)
- Strategic decisions: station guards, invest in fortifications vs. commerce, faction alliances
- Plays out over real time within the larger god-driven geopolitical simulation
- Consequences are emergent — the war god's faction might raid your undefended trade route overnight

**NPC Network Management**
- Send companions on errands ("scout the northern pass") — they return hours later with results or trouble
- Assign apprentices to study, commission merchants for rare materials
- Building a network of characters and activities that feed into sync sessions

**Faction Reputation (Slow Burn)**
- Async decisions accumulate into faction standing over time
- Higher standing unlocks better quests, unique items, hidden areas
- Rewards consistent engagement without punishing absence — slower progress, not blocked progress
- Benefits are lateral (more options, info, flavor) rather than strictly vertical power increases

**God Whispers & Re-engagement**
- Patron deity reaches out with visions, warnings, cryptic messages
- Short, atmospheric interactions that make the world feel alive
- Notification hook: "Tharion, the Shadow Weaver, has a message for you" > "daily login reward available"

**Party Coordination**
- Leave voice messages for party members
- AI DM can facilitate: session recaps, open thread reminders, preparation suggestions

**Seasonal & World Events with Timers**
- Gods announce events with real-world countdowns ("a comet approaches in 72 hours")
- Async players prepare: gather materials, fortify, choose sides
- Event fires as a massive sync experience shaped by async preparation

### Async Design Principles

1. **Async must matter to sync.** Crafted gear used in the next dungeon. Training unlocks an ability just in time. Preparation, not busywork.
2. **Async must not be required.** Sync-only players should never feel punished. Async provides lateral advantages (options, information, flavor) not mandatory power.
3. **The timer isn't the content — the decisions on either side are.**
4. **Notifications are narrative hooks.** Every ping is a tiny story: "The blade is forged — Grimjaw awaits your inspection."

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

*Resolved by recent architecture work:*

- [x] **Combat resolution mechanics** — Hybrid model defined: LLM decides when, rules engine resolves how. Tools: `request_attack`, `request_skill_check`, `request_saving_throw`. See *Tech Architecture — Dice & Mechanics Tools*.
- [x] **NPC persistence** — `npc_dispositions` state table with per-player scores, decay toward default. NPC schedules driven by simulation layer 1. See *World Data & Simulation — NPC Schema*.
- [x] **World simulation model** — Four-layer system: time-driven, simulation tick, god-agent heartbeat, event-driven cascades. See *World Data & Simulation — World Simulation Rules*.
- [x] **Session lifecycle** — Start, mid-session persistence, narrative end, reconnection, cross-session continuity. See *Tech Architecture — Session Lifecycle*.

*To be developed as design continues:*

- [ ] **Detailed ability design** — Specific abilities for each archetype × god combination
- [ ] **The crafting system** — How crafting works mechanically, what can be made, how async timers integrate with the real-time clock
- [ ] **The party system** — Matchmaking, AI companion behavior, party roles, group dynamics. Companion extraction from ventriloquism to independent agent is a post-MVP decision (see *Tech Architecture — Open Questions*).
- [ ] **Onboarding flow** — The first 30 minutes of gameplay from installation to first session. How the client guides a new player through character creation.
- [ ] **The economy** — Currency, trade, item values, the relationship between async and sync economies. Item `value_modifiers` in the schema support context-dependent pricing, but the full economic model is undesigned.
- [ ] **Death and resurrection** — What happens when you die? How does Mortaen's domain work mechanically?
- [ ] **The mystery questline** — How clues are discovered, shared, and synthesized across the player base
- [ ] **Seasonal content structure** — How seasons work mechanically, what resets, what persists
- [ ] **Accessibility** — Audio-first design for visually impaired players; options for hearing-impaired players
- [ ] **Tutorial and early game** — How to teach voice-first RPG mechanics to players new to the genre
- [ ] **Cold start / player density** — AI NPC parties help, but how to seed the world and encourage organic grouping
- [ ] **Client/mobile architecture** — UI framework, screen design, HUD layout, audio mixing, session flow on screen. See *Product Overview — Document Map* for status.

---

*This document is living — it will be expanded as game design continues.*
