# Divine Ruin — World Data & Simulation

## Purpose

How is the game world authored, stored, and simulated? This document defines the content authoring format (JSON schemas for all game entities), the world simulation rules (how things change over time), and the data model (what's stored where and how it's queried). It bridges the gap between the static lore (see *Aethos Lore Document*) and the live game state that the DM agent reads from (see *Technical Architecture — DM Agent Architecture*).

**Design philosophy:** Content is sparse structured data. The DM agent brings it to life through narration. Authors (human or AI) define *what exists* and *the rules for how it changes*. The LLM decides *how to describe it*.

---

## Content Authoring Format

All game content is authored in JSON. The schemas are designed for machine generation with human review — most content is AI-generated, then reviewed and tuned by human authors.

### Content Tiers

**Tier 1 (authored):** Key story locations, major NPCs, quest-critical items. These include a `description` field with authored prose that the DM uses as a foundation. Human-written or AI-generated with careful human editing.

**Tier 2 (generated):** Minor locations, ambient NPCs, common items. These have tags and attributes only — no authored prose. The DM improvises descriptions from the structured data. Can be generated on demand when a player enters an undefined area, then persisted for consistency on return visits.

### Entity Schemas

#### Locations

Locations are the fundamental spatial unit. Players are always *at* a location. Locations have base content that can be modified by conditions (time of day, corruption level, quest progress, etc.).

```json
{
  "id": "wailing_market",
  "name": "The Wailing Market",
  "tier": 1,
  "district": "ashfall",
  "region": "veldross",
  "tags": ["market", "outdoor", "crowded", "alchemical"],
  "description": "A labyrinth of rickety stalls crammed into the gap between two leaning tenements. The air is thick with sulfur and dried herbs. Vendors call their wares with forced cheer, but everyone keeps one eye on the alley mouths.",
  "atmosphere": "anxious commerce, sensory overload",
  "key_features": [
    "cracked fountain, dry for years",
    "alchemist row along the eastern wall",
    "a boarded-up stall with Thornwatch seal marks"
  ],
  "hidden_elements": [
    {
      "id": "maren_compartment",
      "discover_skill": "perception",
      "dc": 14,
      "description": "hidden drawer beneath Maren's counter"
    }
  ],
  "exits": {
    "north": {"destination": "temple_quarter"},
    "south": {"destination": "harbor_gate"},
    "east": {"destination": "merchant_row", "requires": "!city_lockdown"}
  },
  "conditions": {
    "time_night": {
      "description_override": "The stalls are shuttered and dark. A single lantern swings on a chain over the dry fountain.",
      "atmosphere": "eerie quiet, footsteps echo",
      "npcs_remove": ["market_vendors"],
      "danger_level": 2
    },
    "hollow_corruption >= 5": {
      "atmosphere_add": "wrongness in peripheral vision, whispers from nowhere",
      "danger_level_add": 2,
      "new_encounters": ["shadow_wisp_patrol"]
    },
    "quest:silent_patrol:stage >= 3": {
      "key_features_add": ["Thornwatch soldiers posted at north exit"],
      "npcs_add": ["thornwatch_sergeant"]
    }
  },
  "ambient_sounds": "market_bustle",
  "ambient_sounds_night": "wind_empty_streets"
}
```

**Key fields:**
- `tier`: 1 (authored) or 2 (generated). Tier 1 locations have `description` prose; tier 2 locations have only `tags` and `atmosphere` keywords.
- `conditions`: Overlays that modify the base content based on game state. Conditions can override descriptions, add/remove NPCs, adjust danger levels, and enable new encounters. Conditions are evaluated by the background process when building the DM's warm prompt layer.
- `hidden_elements`: Things that require active discovery (skill checks). The DM knows these exist but only reveals them when the player searches and succeeds.
- `exits.requires`: Condition expressions for blocked paths. The `move_player` tool validates these.

**Tier 2 example (generated, minimal):**

```json
{
  "id": "ashfall_alley_7",
  "name": "Narrow Alley",
  "tier": 2,
  "district": "ashfall",
  "region": "veldross",
  "tags": ["alley", "narrow", "dim", "residential"],
  "atmosphere": "claustrophobic, dripping water",
  "exits": {
    "north": {"destination": "wailing_market"},
    "south": {"destination": "ashfall_tenements"}
  },
  "danger_level": 1
}
```

No authored description, no hidden elements, no conditions. The DM reads "narrow, dim, residential alley with dripping water" and generates: *"You duck into a tight alleyway between crumbling tenement walls. Water drips from somewhere above, and the sounds of the market fade behind you."*

#### NPCs

NPCs are characters the player can interact with. They have personalities, knowledge, schedules, and dispositions that shift based on player actions.

```json
{
  "id": "maren_thell",
  "name": "Maren Thell",
  "tier": 1,
  "role": "alchemical merchant",
  "species": "human",
  "gender": "female",
  "age": "mid-40s",
  "appearance": "weathered face, deep-set eyes, stained leather apron, calloused hands that move precisely",
  "personality": ["cautious", "shrewd", "privately compassionate", "paranoid about authority"],
  "speech_style": "clipped and transactional with strangers, warmer once trust is earned, avoids eye contact when lying",
  "mannerisms": ["wipes hands on apron when nervous", "lowers voice when sharing secrets"],
  "backstory_summary": "Former Thornwatch field medic who left the service after seeing something in the Hollowmere she won't discuss. Now sells alchemical supplies and secretly smuggles restricted reagents to people who need them.",
  "knowledge": {
    "free": [
      "general market gossip",
      "alchemical ingredient properties",
      "weather and trade conditions"
    ],
    "disposition >= friendly": [
      "missing Thornwatch patrol was investigating something specific",
      "she's heard whispers about a new Hollow incursion"
    ],
    "disposition >= trusted": [
      "she's smuggling reagents",
      "she left the Thornwatch because of what she saw at Hollowmere"
    ],
    "quest_triggered": {
      "quest": "silent_patrol",
      "stage": 2,
      "reveals": "the patrol's last known heading was toward the old watchtower"
    }
  },
  "schedule": {
    "06:00-20:00": "wailing_market",
    "20:00-06:00": "maren_house"
  },
  "default_disposition": "neutral",
  "disposition_modifiers": {
    "bought_from_her": 1,
    "mentioned_thornwatch_positively": -1,
    "helped_with_smuggling": 3,
    "threatened_her": -5
  },
  "inventory_pool": "alchemical_supplies_common",
  "secrets": [
    "smuggling restricted reagents",
    "saw something at Hollowmere that broke her faith in the Thornwatch"
  ],
  "faction": "independent",
  "voice_id": "maren_thell_v1",
  "voice_notes": "alto, slightly hoarse, measured pace"
}
```

**Key fields:**
- `knowledge`: Gated information. The DM checks the player's disposition with this NPC and reveals what's appropriate. The `quest_triggered` variant unlocks specific information when a quest reaches a certain stage. This is how information flows naturally through conversation — the DM knows what Maren *could* tell you, and roleplay determines what she *does* tell you.
- `disposition_modifiers`: Named triggers that shift the relationship. The `update_npc_disposition` tool uses these — when the DM calls the tool with `reason: "bought_from_her"`, the tool looks up the modifier value.
- `schedule`: Where this NPC is at what time. The simulation tick uses this to determine who's present at each location. The background process includes only scheduled NPCs in the warm prompt layer.
- `voice_id` and `voice_notes`: For the ventriloquism system. The `tts_node` maps the character name to this voice.

**Tier 2 NPC (template-based):**

```json
{
  "id": "market_vendor_03",
  "tier": 2,
  "name": "Gruff Spice Merchant",
  "role": "spice merchant",
  "species": "human",
  "gender": "male",
  "personality": ["impatient", "loud"],
  "speech_style": "booming voice, sales pitches",
  "schedule": {"06:00-18:00": "wailing_market"},
  "default_disposition": "neutral",
  "inventory_pool": "spices_common",
  "voice_id": "male_merchant_02"
}
```

Minimal. The DM invents the rest.

#### Items

Items have mechanical properties (for the rules engine), economic properties (for merchants and the economy simulation), and narrative flavor (for the DM).

```json
{
  "id": "hollow_ward_amulet",
  "name": "Hollow-Ward Amulet",
  "tier": 1,
  "type": "accessory",
  "subtype": "amulet",
  "rarity": "uncommon",
  "description": "A tarnished silver disc etched with overlapping ward-circles. It hums faintly when the Hollow is near.",
  "tags": ["protective", "anti-hollow", "thornwatch"],
  "weight": 0.2,
  "effects": [
    {"type": "resistance", "target": "hollow_corruption", "value": 2},
    {"type": "passive_alert", "trigger": "hollow_corruption >= 3", "description": "amulet vibrates and grows warm"}
  ],
  "value_base": 150,
  "value_modifiers": {
    "region:hollowmere_border": 1.5,
    "hollow_corruption >= 7": 2.0
  },
  "lore": "Standard issue for Thornwatch patrols near the Hollowmere. Most have been recalled — finding one in civilian hands raises questions.",
  "found_in": ["thornwatch_patrol_gear", "maren_hidden_compartment", "old_watchtower_armory"]
}
```

**Key fields:**
- `effects`: What the rules engine reads. The `apply_status_effect` and mechanics tools check these for resistance calculations, passive triggers, and stat modifications.
- `value_modifiers`: Context-dependent pricing. The economy simulation and merchant tools use these — the same amulet costs more near the Hollowmere where it's needed most.
- `found_in`: Content authoring hint — where this item can be placed as loot or inventory. Not queried at runtime; used during content generation to populate locations and merchants.

**Tier 2 item (templated):**

```json
{
  "id": "healing_potion_minor",
  "tier": 2,
  "name": "Minor Healing Potion",
  "type": "consumable",
  "rarity": "common",
  "tags": ["healing", "potion"],
  "weight": 0.3,
  "effects": [{"type": "heal", "value": "2d4+2"}],
  "value_base": 25
}
```

#### Quests

Quests are state machines. Each quest has stages with objectives, completion conditions, branches, and world effects that ripple into the simulation.

```json
{
  "id": "silent_patrol",
  "name": "The Silent Patrol",
  "tier": 1,
  "type": "main",
  "description": "A Thornwatch patrol sent to investigate Hollow activity near the border has gone silent. Find out what happened to them.",
  "giver": "captain_aldric",
  "giver_context": "given during briefing at Thornwatch headquarters",
  "stages": [
    {
      "id": 1,
      "objective": "Gather information about the patrol in Veldross",
      "hints": [
        "Ask around the market",
        "Check Thornwatch notice boards",
        "Maren Thell was a former field medic — she might know something"
      ],
      "completion_conditions": [
        "learned_patrol_heading OR learned_patrol_members >= 2"
      ],
      "on_complete": {
        "xp": 50,
        "world_effects": ["thornwatch_sergeant_appears_at_market"]
      }
    },
    {
      "id": 2,
      "objective": "Travel to the old watchtower near the Hollowmere border",
      "hints": ["The road north from Veldross leads to the border region"],
      "completion_conditions": ["arrived_at_old_watchtower"],
      "on_complete": {
        "xp": 75,
        "world_effects": ["watchtower_area_unlocked", "hollow_corruption_border += 2"]
      }
    },
    {
      "id": 3,
      "objective": "Search the watchtower for signs of the patrol",
      "hints": ["The watchtower looks abandoned but there are recent tracks"],
      "completion_conditions": ["found_patrol_journal OR found_patrol_survivor"],
      "branches": {
        "found_journal": {
          "next_stage": "4a",
          "world_effects": ["patrol_confirmed_dead"]
        },
        "found_survivor": {
          "next_stage": "4b",
          "world_effects": ["survivor_added_as_temp_npc"]
        }
      }
    },
    {
      "id": "4a",
      "objective": "Bring the patrol journal back to Captain Aldric",
      "completion_conditions": ["delivered_journal_to_aldric"],
      "on_complete": {
        "xp": 200,
        "reputation": {"thornwatch": 5},
        "rewards": ["hollow_ward_amulet", "thornwatch_commendation"],
        "world_effects": ["thornwatch_increases_border_patrols"],
        "unlocks_quest": "hollowmere_investigation"
      }
    },
    {
      "id": "4b",
      "objective": "Escort the survivor back to Veldross",
      "completion_conditions": ["survivor_delivered_to_aldric"],
      "on_complete": {
        "xp": 250,
        "reputation": {"thornwatch": 8},
        "rewards": ["hollow_ward_amulet", "thornwatch_field_promotion"],
        "world_effects": [
          "survivor_becomes_recurring_npc",
          "thornwatch_increases_border_patrols"
        ],
        "unlocks_quest": "hollowmere_investigation"
      }
    }
  ],
  "failure_conditions": {
    "survivor_dies": {
      "world_effects": ["thornwatch_blames_player"],
      "reputation": {"thornwatch": -5}
    },
    "time_limit_exceeded": {
      "days": 7,
      "description": "The trail goes cold after 7 in-game days",
      "world_effects": ["patrol_declared_lost"]
    }
  },
  "global_hints": {
    "stuck_stage_1": "Your companion might suggest checking the market or asking locals",
    "stuck_stage_3": "The watchtower has a cellar — have you checked below?"
  }
}
```

**Key fields:**
- `stages`: Ordered steps with branching. Each stage has `completion_conditions` evaluated against world state flags. The `update_quest` tool checks these conditions and advances the quest when met.
- `branches`: Decision points where the player's approach determines which path the quest takes. Different branches lead to different stages, different rewards, and different world effects.
- `world_effects`: The critical link to world simulation. Completing a quest stage changes things beyond the quest — NPCs appear, corruption levels shift, faction dispositions change. These effects feed into the cascade engine.
- `failure_conditions`: How the quest can fail. Time-based failures use real-time deadlines. Event-based failures (survivor dies) trigger when specific state changes occur.
- `global_hints`: Used by the guidance system. When the DM detects the player is stuck (no progress for N minutes), it can use these hints through the companion NPC or environmental cues.

#### Events / Triggers

Events are things that happen when conditions are met. They're the simulation's output — the way the world reacts to state changes.

```json
{
  "id": "hollow_whisper_event",
  "name": "Whispers from the Hollow",
  "type": "environmental",
  "trigger": {
    "conditions": [
      "hollow_corruption >= 4",
      "time_night",
      "player_outdoors"
    ],
    "probability": 0.3,
    "cooldown_hours": 4,
    "max_occurrences_per_session": 2
  },
  "priority": "important",
  "dm_instructions": "Narrate an unsettling moment where the player hears faint whispers. Don't reveal what the words mean yet. Build dread. If the player has a Hollow-Ward Amulet, mention it growing warm.",
  "effects": {
    "player": {"status_add": "unsettled", "duration_minutes": 30},
    "world": {"hollow_corruption_local": "+0.5"}
  },
  "sound_effect": "hollow_whisper",
  "escalation": {
    "if_corruption >= 7": {
      "dm_instructions_override": "The whispers are louder now. You can almost make out words. Your name. Someone is saying your name.",
      "effects": {"player": {"status_add": "hollow_touched"}}
    }
  }
}
```

**Key fields:**
- `trigger.conditions`: All conditions must be true for the event to be eligible. The simulation tick evaluates these.
- `trigger.probability`: Not all eligible events fire every tick. This creates unpredictability — the player might cross through a corrupted area without incident one time, then get hit the next.
- `trigger.cooldown_hours` and `max_occurrences_per_session`: Prevent event spam. The Hollow whispers shouldn't happen every 10 minutes.
- `priority`: Maps to the background process's proactive speech system. "critical" events can interrupt the player; "important" events wait for a pause; "routine" events only update the prompt.
- `dm_instructions`: Tells the DM *how* to present the event. This is the bridge between mechanical triggers and narrative delivery.
- `escalation`: Condition-dependent variants of the same event. Higher corruption → more intense version. The simulation tick checks escalation conditions when the event fires.

**Event types:**
- `environmental`: Weather, corruption effects, ambient phenomena
- `encounter`: Combat or social encounters triggered by conditions
- `narrative`: Story beats that fire at specific quest/state combinations
- `divine`: God-agent actions manifesting in the world
- `economic`: Market shifts, supply changes, price fluctuations

#### Factions / Organizations

Factions structure reputation, NPC allegiances, and political dynamics.

```json
{
  "id": "thornwatch",
  "name": "The Thornwatch",
  "type": "military_order",
  "description": "The primary military defense against the Hollow. Disciplined, well-equipped, stretched thin.",
  "values": ["order", "duty", "sacrifice", "suspicion of the unknown"],
  "territory": ["veldross", "border_regions", "watchtower_network"],
  "leader": "commander_voss",
  "reputation_tiers": {
    "hostile": {
      "threshold": -10,
      "effects": ["attacked on sight in Thornwatch territory", "bounty placed"]
    },
    "unfriendly": {
      "threshold": -5,
      "effects": ["refused service", "watched closely"]
    },
    "neutral": {
      "threshold": 0,
      "effects": ["basic services available", "guarded conversation"]
    },
    "friendly": {
      "threshold": 5,
      "effects": ["discounted supplies", "mission access", "insider information"]
    },
    "trusted": {
      "threshold": 15,
      "effects": ["restricted areas accessible", "Thornwatch gear available", "field commissions"]
    },
    "honored": {
      "threshold": 25,
      "effects": ["command authority in the field", "access to classified intelligence"]
    }
  },
  "relationships": {
    "city_council": "tense_alliance",
    "merchant_guild": "neutral",
    "the_hollow": "existential_enemy",
    "aethon_clergy": "respectful_cooperation"
  },
  "world_state": {
    "current_strength": "strained",
    "active_concerns": ["missing patrol", "border incursions increasing", "supply shortages"],
    "recent_events": []
  }
}
```

**Key fields:**
- `reputation_tiers`: Gameplay effects at each tier. The `update_npc_disposition` tool checks faction membership — when Maren's disposition changes, it may also shift Thornwatch reputation if she's faction-affiliated. The background process includes faction standing in the warm prompt layer so NPCs react appropriately.
- `relationships`: Inter-faction dynamics. If the player gains standing with a faction's enemy, they may lose standing with that faction. The simulation tick evaluates these relationships.
- `world_state`: Live faction state that the simulation updates. "Current strength: strained" might shift to "recovering" after the player completes quests that help the Thornwatch. This affects NPC behavior, available quests, and faction event triggers.

---

## Content Style Guide

### The Fundamental Constraint

Every word of authored content will be spoken aloud by the AI DM and heard through headphones. The player never reads a description — they listen to it mid-conversation, often while deciding what to do next. This changes everything about how content should be written.

**Write for the ear, not the eye.** Sentences that read beautifully on paper can sound awkward, confusing, or monotonous when spoken. Read every description aloud before committing it. If you stumble, the TTS will stumble harder. If you lose the thread, the player will too.

**Write for performance, not consumption.** The DM isn't a narrator reading from a book — the DM is a character performing the world for the player. Descriptions should give the DM material to *perform*: sensory hooks to emphasize, emotional beats to land, moments to pause for effect. Think stage directions, not prose paragraphs.

### Writing Location Descriptions

Location descriptions go in the `description` field for tier 1 entities. They're the raw material the DM uses when a player enters a location for the first time or asks "what do I see here?"

**Lead with what you hear, then what you feel, then what you see.** This is a voice game. Sound comes first.

Good: *"The forge hits you before you see it — a rhythmic clang of hammer on steel, a low roar of bellows, and the hiss of quenched metal. The heat rolls out through the open doorway. Inside, the space is cramped and soot-darkened, lit by the orange glow of the furnace."*

Weak: *"The blacksmith's forge is a small stone building with a chimney that emits dark smoke. Inside, there are several anvils and a large furnace. Tools hang on the walls."*

The first version gives the DM sensory hooks to perform — sounds, temperature, light quality. The second is a visual inventory that sounds like a real estate listing when spoken aloud.

**Keep descriptions to 2-4 sentences.** The DM delivers these mid-conversation. Too short and the location feels empty. Too long and the player's attention drifts before they can act. If a location has more to reveal, put the deeper details in `key_features` and `hidden_elements` — the DM reveals them when the player investigates.

**Include atmosphere, not just geometry.** Don't describe the layout of a room. Describe how it makes you feel to walk into it. A tavern isn't "a large room with tables and a bar." It's warm, noisy, smells of woodsmoke and ale, and there's a feeling of relief when you step in from the cold. The player's brain builds the geometry from the atmosphere.

**Write conditions as overlays, not replacements.** The `conditions` field in the location schema defines how the description changes based on time, weather, corruption, or quest state. Write these as modifications to the base atmosphere, not full rewrites.

Base: *"The market square is alive with sound — vendors calling prices, cart wheels on cobblestone, fragments of a dozen conversations in as many languages."*

Night condition: *"The market square is quiet now. A few lanterns sway in the harbor breeze. The vendors are gone, but you can still smell the day's spices. A lone guard's footsteps echo off the buildings."*

Corrupted condition: *"The market square is... wrong. The vendors are here, but their calls sound hollow, rehearsed. The colors feel muted even in description. A faint hum sits beneath everything, just below the threshold of hearing."*

### Writing NPC Content

NPC content spans several schema fields: `personality`, `speech_style`, `mannerisms`, `backstory_summary`, `knowledge`, and `secrets`. Together, they give the DM everything needed to portray a believable character through voice alone.

**Personality: 3-5 traits, with tension.** Flat personalities ("kind, brave, honest") produce flat characters. Include at least one trait that creates internal tension or contradiction — a brave warrior who's terrified of the dark, a generous merchant who's stingy about one specific thing, a cheerful innkeeper who goes quiet whenever someone mentions the Ashmark. The contradiction gives the DM material for interesting moments.

Good: *"Warm, gregarious, fiercely protective of her regulars — but noticeably evasive about her past before arriving in the Accord. Changes the subject with a joke whenever her history comes up."*

Weak: *"Friendly and helpful. Likes to talk. Runs a good tavern."*

**Speech style: write it so the DM can hear it.** Don't just say "formal" — describe the texture. Does the character use long sentences or short ones? Do they pause frequently? Do they ask rhetorical questions? Do they repeat themselves for emphasis? Do they trail off? The DM will use these cues to shape the TTS performance.

Good: *"Speaks in short, declarative sentences. Rarely uses more than five words where three will do. Pauses before answering questions, as if weighing each word. Never raises her voice — drops it instead when she's angry."*

Weak: *"Speaks formally."*

**Mannerisms: one or two memorable verbal tics.** These are the details players remember and that make an NPC recognizable across sessions. Keep them subtle enough that they don't become annoying when heard repeatedly. A character who *always* starts sentences with "Well, now..." or who clears their throat before giving bad news, or who uses a specific oath ("by Kaelen's hammer") when surprised. The DM weaves these into performance naturally.

**Backstory summary: motivation, not history.** The DM doesn't need to know where an NPC was born and raised. The DM needs to know what the NPC *wants*, what they're *afraid of*, and what they *won't talk about*. Write backstories as emotional context, not chronological biography.

Good: *"Lost her daughter to a Hollow incursion three years ago. Channels her grief into protecting Millhaven with ferocious determination. Refuses to discuss the loss — deflects with brusque practicality. Secretly terrified it could happen again."*

Weak: *"Born in the northern reaches 45 years ago. Moved to Millhaven as a young woman. Married a farmer named Aldric. Had a daughter named Senna who was killed during a Hollow raid."*

The first version tells the DM how to play the character in every conversation. The second is a wiki entry.

**Knowledge gating: structure by disposition and context.** The `knowledge` field defines what an NPC knows and under what conditions they'll share it. Write knowledge entries with clear gates:

```json
"knowledge": [
  {
    "topic": "the greyvale ruins",
    "disposition_required": "neutral",
    "info": "Mentions that lights have been seen at the ruins recently. Dismisses it as swamp gas or kids."
  },
  {
    "topic": "the greyvale ruins",
    "disposition_required": "friendly",
    "info": "Admits she's worried about the lights. Her cousin went to investigate and came back shaken, refusing to talk about what he saw."
  },
  {
    "topic": "the greyvale ruins",
    "disposition_required": "trusted",
    "info": "Reveals that her cousin described hearing voices in a language he didn't recognize — but somehow understood. He left Millhaven the next day and hasn't been heard from since."
  }
]
```

Each tier reveals more, creating a natural conversational progression that rewards relationship-building. The DM uses these gates automatically — it checks the player's disposition score against the requirement.

### Writing Quest Content

Quest content spans `description`, `stages`, `hints`, `completion_conditions`, and `branches`. The DM delivers all of this in conversation, never as text on a screen.

**Quest descriptions: the hook, not the briefing.** The `description` is what the quest-giver says (or what the DM narrates) to draw the player in. Write it as dialogue or narration, not as a quest log entry.

Good: *"She lowers her voice. 'The lights started again last month. At the old ruins north of town. Everyone pretends not to notice, but I've seen the look on the night watch's faces. Something is up there, and it's not scholars anymore.'"*

Weak: *"Investigate the Greyvale Ruins. Strange lights have been reported. Speak to the night watch for more information."*

The first gives the DM a scene to perform. The second is a UI tooltip.

**Stage objectives: action-oriented, spoken naturally.** Each quest stage has an `objective` that the DM may paraphrase or the companion may reference when giving guidance. Write them as things a person would actually say, not as bullet points.

Good: *"Find out what the night watch saw at the ruins."*
Weak: *"Gather information from 3 NPCs about the ruins (0/3)."*

**Hints: escalating, in-character.** The `hints` array in each stage feeds the guidance system. Write them as things the companion or DM would naturally say, in escalating specificity:

```json
"hints": [
  "Your companion mentions they overheard someone at the inn talking about the ruins.",
  "Your companion suggests asking the innkeeper — she seems to know everyone's business.",
  "Your companion says directly: 'The innkeeper's cousin was at those ruins. We should talk to her.'"
]
```

Level 1 is a nudge. Level 2 is a suggestion. Level 3 is explicit direction. All three sound like natural conversation, not system prompts.

**Branches: meaningful divergence.** If a quest branches, the branches should create genuinely different experiences — different NPCs, different locations, different information revealed. Don't branch into "you did the same quest but the DM described it slightly differently." A branch should change what the player knows, who trusts them, and what happens next.

### Writing Item Descriptions

Item descriptions appear when the DM narrates loot discovery and when the `show_item_card` tool fires on the client. They must work in both contexts: spoken aloud by the DM and displayed as brief text on an item card.

**One sentence of flavor, one sentence of function.** That's the target length.

Good: *"A dagger carved from Hollow-bone — the blade seems to drink the light around it. Deals additional void damage to corrupted creatures."*

Weak: *"This is a dagger made from the bone of a Hollow creature. It has been shaped into a blade approximately 8 inches long with a wrapped leather handle. When used against corrupted enemies, it deals bonus damage of the void type."*

**Audio-first sensory details.** How does the item *sound* when drawn? How does it *feel* in the hand? What *happens* in the air around it? These matter more than what it looks like.

Good: *"The blade hums when drawn — a low, unsettling tone that makes your teeth ache."*
Weak: *"The blade is dark gray with a slightly iridescent sheen."*

### Writing Event Content

Events drive the world simulation — they're the moments when something changes and the DM needs to react. The `dm_instructions` field is the most important part of an event schema: it tells the DM how to introduce the event to the player.

**Write instructions as direction, not script.** The DM is an improvisor. Give it a brief, a mood, and key details to include — not a paragraph to read verbatim.

Good:
```json
"dm_instructions": "A tremor runs through the ground — brief but unmistakable. NPCs react with alarm. If the player is indoors, dust falls from the ceiling. If outdoors, birds scatter. The tremor came from the north. This is the first sign of the Hollow incursion intensifying. Mood: sudden unease breaking through normality."
```

Weak:
```json
"dm_instructions": "Tell the player: 'You feel a sudden tremor beneath your feet. The ground shakes for a moment, then stops. People around you look worried. You notice that the tremor seemed to come from the north.'"
```

The first version gives the DM freedom to adapt to the player's situation while hitting the key beats. The second is a script that sounds stilted when the DM tries to deliver it naturally.

### General Principles

**The Hollow sounds wrong, never generic.** Any content describing the Hollow or its effects should emphasize audio wrongness — sounds that shouldn't exist, silences where there should be noise, familiar sounds distorted into something alien. The Hollow is not "evil" in a familiar fantasy way. It's incomprehensible. Content should make the player uneasy, not just threatened. Avoid clichés like "dark energy" or "sinister glow." Instead: "a sound like glass being sung backward" or "the birdsong stopped, and in the silence you hear something almost like breathing, but with the wrong rhythm."

**Gods have distinct voices, literally and figuratively.** Each god's content — whispers, quests, faction dialogue — should have a recognizable tone. Kaelen is direct, blunt, speaks of honor and courage. Syrath is indirect, speaks in questions and implications, never says anything straight. Veythar is scholarly, precise, fascinated by detail. When writing content associated with a god, inhabit their voice. The DM will pick up on the tonal cues and perform accordingly.

**Avoid visual-dependent descriptions.** Never describe something that can only be understood visually. "A complex series of runes carved in concentric circles" means nothing in audio. Instead: "The wall is covered in carvings — you can feel the grooves under your fingers, spiraling inward. Your companion says they're runes, old ones, and they hum faintly when you touch them." Engage touch, sound, smell, spatial awareness. Make the player's imagination do the rendering.

**Write for the DM, not the player.** Content is consumed by the AI DM, which then performs it for the player. The DM will paraphrase, adapt, and improvise around your content. Write material that gives the DM strong raw ingredients — vivid sensory hooks, clear emotional beats, concrete details — rather than polished final prose. The DM will make it its own.

---

## World Simulation Rules

The world changes over time through four simulation layers, each operating at a different frequency. The simulation runs on a real-time clock — one game-minute equals one real minute, 24/7, even when no players are online.

### The World Clock

Real-time, always running. The server maintains a canonical game clock synchronized to wall-clock time. This means:

- The world has a real circadian rhythm. Players who play in the evening experience nighttime gameplay; morning players get daytime.
- NPC schedules are real. The market opens at 6 AM and closes at 8 PM. If you log in at midnight, the stalls are shuttered.
- Quest deadlines are real. "Find the survivor within 7 days" means 7 real days.
- The async loop between sessions uses the same clock. Log off for 8 hours, 8 hours pass in-world.

### Simulation Layer 1: Time-Driven (every game-minute, deterministic)

These changes are purely a function of the current in-game time. Given the time, the state is computable with no randomness.

- **NPC schedules:** Cross-reference current time against each NPC's `schedule` field. Update `npc_state.current_location` accordingly.
- **Lighting and atmosphere:** Compute current time-of-day period (dawn/morning/afternoon/dusk/night). Apply corresponding `conditions` overlays to all locations.
- **Shop status:** Open/closed based on schedule.
- **Guard patrol positions:** Deterministic rotation through patrol routes.

Implementation: A lightweight cron-like process. No database reads beyond the clock — schedules and time conditions are loaded into memory at startup and refreshed when content changes.

### Simulation Layer 2: Simulation Tick (every 10 minutes)

Periodic computation that evolves slow-moving world variables. These involve database reads and writes.

**Hollow corruption drift:**
```
For each region:
  base_drift = region.corruption_baseline_rate  (e.g., +0.1/tick in border regions)
  god_suppression = sum(god_influence[region] for protective gods)
  god_amplification = hollow_pressure[region]
  event_modifier = sum(recent_event_effects on corruption)
  
  new_corruption = current_corruption + base_drift - god_suppression + god_amplification + event_modifier
  clamp(new_corruption, 0, 10)
```

**Faction influence adjustments:**
- Factions that recently gained or lost territory adjust their `world_state.current_strength`
- Inter-faction relationships shift based on recent events in the `world_events_log`

**NPC disposition decay:**
- Per-player dispositions drift toward the NPC's `default_disposition` over time
- Rate: ~1 point per in-game day for minor NPCs, slower for major NPCs
- This means relationships require maintenance — a merchant you befriended last week is slightly less warm if you haven't visited

**Economy tick:**
- Merchants restock from their `inventory_pool` (depleted items regenerate over time)
- Prices adjust based on `value_modifiers` conditions (regional demand, corruption levels, supply disruptions)
- Trade route events (caravan arrived, road blocked) shift availability

**Weather progression:**
- Weather state advances along probabilistic patterns per region and season
- Feeds into location `conditions` for atmosphere changes

**Event evaluation:**
- After all state updates, evaluate all `events` whose `trigger.conditions` now match
- For eligible events: roll against `probability`, check `cooldown` and `max_occurrences`
- Fire matching events → apply `effects` → cascade (see below)

### Simulation Layer 3: God-Agent Heartbeat (every 15-30 minutes)

Each of the 10 gods runs a periodic evaluation of the world through their domain of concern. Gods are the most interesting actors in the simulation — their decisions create the large-scale narrative dynamics that make the world feel alive.

**God heartbeat process:**

```
For each active god:
  1. Read current world state in their domain:
     - Region corruption/influence levels in their territory
     - Recent events in world_events_log relevant to their values
     - Player actions that align with or violate their principles
     - Other gods' recent actions that contest or complement theirs
  
  2. Evaluate using rules + occasional LLM judgment:
     SIMPLE CASES (rule-based, no LLM call):
     - Corruption rising in my territory → increase ward strength
     - My influence is unchallenged → maintain current state
     - A player completed a quest aligned with my values → small blessing
     
     COMPLEX CASES (LLM call with god personality):
     - Two gods contesting the same region → who yields?
     - A player prayed to me in an unusual situation → how do I respond?
     - A significant world event occurred → what's my reaction?
     - My domain is under serious threat → what dramatic action do I take?
  
  3. Emit world_effects:
     - Strengthen/weaken influence in specific regions
     - Send a sign or omen (event trigger for nearby players)
     - Bless or curse a location (modify location conditions)
     - Respond to a player's prayer (proactive event for that player)
     - Contest another god's action (creates tension events)
  
  4. Update god_agent_state:
     - Current focus and priorities
     - Recent decisions (for consistency)
     - Influence map changes
```

**God interaction with players:**

When a god's heartbeat produces an effect relevant to an active player session:
- The effect is published to the event bus
- The player's background process picks it up
- Classified by priority (divine intervention → critical, subtle omen → routine)
- Delivered through the proactive speech system or prompt update

**The Hollow as a simulation actor:**

The Hollow isn't a god but behaves like one mechanically. Its "heartbeat" probes for weak points:
- Regions with low divine protection
- Areas where traumatic events recently occurred (violence, death, fear)
- Places near the physical border of the Hollowmere
- Locations where players or NPCs have used Hollow-tainted artifacts

Corruption spreads like a slow infection. The protective gods push back. The balance between them is the world's macro-narrative tension.

**Contested regions:**

When multiple gods (or gods vs. the Hollow) influence the same area, the simulation tracks competing values:

```json
{
  "region": "ashfall",
  "influences": {
    "aethon": 6.2,
    "the_hollow": 3.8,
    "valdris": 1.5
  },
  "dominant": "aethon",
  "contested": true,
  "tension_level": "moderate"
}
```

Contested regions generate atmospheric events: flickering lights, contradictory omens, NPCs who feel uneasy without knowing why. The DM reads the tension level from the warm prompt layer and weaves it into narration.

### Simulation Layer 4: Event-Driven (immediate)

Events fire immediately when their trigger conditions are met — from player actions, quest completions, simulation tick results, or god-agent decisions. The cascade engine processes their ripple effects.

**The Cascade Engine:**

When a `world_effect` fires, the cascade engine evaluates its consequences up to 3 levels deep:

```
Level 0: Original effect
  Example: "bandit_leader_killed"

Level 1: Direct consequences
  Check all events/conditions that depend on "bandit_leader_killed"
  → "bandit_threat_cleared" triggers
  → "merchant_caravans_resume" triggers

Level 2: Secondary effects
  → "market_prices_drop_10_percent" (from caravans resuming)
  → "merchant_guild_disposition_toward_player +2"

Level 3: Tertiary effects (final level)
  → Any effects here apply but do NOT cascade further
  → Would-be level 4+ effects are logged for content review

Cap enforced. The entire cascade resolves atomically within a single tick.
```

**Cascade rules:**
- Maximum 3 levels of cascading from any single triggering event
- Each cascade level resolves completely before the next begins
- Effects at the same level are applied in deterministic order (alphabetical by effect ID for reproducibility)
- Contradictory effects at the same level: last-write-wins (logged for content review)
- The full cascade resolves before any player-facing notifications are emitted — players see the final state, not intermediate steps

**Cross-player cascades:**

In multiplayer, one player's actions can cascade into another player's experience:

```
Player A clears the bandits (Level 0)
  → Road is safe (Level 1)
    → Player B, currently on that road, gets a prompt update:
       "The tension lifts. The road ahead looks... clear." (Level 2)
```

The event bus routes cascade effects to all affected active sessions.

---

## Data Model

### Storage Architecture

**PostgreSQL:** Durable storage for all content and state. The source of truth.

**Redis:** Hot-path cache for data the DM agent and background process read frequently. Current player location, active combat state, session data, recent events. Written through from PostgreSQL mutations.

### Content Tables (authored, relatively static)

These hold the JSON entity schemas. Content changes only when authors update the world — not during normal gameplay.

| Table | Primary Key | Description |
|---|---|---|
| `locations` | `id` | Location definitions with conditions |
| `npcs` | `id` | NPC personalities, schedules, knowledge |
| `items` | `id` | Item properties, effects, economic data |
| `quests` | `id` | Quest state machines with stages and branches |
| `events` | `id` | Trigger conditions, effects, DM instructions |
| `factions` | `id` | Reputation tiers, relationships |
| `lore_entries` | `id` | Searchable lore passages (for `query_lore` tool) |
| `encounter_templates` | `id` | Combat encounter definitions, difficulty scaling |
| `inventory_pools` | `id` | Named item collections for merchant stocking |
| `voice_registry` | `character_id` | Voice ID mappings for the ventriloquism system |

Content is stored as JSONB in PostgreSQL, allowing flexible schema evolution without migrations. Indexed on `id`, `region`, `tags`, and commonly queried condition fields.

### State Tables (live, constantly changing)

These hold the current game state. Written by mutation tools (async), simulation ticks, and god-agent heartbeats.

| Table | Primary Key | Description |
|---|---|---|
| `players` | `player_id` | Character sheet, stats, current location, session status |
| `player_inventory` | `player_id, item_id` | Items held, equipped status, quantity |
| `player_quests` | `player_id, quest_id` | Active quests, current stage, progress flags |
| `player_reputation` | `player_id, faction_id` | Per-faction reputation scores |
| `npc_dispositions` | `npc_id, player_id` | Per-player disposition overrides |
| `npc_state` | `npc_id` | Current location (schedule-driven), revealed knowledge |
| `region_state` | `region_id` | Corruption levels, god influence values, weather, tension |
| `combat_instances` | `combat_id` | Active combats, turn order, participant HP/status |
| `world_events_log` | `event_id, timestamp` | Fired events history (cascade tracking, debugging) |
| `session_summaries` | `player_id, session_id` | Compressed recaps for cross-session continuity |
| `god_agent_state` | `god_id` | Current focus, recent decisions, influence map |
| `world_flags` | `flag_name` | Global boolean/numeric flags set by world_effects |

### Redis Cache Layer

The following data lives in Redis for sub-millisecond reads by the DM agent and background process:

| Key pattern | Data | TTL | Write-through from |
|---|---|---|---|
| `session:{player_id}` | Active session state (location, combat, userdata) | Session duration | Mutation tools |
| `location:{location_id}:state` | Computed location state (base + active conditions) | 60 seconds | Simulation tick |
| `combat:{combat_id}` | Active combat state | Combat duration | Mechanics tools |
| `region:{region_id}:state` | Current corruption, influence, weather | 60 seconds | Simulation tick |
| `npc:{npc_id}:location` | Current NPC location | 60 seconds | Schedule tick |
| `player:{player_id}:reputation` | Faction reputation scores | 5 minutes | Mutation tools |
| `events:recent:{region_id}` | Recently fired events | 1 hour | Event system |

Redis is not durable — if it crashes, all data is rebuilt from PostgreSQL on restart. The 60-second TTLs mean the background process always reads fresh-enough data for prompt building.

### Query Patterns

**Background process rebuilding the warm prompt layer:**
```
1. Read player's current location from Redis: session:{player_id}
2. Read computed location state from Redis: location:{location_id}:state
3. Read NPC locations for this location: SCAN npc:*:location WHERE value = location_id
4. For each NPC present: read disposition from Redis or DB
5. Read region state: region:{region_id}:state
6. Read active quests: SELECT from player_quests WHERE player_id = X AND status = 'active'
7. Read god agent states for relevant gods
8. Assemble warm layer prompt string
```

**DM tool `query_npc(npc_id)`:**
```
1. Read NPC definition from content DB (or Redis cache): npcs WHERE id = npc_id
2. Read per-player disposition: npc_dispositions WHERE npc_id = X AND player_id = Y
3. Compute available knowledge based on disposition tier
4. Return structured NPC data to the LLM
```

**Simulation tick:**
```
1. Read all region_state rows
2. Read all god_agent_state rows
3. Compute new corruption/influence values per region
4. Write updated region_state (PostgreSQL + Redis)
5. Evaluate event triggers against new state
6. Fire eligible events → cascade engine
7. Write world_events_log entries
8. Publish changes to event bus
```

---

## MVP Content Scope

The MVP supports the Greyvale arc — a 10-15 hour story experience. Content volume:

| Entity | Tier 1 (authored) | Tier 2 (generated) | Total |
|---|---|---|---|
| Locations | 5-6 | 10-15 | ~20 |
| NPCs | 5-6 | 15-20 | ~25 |
| Items | 8-10 | 25-30 | ~40 |
| Quests | 4-5 | — | ~5 |
| Events | 10-12 | 5-8 | ~18 |
| Factions | 3-4 | — | ~4 |

**Tier 1 authored content** (~35-40 entities): Human-reviewed, carefully crafted. These are the entities that carry the story — the key locations, major NPCs, critical items, and main quest line.

**Tier 2 generated content** (~55-75 entities): AI-generated from templates and tags. Minor locations, ambient NPCs, common items, environmental events. Generated in batch before launch, reviewed for consistency, regenerated on demand if a player encounters an undefined area.

**On-demand generation:** If a player goes somewhere undefined, the system generates a tier 2 location from the region's template palette, persists it, and the DM narrates it naturally. The player never knows it was just created. This means the MVP can launch with authored content for the critical path and generate everything else as needed.

**Content generation pipeline:**
1. Human authors define tier 1 entities (the story skeleton)
2. AI generates tier 2 entities using tier 1 content as examples and the Aethos lore as context
3. Human reviews generated content for consistency and tone
4. Content is loaded into the content DB as JSON
5. During gameplay, the DM agent and simulation read from the content DB
6. On-demand generation fills gaps as players explore beyond authored boundaries

---

## Cross-References

- **Technical Architecture — DM Agent Architecture:** The DM agent's tools read from content tables and write to state tables. The background process reads state to build the warm prompt layer.
- **Technical Architecture — Orchestration Design:** Session lifecycle, state persistence, and the event bus connect directly to the data model.
- **Game Design Document:** Quest structures, combat mechanics, and the guidance system reference entity schemas defined here.
- **Aethos Lore Document:** The narrative foundation that content authors and AI generators use as context for creating entities.
- **Cost Model:** Content volume affects storage costs (minimal) and LLM token usage (the warm prompt layer size depends on how much entity data is injected per turn).
- **MVP Spec:** The Greyvale arc content scope maps to the MVP content table above.

---

*Entity schemas and simulation rules defined February 2026. Schemas are intentionally flexible — JSONB storage allows field additions without migrations. Simulation parameters (tick rates, cascade depth, corruption drift rates) will be tuned through playtesting.*
