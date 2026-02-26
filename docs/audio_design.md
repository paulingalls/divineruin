# Divine Ruin — Audio Design Document

## About This Document

This is the audio design bible for Divine Ruin. In a voice-first game with no visuals, audio isn't a layer on top of the experience — it *is* the experience. Every moment the player spends in this game, their entire understanding of where they are, what's happening, and how they should feel comes from what they hear. This document governs every audio decision from environmental ambience to god voices to the sound a dice roll makes when it hits the table.

This document is designed to serve two purposes: (1) as a creative direction guide for all audio work, and (2) as a **prompt-ready reference for AI audio generation** — each asset category includes descriptions detailed enough to feed directly into generative audio tools.

**Related documents:**
- *Game Design Document* — gameplay systems that audio must support
- *World Data & Simulation* — content style guide (audio-first writing principles), location schemas with `ambient_audio` fields
- *Technical Architecture* — voice pipeline (LiveKit, STT, TTS), audio mixing, client playback architecture
- *Aethos Lore* — world, cultures, gods, and the Hollow (the emotional and narrative foundation for audio direction)
- *MVP Spec* — which audio assets are needed for launch

---

## Audio Philosophy

### The First Principle: Sound Is Sight

The player has no screen to look at. Sound replaces vision entirely. When they enter a tavern, they don't see warm light and wooden beams — they hear the crackle of a fire, the murmur of conversation, the creak of a chair, the clink of ceramic. When they step outside, they don't see a night sky — they hear crickets, a distant dog barking, wind through thatch. When danger approaches, they don't see a red indicator — they hear the ambient soundscape shift, the music darken, the companion's voice tighten.

This means audio must do the work of an entire visual engine:
- **Establish place.** Every location has a unique sonic identity the player learns to recognize.
- **Communicate state.** Time of day, weather, corruption level, safety/danger — all conveyed through audio shifts.
- **Signal change.** When something happens in the world, the audio changes first. The player hears the shift before the DM describes it.
- **Create emotion.** Fear, wonder, warmth, tension, grief — all built through the interaction of voice, ambience, music, and silence.

### The Second Principle: Silence Is a Tool

In a game made of sound, silence is the most powerful effect. A world that's always noisy teaches the player to tune things out. Strategic silence — a sudden drop in ambient sound, a companion who stops talking, music that cuts to nothing — is how the game creates its most intense moments. The Hollow's most terrifying quality isn't that it makes terrible sounds. It's that it makes *wrong* sounds — and sometimes no sound at all where sound should be.

### The Third Principle: Audio Must Be Layered, Not Stacked

The player hears multiple audio sources simultaneously: DM voice, companion voice, ambient environment, sound effects, music, UI sounds. These cannot compete. A clear mixing hierarchy ensures the player always hears what matters most, without the mix becoming muddy or overwhelming. Voice always wins. Ambience supports but never overwhelms. Music breathes underneath everything. Effects punctuate.

### The Fourth Principle: The Ear Learns

Players will develop audio literacy over time. A sound they don't consciously notice in session one becomes a meaningful signal by session five. The creak of a specific door. The hum of Veil energy. The distant horn that means a patrol is changing. Audio design should reward attentive listeners with environmental storytelling that builds over sessions.

### The Fifth Principle: Audio Must Be Generatable

Every audio asset in the game will be produced through AI generation tools — not recorded in a studio. This means audio design must account for the strengths and limitations of generative audio: strong at ambience, textures, and tonal atmospheres; improving rapidly at music; variable at precise sound effects. Descriptions must be specific enough to produce consistent results across generation sessions.

---

## The Audio Stack — What the Player Hears

At any given moment, the player's audio experience is a mix of up to seven simultaneous layers. These layers have a strict priority hierarchy — higher-priority layers duck or mute lower-priority ones.

### Layer Hierarchy (Highest to Lowest Priority)

| Priority | Layer | Description | Source |
|---|---|---|---|
| 1 | **DM Voice** | The narrator, NPC ventriloquism, environmental description | Real-time TTS via LiveKit |
| 2 | **Companion Voice** | The companion's dialogue, reactions, idle chatter | Real-time TTS via LiveKit (different `voice_id`) |
| 3 | **Critical Sound Effects** | Combat impacts, danger alerts, Hollow intrusions, dice rolls | Client-side playback triggered by `play_sound` tool |
| 4 | **Music** | Adaptive score, stingers, tension cues | Client-side playback, crossfaded by state |
| 5 | **Ambient Sound Effects** | Footsteps, door creaks, item interactions, weather | Client-side playback triggered by tools or state |
| 6 | **Environmental Ambience** | Location-specific soundscape (base layer) | Client-side looping audio, switched on location change |
| 7 | **UI Sounds** | Notification chimes, HUD interactions, async activity alerts | Client-side, minimal and unobtrusive |

### Mixing Rules

**Voice is sacred.** When the DM or companion speaks, ambient audio ducks by 40-60%. Music ducks by 50-70%. Non-critical sound effects are deferred until the next speech gap. The player must always be able to hear and understand dialogue clearly.

**Effects punctuate, never compete.** Sound effects play in the gaps between speech or are brief enough to overlay without interfering. A sword clash during combat narration is timed to land between the DM's words, not over them. The orchestration layer handles this timing — the `play_sound` tool fires with a `timing` parameter: `immediate` (overrides everything, reserved for danger), `next_gap` (waits for a speech pause), or `background` (plays quietly under speech).

**Music breathes.** Music is the lowest-energy audio layer. It sets mood without demanding attention. It should be possible to play the game with music at 50% volume and miss nothing. Music swells during dramatic moments when speech pauses, and recedes when dialogue resumes.

**Ambience is continuous.** Environmental ambience loops without noticeable seams. It's the foundation the other layers sit on top of. When the player moves locations, the old ambience crossfades to the new one over 2-3 seconds — never a hard cut.

**The Hollow breaks the rules.** Hollow-corrupted audio intentionally violates the mixing hierarchy. Sounds that shouldn't be at priority 3 force themselves there. The ambient layer produces sounds that don't belong. Music distorts. The mixing rules exist specifically so that when the Hollow breaks them, the player feels it.

---

## Environmental Soundscapes

Every location in the game has a base soundscape — a looping audio bed that establishes the identity of the place. This is the foundation of the player's spatial understanding. Over time, players learn to recognize locations by sound alone: "That's the market. That's the forest. That's the ruins."

### Soundscape Structure

Each location's soundscape is built from three sub-layers:

**1. Bed (continuous).** A low-energy, looping foundation that establishes the acoustic space. Indoors: room tone, reverb characteristics, the "size" of the space. Outdoors: the base environmental texture — wind, water, open air, enclosed canopy. This layer is subtle and almost subliminal.

**2. Texture (semi-random).** Intermittent sounds that give the environment life. A bird call. A distant hammer. A creak in the floorboards. A child's laugh from another street. These fire at randomized intervals (every 5-30 seconds) with randomized selection from a pool. They prevent the soundscape from feeling like a static loop.

**3. Condition overlay (state-driven).** Modifications based on current conditions: time of day, weather, corruption level, quest state. Rain adds a rain layer. Night replaces daytime textures (birdsong → crickets, market bustle → quiet). Corruption adds a subsonic hum and removes natural sounds. These overlay on the base soundscape, not replace it — the bed stays, the textures shift.

### Soundscape Specifications by Location Type

#### Settlements and Towns

**Bed:** Warm room tone or open-air hum. The "acoustic signature" of civilization — reverb that suggests buildings nearby, hard surfaces, enclosed spaces. Slightly different for each settlement based on size and material (stone city vs. wooden village vs. tent camp).

**Daytime textures:** Voices in the distance (indistinct murmur, not intelligible words), footsteps, cart wheels on stone or dirt, merchant calls, hammering, livestock, children, doors opening and closing, the clink of trade.

**Nighttime textures:** Crickets or equivalent insects, distant music from a tavern, a guard's footsteps on patrol, an occasional dog bark, wind through streets, the creak of shop signs swinging.

**Rain overlay:** Steady rain on various surfaces (stone, thatch, wood). Reduces the distance at which other textures are audible — the world closes in during rain. Occasional thunder for storms, distant and rolling.

**Corruption overlay:** The warm civilization sounds thin out. Fewer voices. The hum of Veil disturbance underneath — not a musical note, more like tinnitus with texture. One or two "wrong" textures enter the pool — a sound that could be a voice but isn't, a metallic resonance with no source.

---

**AI Generation Prompt — Town, Daytime:**
> Ambient soundscape for a small medieval market town during a busy afternoon. Warm and alive. Foundation of open-air room tone with slight reverb suggesting stone and wood buildings. Layered with: distant indistinct crowd murmur, occasional merchant calls, wooden cart wheels on cobblestone, a blacksmith's hammer in the middle distance, chickens clucking, children playing far away, a wooden door opening and closing. Mood: safe, bustling, lived-in. No music. No modern sounds. 60-second seamless loop.

**AI Generation Prompt — Town, Night:**
> Ambient soundscape for a small medieval town at night. Quiet and still but not empty. Foundation of nighttime open-air room tone — cooler, more reverberant than daytime. Layered with: crickets and night insects, distant muffled tavern music (lute and voices, very faint), a guard's slow footsteps on stone (passing through, not looping), an occasional dog bark in the distance, wind through narrow streets, the creak and tap of a hanging shop sign. Mood: peaceful but watchful. 60-second seamless loop.

**AI Generation Prompt — Town, Corrupted:**
> Ambient soundscape for a medieval town under subtle supernatural corruption. The sounds of normal town life are present but thinned — fewer voices, less energy, as if people have withdrawn indoors. Foundation includes a low, barely perceptible subsonic hum with an uneasy tonal quality, like tinnitus mixed with a distant vibration. Occasional textures that feel wrong: a sound that could be a whispered word but resolves into wind, a faint metallic resonance with no identifiable source, a bird call that trails off at the wrong pitch. Mood: familiar but uneasy, something is off but you can't name it. 60-second seamless loop.

---

#### Wilderness and Roads

**Bed:** The acoustic signature of open space — wind, the ambient rustle of vegetation. Forests feel enclosed (close reverb, dampened). Plains feel wide (distant reverb, open). Mountains feel vast (echoes, thin air quality). The bed immediately tells the player whether they're in an open or enclosed natural space.

**Daytime textures:** Birdsong (species vary by biome), rustling leaves or grass, running water if near a stream, insect hum, snapping twigs, animal calls in the distance.

**Nighttime textures:** Owl calls, nocturnal insects, the rustle of small creatures, wind through trees (more prominent at night), the occasional crack of a branch that makes you wonder what's out there.

**Rain/storm overlay:** Rain hitting foliage is different from rain hitting stone. Forest rain is muffled and pattering. Open-field rain is steady and enveloping. Thunder rolls take longer across open terrain.

**Corruption overlay:** Nature goes quiet. Birds stop singing. The insect hum takes on an unnatural buzz. Wind carries a sound that shouldn't travel on wind — a low, sustained note like a bowed glass rim. The trees creak, but not from wind.

---

**AI Generation Prompt — Temperate Forest, Daytime:**
> Ambient soundscape for a temperate deciduous forest on a mild day. Enclosed canopy feel — close reverb, sound slightly dampened by vegetation. Foundation of gentle wind through leaves, creating a continuous rustling texture. Layered with: varied birdsong (realistic woodland species, calls from different distances and directions), a small stream bubbling nearby, occasional distant woodpecker, insect hum at the edge of perception, the rare crack of a branch or rustle of underbrush from an unseen animal. Mood: peaceful, alive, slightly mysterious. 60-second seamless loop.

**AI Generation Prompt — Wilderness, Corrupted Night:**
> Ambient soundscape for a forest at night where something supernatural has gone wrong. Unnatural quiet — the normal night creatures have gone silent. Foundation of wind through bare or dead branches, creaking wood with an irregular rhythm that doesn't match the wind. A low, sustained tonal hum like a bowed glass rim or distant singing metal, just below comfortable hearing — subsonic pressure that creates unease. Occasional textures: a branch crack from no direction, a sound like breathing that resolves into wind, a single bird call that cuts off abruptly mid-note. Absolute silence for 3-5 seconds at random intervals — then the ambient sounds resume as if nothing happened. Mood: dread, wrongness, the absence of what should be there. 60-second seamless loop.

---

#### Interiors — Taverns, Shops, Temples

**Tavern bed:** Warm, enclosed, slightly boomy low-end. The sound of a room full of wooden furniture and bodies. Fire crackle from a central hearth.

**Tavern textures:** Murmured conversations (multiple overlapping, indistinct), occasional laughter, ceramic and wooden cups clinking, a chair scraping, footsteps on wooden floorboards, a door opening with a rush of outside air, distant music (lute, voice) that comes and goes.

**Shop bed:** Quieter, smaller acoustic space. A single-room feel. The specific sound depends on the shop type: a blacksmith has a hot, metallic ring to the air; an alchemist has the bubble and hiss of liquids; a general merchant has the rustle of cloth and creak of shelving.

**Temple bed:** Reverent acoustic — high ceiling reverb, stone surfaces, the quality of a space designed to make silence feel intentional. A subtle, low organ-like resonance from the architecture itself. The god associated with the temple inflects the sound: Kaelen's temples have an iron solidity; Syrath's have whispered undertones; Veythar's have the faint hum of arcane energy.

---

**AI Generation Prompt — Tavern Interior:**
> Interior ambience of a busy medieval tavern. Warm, enclosed acoustic space with wooden surfaces and a low ceiling. Prominent fireplace crackle from a central hearth. Multiple overlapping indistinct conversations — a warm murmur of voices, no intelligible words. Occasional: a burst of laughter, ceramic mugs clinking, a wooden chair scraping on the floor, heavy footsteps crossing wooden floorboards, a door opening briefly letting in wind before closing again. Very faint background lute music, simple melody, sometimes there and sometimes not. Mood: safe, convivial, the kind of place you want to sit down and stay a while. 60-second seamless loop.

**AI Generation Prompt — Veythar's Temple:**
> Interior ambience of a large stone temple dedicated to a god of knowledge and magic. High-ceilinged, reverberant acoustic space — every small sound echoes. Stone surfaces, cool air. Foundation of a barely audible low resonance, as if the building itself hums with contained energy — not musical, more like the tonal vibration of a tuning fork felt through the floor. Occasional: a page turning in the distance, soft footsteps on stone, a faint crystalline chime that seems to come from the walls, the whisper of robes. No voices, no conversation. Mood: reverent, intellectual, quietly powerful — a place where silence is a form of respect. 60-second seamless loop.

---

#### Dungeons and Ruins

**Bed:** The acoustic signature of underground or decaying architecture. Stone reverb, dripping water, the ambient pressure of being enclosed. Ruins have more air movement (open to sky in places); true dungeons feel sealed and tight.

**Textures:** Water drips (randomized timing, varying resonance depending on what it drips onto), settling stone, distant rumbles, the scuttle of unseen creatures, wind through cracks, the groan of stressed architecture. Deeper in the dungeon, textures become sparser — the silence itself becomes the texture.

**Corruption overlay:** The dripping water takes on a rhythmic quality that shouldn't be there — not random anymore, almost deliberate. A subsonic pressure builds, the feeling of something large breathing behind the walls. Sounds occur behind the player (spatial audio) with no source. Stone settling sounds become more frequent and directional, as if the architecture is responding to the player's presence.

---

**AI Generation Prompt — Ancient Ruins, Upper Level:**
> Ambient soundscape for the upper level of ancient stone ruins, partially exposed to the sky. Reverberant stone acoustic space, damp, with occasional wind from above. Foundation of intermittent water drips onto stone and standing pools, each drip with slightly different resonance. Layered with: faint wind through cracks and openings, the subtle groan of settling stonework, the distant flutter of a bat or bird in the rafters, pebbles shifting underfoot. The space feels old and undisturbed. Mood: cautious exploration, ancient mystery, the weight of forgotten time. 60-second seamless loop.

**AI Generation Prompt — Hollow Breach (Deep Corruption):**
> Ambient soundscape for a location where reality has been breached by a supernatural force of corruption and entropy. The normal rules of sound have broken down. Foundation of oppressive subsonic pressure — a deep, slow oscillation felt more than heard, like standing inside a massive breathing lung. Layered with: water drips that have fallen into an unnatural rhythm (drip... drip... drip-drip... silence... drip), stone sounds that respond to the listener as if the architecture is aware, a faint high-frequency tone that drifts in pitch like distant tinnitus, and periodic moments of absolute dead silence — no reverb, no room tone, nothing — lasting 2-3 seconds before the ambient sounds resume with a slight shift in character. Occasional: a sound that resembles a human voice speaking a single syllable, backwards, very far away. Mood: wrong. Not scary in a jump-scare way — wrong in a way that makes your skin crawl because the rules you unconsciously trust about how the world sounds have been violated. 60-second seamless loop.

---

## The Sound of the Hollow

The Hollow is Divine Ruin's signature audio design challenge and its most important sonic element. The Hollow is the corruption at the heart of the world — a force of entropy and dissolution that erodes reality. Visually, it would be darkness and decay. But we have no visuals. The Hollow must be communicated *entirely* through audio, and it must be the most memorable, distinctive, and unsettling sound design in the game.

### Design Rules for Hollow Audio

**1. The Hollow sounds wrong, never generic.** Not "scary monster sounds." Not horror movie stingers. The Hollow's audio identity is *wrongness* — sounds that violate the player's unconscious expectations about how reality works. A bird call that plays backwards. Water dripping upward (the resonance inverts). Wind that carries a voice that isn't there. Silence where there should be echo. These are subtle at first and escalate as corruption deepens.

**2. The Hollow is subtractive first, additive second.** The first sign of the Hollow isn't a new sound — it's the absence of an expected sound. Birds stop singing. The ambient hum drops out. The companion's voice gets slightly muffled, as if heard through water. The player notices something is *missing* before they hear something wrong. Only after the subtractive layer establishes unease do the additive elements arrive: the subsonic pressure, the impossible sounds, the whispers.

**3. The Hollow escalates through stages.** The audio shifts progressively through corruption levels:

**Stage 1 — Thinning.** Natural sounds become sparse. Longer silences between ambient textures. The soundscape feels emptier than it should. Most players won't consciously notice — they'll just feel slightly uneasy.

**Stage 2 — Displacement.** Sounds begin appearing at wrong distances or positions. A sound that should be far away is suddenly close. A sound from the left has no spatial source. Echo behavior changes — a clap doesn't echo when it should, or echoes when it shouldn't. The acoustic space becomes unreliable.

**Stage 3 — Intrusion.** New sounds enter that don't belong: the subsonic hum, metallic resonances, tonal drifts. These aren't aggressive — they're ambient, pervasive, like background radiation. The player can't point to a single sound and say "that's wrong," but the overall texture has shifted.

**Stage 4 — Violation.** The mixing rules break. Sounds at wrong priority levels. Ambient textures that override voice briefly. Music that distorts. A sound that seems to come from inside the player's head rather than the game world. The companion says "Did you hear that?" — and the player isn't sure if the companion is scripted to say that or if the companion *actually heard something.*

**Stage 5 — Presence.** The Hollow has a voice. Not words — a presence in the audio field that feels aware. A sustained sound that responds to the player's actions (volume shifts when they speak, pitch changes when they move). The subsonic pressure becomes rhythmic, like breathing. The player feels watched through their ears.

**4. The Hollow is personal.** In the full MMO, different players in the same corrupted area might hear different Hollow manifestations based on their divine patronage, psychological profile (play history), and corruption exposure. One player hears their dead companion's voice. Another hears a lullaby from their starting culture. The Hollow uses the player's own audio history against them. (MVP: standardized Hollow audio. Post-MVP: personalized manifestations.)

### Hollow Sound Asset Categories

**Subsonic drones.** Low-frequency pressure beds (30-60 Hz) that create physical unease. Slowly oscillating, sometimes pulsing at irregular intervals. Not melodic — tonal but unstable, drifting in pitch like a detuned instrument.

**Reversed naturals.** Real-world sounds (birdsong, water, wind, footsteps) processed in reverse with slight pitch shift. Uncanny because the brain recognizes the source but the temporal envelope is wrong.

**Tonal voids.** Moments where specific frequency bands are suddenly absent from the mix — as if someone cut a hole in the sound. The brain perceives this as the acoustic equivalent of a shadow.

**False sources.** Sounds with no spatial origin or with contradictory spatial cues. A whisper that comes from all directions equally. A footstep that's both close and far away simultaneously.

**Corrupted voices.** Human-like vocalizations that aren't speech: a single syllable repeated at irregular intervals, a breath that extends too long, a laugh that decays into static, a word spoken backwards at half speed.

---

**AI Generation Prompt — Hollow Subsonic Drone:**
> A deep, unsettling ambient drone for a supernatural corruption force. Frequency range centered around 40-60 Hz, felt as physical pressure in the chest more than heard as a note. Slowly oscillating in volume with an irregular rhythm — not mechanical, more like something breathing at an inhuman rate. The pitch drifts very slightly, never settling, creating a constant subliminal tension. Occasionally, a higher harmonic (around 200 Hz) rises briefly and fades, like a distant moan. No melody, no rhythm, no musical structure — this is a presence, not music. Duration: 60 seconds, seamless loop.

**AI Generation Prompt — Hollow Reversed Naturals:**
> A collection of everyday natural sounds processed to sound deeply uncanny. Each clip takes a familiar sound — birdsong, running water, wind through leaves, a human footstep on gravel — and reverses the temporal envelope while keeping some recognizable quality. The reversed birdsong should still feel like it could be a bird, but the attack and decay are wrong. The water sounds like it's flowing upward. The footstep arrives before the impact. Each clip is 3-8 seconds. The mood is not aggressive or loud — it's quiet and deeply wrong, the kind of sound that makes you turn your head even though you know nothing is there. Generate 10 variations.

**AI Generation Prompt — Hollow False Source Whisper:**
> A human-like whisper that seems to come from no specific direction — diffuse, omnidirectional, as if the air itself is speaking. The whisper contains what sounds like a single word or syllable repeated 2-3 times, but the word is unrecognizable — close to language but not quite. The voice quality is androgynous, breathy, with no emotional affect — neutral in a way that feels deliberate and unsettling. The whisper should not sound like a recording of a person — it should sound like something mimicking a human whisper without understanding what whispering is for. Duration: 5-8 seconds. Generate 5 variations.

---

## Voice Design

Voice is the primary medium of the game. The DM, companion, and NPCs communicate everything through spoken language. Voice design governs how each character type sounds, how emotion is conveyed through TTS, and how the player distinguishes between speakers in an audio-only environment.

### The DM Voice

The DM is the world's voice — narrator, environment, and ventriloquist for NPCs. The DM voice must be:

**Authoritative but warm.** The player trusts this voice to tell them the truth about the world. It's confident without being cold, descriptive without being flowery, and present without being overbearing.

**Flexible in register.** The DM shifts tone constantly: calm narration for exploration, urgent intensity for combat, soft reverence for sacred moments, dark gravity for Hollow encounters. The voice doesn't change — the delivery does.

**Distinct from all NPCs.** When the DM ventriloquizes an NPC, the shift must be audible. The DM's narrative voice is the baseline; NPC voices deviate from it through accent, pace, pitch adjustment, and delivery style. The player must always know whether they're hearing the DM describe something or an NPC speak.

**TTS direction for DM voice:**
- Base `voice_id`: a warm, mid-range voice with natural cadence and clear enunciation
- Default emotion: `neutral-warm` — engaged but not performative
- Speech rate: moderate, with natural pauses between sentences
- The DM voice should feel like a skilled narrator reading aloud — human in rhythm, unhurried, with subtle emphasis on important words

### Companion Voices

The companion is the player's constant audio partner — the voice they hear most often. Each companion archetype has a distinct voice that reflects their personality.

**Kael (Steadfast Partner):**
- Voice: warm baritone, slightly rough, grounded
- Pace: measured, deliberate — thinks before speaking
- Emotional range: steady calm → dry humor → protective urgency → quiet grief
- TTS direction: `voice_id` should sound like a reliable older brother — not gruff, but solid. Pauses between thoughts. When stressed, the voice gets quieter and more focused, not louder

**Lira (Skeptical Scholar):**
- Voice: clear mezzo, precise articulation, a hint of impatience
- Pace: quick when excited by an idea, clipped when annoyed, deliberately slow when explaining something she finds obvious
- Emotional range: intellectual curiosity → sarcastic frustration → reluctant warmth → stunned wonder
- TTS direction: `voice_id` should sound educated and sharp — someone who listens carefully and speaks pointedly. When she's genuinely impressed or moved, the precision drops and she sounds almost surprised at her own emotion

**Tam (Reckless Heart):**
- Voice: bright, energetic, slightly higher register, youthful
- Pace: fast and enthusiastic in safe moments, breathless in action, uncharacteristically slow and quiet in vulnerable moments
- Emotional range: infectious enthusiasm → reckless bravado → sudden tenderness → raw guilt
- TTS direction: `voice_id` should sound like someone who talks with their hands — expressive, forward-leaning, words tumbling out. The contrast between their normal energy and their rare quiet moments is the emotional core

**Sable (Quiet Watcher):**
- Voice: Sable doesn't speak. The DM narrates Sable's behavior and body language in a softer, more intimate register than normal narration — as if describing something private
- Sound identity: Instead of voice, Sable has a sound palette. Soft chirps, low trills, a specific purring hum when content, a sharp bark-like call when alarmed, a keening whine when distressed. These sounds are Sable's "voice" and the player learns to read them
- TTS direction: no dedicated `voice_id` — the DM's voice shifts to a gentler, more observational tone when narrating Sable's actions

### NPC Voice Differentiation

The DM ventriloquizes all NPCs. In an audio-only game, the player must instantly know which character is speaking. Voice differentiation is achieved through:

**Pace.** An old village elder speaks slowly, with long pauses. A nervous merchant speaks quickly, words running together. A military commander speaks in short, clipped phrases.

**Emotional default.** Each NPC has a resting emotional state that colors all their speech. The paranoid guard is always slightly tense. The warm innkeeper is always slightly amused. The grieving mother is always slightly distant.

**Verbal tics.** One or two memorable speech patterns per major NPC: a phrase they repeat, a way they start sentences, a habit of trailing off, a tendency to answer questions with questions. These should be subtle enough not to annoy but consistent enough to identify.

**TTS emotion tags.** The orchestration layer wraps NPC dialogue in emotion tags that the TTS system uses to inflect delivery: `[GUILDMASTER_TORIN, weary-authoritative]: "The scouts haven't returned."` See *Technical Architecture — Orchestration Design* for the `[CHARACTER, emotion]: "dialogue"` format.

### God Voices

Each god has a distinct vocal quality that transcends normal NPC voice design. When a god speaks, the audio experience shifts — the player should feel that they're hearing something larger than a person.

**Kaelen, the Ironhand (War, Duty):**
- Voice quality: deep, resonant, with a slight echo as if spoken in a vast stone hall
- Delivery: direct, declarative, no wasted words — commands, not conversations
- Audio treatment: subtle low-frequency reinforcement, slight reverb suggesting immense space
- TTS direction: deep male voice, slow and deliberate, with the gravity of someone who has never needed to raise their voice to be obeyed

**Syrath, the Whisper (Secrets, Night):**
- Voice quality: close and intimate, as if whispering directly into the player's ear, androgynous
- Delivery: questions more than statements, pauses that feel deliberately uncomfortable, sentences that trail off as if deciding how much to reveal
- Audio treatment: very close microphone proximity feel, slight stereo shifting (the voice moves subtly between ears), no reverb — unnervingly present
- TTS direction: soft, whispery, gender-ambiguous, with the cadence of someone who knows more than they're saying and enjoys the asymmetry

**Veythar, the Archivist (Knowledge, Magic):**
- Voice quality: precise, measured, with a crystalline clarity — every word chosen carefully
- Delivery: scholarly patience, the cadence of someone who has eternity to explain things, occasional warmth when a mortal asks a truly interesting question
- Audio treatment: a faint harmonic shimmer underneath the voice, as if the words themselves vibrate at a frequency slightly beyond normal speech
- TTS direction: clear, articulate, gender-neutral tending slightly warm, with the unhurried pace of someone who finds ignorance merely an opportunity

**Aelora, the Hearthkeeper (Civilization, Craft):**
- Voice quality: warm, encompassing, maternal without being soft — the strength of someone who builds
- Delivery: practical and grounding, speaks in specifics not abstractions, encouragement that feels earned
- Audio treatment: warm low-mid frequencies, the vocal equivalent of firelight — comfortable but substantial
- TTS direction: warm female voice, confident and direct, with the cadence of someone who cares about outcomes and wants to help you achieve them

**Mortaen, the Still (Death, Passage):**
- Voice quality: quiet, absolutely calm, the voice of someone standing at the end of all things and finding it peaceful
- Delivery: slow, inevitable, compassionate without pity — the voice you hear when you die and it's not unkind
- Audio treatment: a slight time-stretch quality, as if the words exist outside normal temporal flow, subtle echo that doesn't match any physical space
- TTS direction: low, quiet, gender-neutral, with a pace that feels like it comes from outside of time — not dramatic, not frightening, simply final

*(Note: additional god voices for Tharion, Valdris, Yrenna, Ashara, and the Void-touched should follow similar patterns, each reflecting their domain. These are post-MVP.)*

---

## Combat Audio

Combat in a voice-first game relies entirely on audio to communicate spatial awareness, timing, threat level, and the physical impact of violence. Without visuals, every sword swing, spell effect, and enemy movement must be heard clearly and instantly understood.

### Combat Audio Principles

**Clarity over spectacle.** A combat audio mix that sounds "epic" but confuses the player about what's happening has failed. Every sound must communicate specific information: what happened, where it happened, and whether it was good or bad for the player.

**The DM narrates; effects punctuate.** The DM describes combat actions in voice. Sound effects land in the gaps between narration to reinforce what was described. The effect confirms what the DM said, not the other way around. If the DM says "the creature lunges at you," the lunge sound effect plays immediately after, not before.

**Escalation through density.** Early in combat, effects are sparse — individual strikes, single spell impacts. As combat intensifies (phase transitions, multi-enemy encounters), the audio density increases: more overlapping effects, faster DM narration, tighter gaps between sounds. The player feels the escalation through the increasing density of the audio mix.

**Phase transitions are audio events.** When a boss enters a new phase, the entire audio landscape shifts: music changes, ambient sounds alter, new sound effects appear. The player knows something changed because *everything* sounds different. See *Game Design — Boss Fights* for multi-phase structure.

### Combat Sound Categories

**Weapon impacts.** Each weapon type has a distinct audio signature:
- Swords: sharp metallic ring on impact, varying with material (steel on steel, steel on flesh, steel on stone)
- Blunt weapons: heavy thud with material variation, more bass than bladed weapons
- Bows: the string release, the whistle of flight, the impact (thud for flesh, crack for shield, clatter for stone)
- Magic: elemental sounds — fire crackles and whooshes, ice cracks and crystallizes, lightning snaps and ozone sizzles, force magic hums and thumps

**Player feedback.** Sounds that tell the player about their own state:
- Hit taken: a physical impact sound with a brief, low "body hit" thud — the player should feel it
- Critical hit landed: a sharper, more satisfying version of the weapon impact with a bright harmonic overtone
- Near miss: a whoosh of displaced air, close and fast
- Health low: the player's own heartbeat becomes audible, increasing in rate and volume as HP drops — the most personal and urgent sound in the game
- Status effect applied: each status has a signature sound (poison: a wet hiss, stun: a high-pitched ringing, blessed: a warm chime, cursed: a discordant tone that lingers)

**Enemy audio.** Enemies are identified and located by sound:
- Each enemy type has a signature sound: the scrape of bone on stone for undead, the wet squelch of corrupted flesh, the chitinous click of hollow-spiders, the low growl of a beast
- Enemy positioning is communicated through spatial audio (left/right panning, distance through volume) — the player hears the enemy circling them
- Enemy attacks have wind-up sounds that serve as dodgeable cues — the player hears the swing before the impact

**Dice rolls.** The physical sound of dice hitting a table. This is a non-diegetic element — the dice don't exist in the game world — but the sound is deeply satisfying and communicates a game mechanic moment. Different outcomes have subtly different sounds: a natural 20 has a bright, resonant landing; a natural 1 has a dull thud. The player learns these sounds unconsciously.

---

**AI Generation Prompt — Sword Impact, Steel on Steel:**
> Sound effect of a sword striking against another metal weapon or shield. Sharp, bright metallic clash with a quick decay. The initial transient is crisp and cutting, followed by a brief metallic ring that fades over about 0.5 seconds. Not cinematic or over-processed — realistic weight and physics, as if two actual steel blades collided. Duration: 0.5-1 second. Generate 5 variations with slightly different angles and intensities.

**AI Generation Prompt — Player Heartbeat (Low Health):**
> A human heartbeat sound designed to play as a subtle audio layer when a game character is badly injured. Starts at a normal resting rate (60 bpm) and has variations at 90, 120, and 150 bpm for increasing severity. The heartbeat should be warm and deep — felt in the chest, not clinical. Slightly muffled, as if heard from inside the body. Each beat has a slight bass thump followed by a softer secondary pulse. This should feel intimate and vulnerable, not dramatic. Duration: 10-second loops at each rate.

**AI Generation Prompt — Dice Roll, Natural 20:**
> The sound of a single polyhedral die (d20) rolling across a wooden table and coming to rest. The roll should have 2-3 bounces with a satisfying clatter, followed by the die settling with a final decisive tap. The landing sound is bright and resonant — the acoustic equivalent of a perfect outcome. A very subtle warm harmonic overtone on the final settle, barely perceptible, that makes this roll feel luckier than normal. Duration: 1.5-2 seconds. Generate 3 variations.

**AI Generation Prompt — Dice Roll, Natural 1:**
> The sound of a single polyhedral die (d20) rolling across a wooden table and coming to rest. The roll should feel heavier and more reluctant than a normal roll — one extra bounce before it settles. The landing sound is flat and dull, with a slight dampened quality as if the die landed on something soft. No overtone, no ring — just a thud. The acoustic equivalent of bad luck. Duration: 1.5-2 seconds. Generate 3 variations.

---

## Music Design

Music in Divine Ruin is an atmospheric tool, not a soundtrack. It operates below conscious attention most of the time, supporting the emotional tone without demanding focus. When it rises to the foreground, it does so for specific dramatic reasons — and the contrast with its usual restraint makes those moments powerful.

### Music Principles

**Less is more.** Long stretches of the game should have no music at all — just ambient soundscape and voice. Music entering a scene is itself a signal: something has shifted. If music plays constantly, it loses its communicative power.

**Adaptive, not linear.** Music doesn't play as fixed tracks. It exists as layers and stems that the game mixes in real-time based on state: exploration layers, tension layers, combat layers, wonder layers. Stems crossfade as conditions change. The player never hears a "song start" or "song end" — the music evolves continuously.

**Acoustic over orchestral.** The base musical palette is organic and acoustic: strings (solo cello, violin, viola), woodwinds (flute, low whistle, clarinet), percussion (frame drums, hand percussion, subtle timpani), and voice (wordless vocal pads, distant choral textures). Full orchestral arrangements are reserved for major narrative moments — a god speaking, a boss phase transition, a revelation. The contrast between the intimate acoustic palette and the rare orchestral swell is part of the emotional architecture.

**Cultural inflection.** Each culture in Aethos has a musical signature that flavors the music in their regions:
- **Sunward Accord:** Warm strings, pastoral woodwinds, major modes. Mediterranean folk influence. The sound of civilization and craft.
- **Keldara (Mountain Clans):** Heavy percussion, droning low strings, war chants. Norse/Celtic folk influence. The sound of stone and endurance.
- **Vaelti (Northern Frontier):** Open fifths, sparse instrumentation, solo voice cutting across wind. Scandinavian folk influence. The sound of vast, cold space.
- **Aelindra (Scholar Remnant):** Complex harmonies, crystalline tones, harp and glass-like sounds. Minimalist classical influence. The sound of knowledge and precision.

### Music States

The game's adaptive music system moves between states, each with a distinct emotional character:

**Silence (default for many locations).** No music. Ambient soundscape only. This is a deliberate choice — many locations, especially wilderness and roads, default to no music. The world is enough.

**Exploration.** Sparse, breathing instrumentation. A solo instrument (cello, flute, low whistle) playing a simple, wandering melody over a drone or pad. Unhurried. Gentle. Enters and exits subtly. Plays during calm movement through interesting areas — not during every moment of travel.

**Tension.** The exploration melody fragments. Dissonant intervals creep in. Rhythm appears — a quiet pulse underneath. Lower register. The player should feel that something is about to happen without the music telling them what. Enters when the DM detects potential conflict, environmental danger, or Hollow proximity.

**Combat.** Full rhythmic energy. Percussion drives the tempo. Strings become aggressive and staccato. The melody from exploration may appear in a minor key or fragmented. Intensity scales with combat difficulty — a minor skirmish gets light percussion and tense strings; a boss fight gets the full palette. Music is mixed louder in combat but still ducks under DM narration during critical descriptions.

**Wonder.** Open harmonies, high register, sustained tones. The music breathes and holds. Used for revelations, first sights of grand locations, divine encounters, and narrative moments that should feel transcendent. Rare — this state should appear only a few times per session at most.

**Sorrow.** Solo instrument, simple melody, minor key, slow tempo. No percussion. Used for death, loss, grief, and the weight of consequences. The music should feel like it's mourning alongside the player.

**The Hollow.** Music ceases to function normally. Melodic lines distort and bend. Harmonies collapse into dissonance and then into pure texture. In deep Hollow zones, "music" becomes indistinguishable from the Hollow's ambient sound design — a deliberate dissolution of the boundary between score and sound design. The music doesn't accompany the Hollow; the Hollow *consumes* the music.

**Stingers.** Short musical punctuation marks (2-5 seconds) for specific game events: quest completion, item discovery, level up, faction reputation shift, god whisper arrival. Each is a brief melodic phrase that the player learns to associate with the event type. Bright and warm for positive events; minor and unresolved for complications.

---

**AI Generation Prompt — Exploration Theme, Sunward Accord:**
> A gentle, pastoral exploration theme for a warm Mediterranean-inspired fantasy region. Solo cello plays a simple, wandering melody in a major mode over a sustained drone from a viola. The melody should feel like walking through golden afternoon light — unhurried, slightly wistful, beautiful. Occasional flute ornaments in the upper register. No percussion. The piece should breathe — long notes, natural pauses, space between phrases. This is not adventure music; it's the music of a quiet walk through a world that feels both safe and mysterious. Acoustic instruments only, no synthesizers. Duration: 90 seconds, designed to loop seamlessly. The loop point should feel like a continuation, not a restart.

**AI Generation Prompt — Combat, Standard Encounter:**
> Energetic combat music for a fantasy RPG. Driving percussion (frame drums, toms, aggressive hand percussion) establishes a fast tempo (140-160 bpm). Staccato strings play tense, minor-key phrases in the mid-register. A low cello drone anchors the harmony. The melody is fragmented and aggressive — short phrases that repeat and build, not a singable tune. Energy is sustained but varies in intensity — some measures pull back to just percussion and drone before the strings surge back. Acoustic instruments only. Mood: dangerous, physical, urgent but controlled — this is a fight the player can win if they're smart. Duration: 60 seconds, seamless loop.

**AI Generation Prompt — Wonder Stinger:**
> A short musical moment of awe and revelation for a fantasy game. Duration: 5-7 seconds. Begins with a single sustained high note (violin or soprano voice), then opens into a warm, full chord — open fifths and major intervals. A gentle shimmer of harp or chime in the upper register. The chord swells briefly and then recedes, leaving a resonant tail. The feeling should be: a door opened, and what's behind it is beautiful. Not triumphant — quietly transcendent.

**AI Generation Prompt — Hollow Music Dissolution:**
> Music that transforms from a normal fantasy exploration theme into corrupted, distorted sound design. Begin with a simple, beautiful cello melody (8 seconds). Then the melody begins to degrade: pitch becomes unstable, wavering slightly. The tempo drifts. A dissonant overtone appears underneath. By 20 seconds, the melody has fragmented into disconnected notes separated by silence. By 30 seconds, the cello sound itself has transformed — it no longer sounds like a cello but like something imitating a cello poorly. By 45 seconds, all trace of music has dissolved into abstract, tonal sound design: drones, spectral textures, and the absence of melody. The piece should feel like watching something beautiful be slowly consumed. Duration: 60 seconds. Not a loop — a one-way transformation.

---

## UI and Feedback Audio

Non-diegetic sounds that exist outside the game world — interface feedback, notifications, system confirmations. These should be minimal, consistent, and emotionally appropriate. The player should barely notice them consciously, but they should feel wrong if removed.

### UI Sound Principles

**Minimal and organic.** UI sounds should feel like they belong in a world of wood, stone, and firelight — not a digital interface. Soft taps, resonant tones, materials interacting. No digital beeps, no synthetic clicks.

**Consistent grammar.** Similar actions produce similar sounds. All confirmations share a tonal family. All errors share a tonal family. All notifications share a tonal family. The player learns the grammar unconsciously.

**Brief.** UI sounds are 0.2-0.8 seconds. They punctuate, never linger.

### UI Sound Categories

**Confirm/Select:** A soft, warm tap — like a finger on wood or stone. Brief, satisfying, with a slight resonant tail.

**Cancel/Back:** A softer, duller version of the confirm sound. Slightly lower pitch. The feeling of stepping back.

**Error/Unavailable:** A muted, dampened tone — not harsh or alarming, just a gentle "no." Like tapping on something padded.

**Notification arrival:** A small chime — crystalline but warm, not sharp. Two notes, ascending, brief. The sound of something arriving.

**Async activity complete:** A slightly fuller version of the notification chime — three notes instead of two, with a satisfying resolution. The sound of something finishing.

**Menu open/close:** Subtle material sounds — a soft slide of wood, the quiet turn of a page, a drawer opening or closing. The metaphor is a physical object being manipulated, not a digital panel appearing.

**Scroll/Navigate:** Very quiet, very brief — a whisper of movement, like a finger sliding across parchment.

---

**AI Generation Prompt — UI Confirm Sound:**
> A brief, satisfying confirmation sound for a fantasy game UI. The sound of a finger tapping on a smooth wooden surface — warm, with a slight hollow resonance. Duration: 0.3 seconds. The initial tap should be clean and tactile, followed by the briefest warm resonant decay. Organic, natural materials — not digital, not synthetic. Should feel good to hear repeatedly without becoming annoying. Generate 3 subtle variations.

**AI Generation Prompt — Notification Chime:**
> A gentle notification sound for a fantasy game — something has arrived that needs attention. Two ascending notes, small and crystalline, like tiny bells or a finger running across the rim of a small metal bowl. Warm, not sharp. The interval between notes is a major second or third — pleasant and inviting. Duration: 0.8 seconds total. Mood: "something good is here for you." Not urgent, not demanding — a gentle invitation to look. Generate 3 variations.

---

## Spatial Audio Design

Spatial audio is how the player navigates the world without visuals. Direction, distance, and environment are all communicated through how sound is positioned in the stereo (and eventually binaural) field.

### MVP: Stereo Positioning

For MVP, spatial audio uses basic stereo panning and volume-distance modeling:

**Left-right panning.** Sound sources are positioned in the stereo field based on their relative direction from the player. An NPC to the player's left speaks from the left channel. A sound from behind is slightly muffled and centered (limited by stereo). The DM narrates direction when spatial audio alone isn't sufficient: "You hear footsteps approaching from behind you."

**Distance through volume and filtering.** Close sounds are louder and brighter (full frequency range). Distant sounds are quieter, with reduced high frequencies (the natural effect of distance on sound). Very distant sounds are heavily filtered, almost subliminal.

**Environmental reverb.** The reverb characteristics change with location. Indoor spaces have short, reflective reverb. Outdoor spaces have longer, more diffuse reverb. Caves and dungeons have pronounced echo. This helps the player "feel" the size and material of the space they're in, even without seeing it.

### Post-MVP: Binaural 3D Audio

Full binaural audio processing for headphone users, providing true 360-degree positioning:

**HRTF processing.** Head-Related Transfer Function processing that creates the illusion of sound sources positioned anywhere around the listener — including above, below, and behind. This transforms navigation from "the DM tells me what's around me" to "I can hear what's around me."

**The audio compass.** Key destinations emit subtle, continuous sounds that the player can orient toward. A quest objective hums. A tavern plays distant music. A companion's footsteps walk beside the player. This turns navigation into an auditory skill — the player "hears their way" to destinations.

**Dynamic occlusion.** Sound behavior changes based on what's between the player and the source. A voice behind a closed door is muffled and filtered. A sound around a corner loses high frequencies. This makes architecture audible — the player hears the layout of spaces through how sound behaves within them.

---

## Async Audio Design

The Catch-Up layer uses pre-rendered audio, not live voice. This audio has distinct design requirements from the real-time sync experience.

### Async Audio Characteristics

**Shorter and punchier.** Async narrations are 15-30 seconds, not the flowing narration of a sync session. They need to communicate information efficiently with character and warmth but without wasted words.

**Voiced but not immersive.** Async audio plays through the phone speaker or earbuds in a potentially noisy real-world environment. It should be clear and intelligible at moderate volume, not dependent on the quiet focus of a headphone sync session. More mid-range presence, less low-end atmosphere.

**Consistent tone with sync but lighter.** The DM's async narration voice should be recognizable as the same voice, but slightly more conversational and direct — less atmospheric, more informational. The companion's async voice is similarly shifted: still in character, but knowing they're delivering a quick update, not having a long conversation.

**Optional.** All async audio has text equivalents. The player can read instead of listen. The audio is an enhancement, not a requirement.

### Async-Specific Audio Assets

**World news jingle.** A 2-3 second audio signature that plays before the world news summary — a brief, recognizable motif that says "here's what happened." Should feel like the opening notes of a radio bulletin but organic and fantasy-appropriate.

**Activity resolution sound.** A brief sound that plays when tapping on a resolved activity card — a satisfying "reveal" sound, like uncovering something. Different from the notification chime — warmer, more anticipatory.

**Decision confirmation.** A brief, satisfying sound for when the player makes an async decision — tap a choice, hear the confirmation. Slightly different from the standard UI confirm — a touch more weight, acknowledging that this decision matters.

**Companion idle clips.** 5-10 second voiced clips from the companion's pool of idle chatter. Pre-rendered, rotated. These need to be recorded/generated in batches of 20-30 per companion archetype, with enough variety to avoid repetition within a week of daily check-ins.

---

**AI Generation Prompt — World News Jingle:**
> A 3-second audio signature for a daily news summary in a fantasy world. Three ascending notes played on a warm, resonant instrument — a small bell or a tapped metal bowl with a wooden beater. The notes are simple, clear, and recognizable — the kind of motif you'd learn to associate with "here's what happened today." Followed by a brief, warm sustain that fades to silence. Not urgent or dramatic — inviting and routine, like the opening of a familiar radio program. Mood: "let me tell you what happened." Generate 1 master version.

---

## Audio Asset Inventory — MVP Requirements

The following is a prioritized list of audio assets needed for the MVP launch, organized by category. Each asset includes a description sufficient for AI generation.

### Environmental Soundscapes (Priority 1)

| Asset ID | Location | Condition | Duration | Description |
|---|---|---|---|---|
| ENV-001 | Market Square / Town Center | Day, normal | 60s loop | Busy medieval market. See town daytime prompt above. |
| ENV-002 | Market Square / Town Center | Night, normal | 60s loop | Quiet nighttime town. See town night prompt above. |
| ENV-003 | Market Square / Town Center | Day, corrupted | 60s loop | Thinned market with subsonic unease. See town corrupted prompt above. |
| ENV-004 | Millhaven (village) | Day, normal | 60s loop | Small pastoral farming village. Distant livestock, wind through grass, a single hammer on wood, birdsong, a cart on a dirt road. Warmer and quieter than the market town. |
| ENV-005 | Millhaven (village) | Night, normal | 60s loop | Village at night. Crickets, a dog settling, wind through thatch, the creak of a farmhouse. Very quiet — the isolation is part of the identity. |
| ENV-006 | Millhaven (village) | Day, corrupted/panicked | 60s loop | Village in crisis. Urgent voices, hurried footsteps, children crying in the distance, a cart being loaded quickly. The pastoral sounds are still there underneath — it's the same place, but fear has changed the texture. |
| ENV-007 | Road / Wilderness path | Day, normal | 60s loop | Temperate forest road. See forest daytime prompt above. |
| ENV-008 | Road / Wilderness path | Night, normal | 60s loop | Forest road at night. See wilderness corrupted night prompt for reference, but without corruption — just natural nighttime forest. |
| ENV-009 | Road / Wilderness path | Day, corrupted | 60s loop | Forest with thinning natural sounds and Hollow presence. Hybrid of forest daytime (reduced) and corruption overlay. |
| ENV-010 | Greyvale Ruins — entrance | Normal | 60s loop | See ancient ruins upper level prompt above. Add a barely perceptible tonal hum from the Aelindran artifacts below — the player might not notice it consciously but it's there. |
| ENV-011 | Greyvale Ruins — deep interior | Normal | 60s loop | Deeper stone corridors. Tighter reverb, less air movement, more prominent water drips. The artifact hum is slightly stronger. |
| ENV-012 | Greyvale Ruins — Hollow breach | Corrupted | 60s loop | See Hollow Breach prompt above. The most extreme soundscape in the MVP. |
| ENV-013 | Tavern interior | Normal | 60s loop | See tavern interior prompt above. |
| ENV-014 | Blacksmith shop interior | Normal | 60s loop | Small workshop. Heat shimmer in the air (a subtle hissing warmth), the ring of cooling metal, bellows breathing, the occasional hammer strike. Intimate space — close reverb, warm. |
| ENV-015 | Temple interior (Veythar) | Normal | 60s loop | See Veythar's temple prompt above. |

### Hollow Sound Effects (Priority 1)

| Asset ID | Type | Variants | Duration | Description |
|---|---|---|---|---|
| HLW-001 | Subsonic drone — light | 1 | 60s loop | Gentle version of the Hollow drone. Barely perceptible. For Stage 1-2 corruption. |
| HLW-002 | Subsonic drone — heavy | 1 | 60s loop | Full Hollow drone. See subsonic drone prompt above. For Stage 3-5 corruption. |
| HLW-003 | Reversed naturals | 10 | 3-8s each | See reversed naturals prompt above. Mix of reversed birdsong, water, wind, footsteps. |
| HLW-004 | Tonal voids | 5 | 2-4s each | Brief frequency dropouts — a notch in the audio spectrum that appears and disappears. The listener feels something was briefly absent. |
| HLW-005 | False source whispers | 5 | 5-8s each | See false source whisper prompt above. |
| HLW-006 | Corrupted voices | 5 | 3-6s each | Human-like vocalizations that aren't speech. A breath that lasts too long, a syllable repeated, a laugh that decays into texture. |
| HLW-007 | Dead silence | 1 | 3s | Absolute silence — no room tone, no ambience, nothing. Used to briefly interrupt the audio mix in Stage 4-5 corruption. The sudden absence is more disturbing than any sound. |
| HLW-008 | Hollow presence pulse | 3 | 8-12s each | A rhythmic subsonic pulse like slow, deep breathing. For Stage 5 — the Hollow as a living presence. Different tempos: slow (resting), medium (alert), fast (aggressive). |

### Combat Sound Effects (Priority 1)

| Asset ID | Type | Variants | Duration | Description |
|---|---|---|---|---|
| CMB-001 | Sword strike — metal on metal | 5 | 0.5-1s | See sword impact prompt above. |
| CMB-002 | Sword strike — metal on flesh | 3 | 0.5-1s | Duller, wetter impact than metal-on-metal. Brief. |
| CMB-003 | Blunt weapon impact | 3 | 0.5-1s | Heavy, bassy thud. Wood or metal on something that gives. |
| CMB-004 | Arrow release and flight | 3 | 1-1.5s | Bowstring snap followed by arrow whistle. |
| CMB-005 | Arrow impact — flesh | 3 | 0.3s | Sharp, quick thud. |
| CMB-006 | Spell cast — fire | 3 | 1-2s | Whoosh and crackle. Ignition building to a brief roar. |
| CMB-007 | Spell cast — ice | 3 | 1-2s | Crystallization crack and shatter. Sharp, brittle. |
| CMB-008 | Spell cast — force/arcane | 3 | 1-2s | Low hum building to a concussive thump. |
| CMB-009 | Spell cast — healing | 3 | 1-2s | Warm, rising tone with a gentle chime. Relief, not power. |
| CMB-010 | Player hit taken — light | 3 | 0.3-0.5s | A dull impact felt in the body. Brief grunt of exertion mixed with impact sound. |
| CMB-011 | Player hit taken — heavy | 3 | 0.5-1s | A larger, more painful version. Heavier bass, longer recovery sound. |
| CMB-012 | Critical hit landed | 3 | 0.5-1s | Sharper and more satisfying weapon impact with bright harmonic overtone. The player should feel good hearing this. |
| CMB-013 | Near miss | 3 | 0.3-0.5s | Fast whoosh of displaced air passing close. |
| CMB-014 | Player heartbeat — increasing | 4 rates | 10s loops each | See heartbeat prompt above. 60, 90, 120, 150 bpm versions. |
| CMB-015 | Status — poisoned | 1 | 1s | Wet, acidic hiss. |
| CMB-016 | Status — stunned | 1 | 1s | High-pitched ringing, brief. |
| CMB-017 | Status — blessed | 1 | 1s | Warm chime, ascending. |
| CMB-018 | Status — cursed | 1 | 2s | Discordant tone that lingers and wavers. |
| CMB-019 | Enemy — undead signature | 3 | 2-4s | Bone scraping on stone, dry rattle, hollow groan. |
| CMB-020 | Enemy — Hollow creature | 3 | 2-4s | Sounds that shouldn't come from a living thing — reversed breathing, clicking at wrong frequencies, a wet sound from something that should be dry. |
| CMB-021 | Combat start sting | 1 | 2s | Brief percussive hit with tense string accent. Signals combat has begun. |
| CMB-022 | Combat end sting | 1 | 2s | Resolving chord with a releasing exhale quality. Signals combat is over. |

### Dice Sounds (Priority 1)

| Asset ID | Type | Variants | Duration |
|---|---|---|---|
| DICE-001 | Standard roll | 5 | 1.5-2s |
| DICE-002 | Natural 20 | 3 | 1.5-2s |
| DICE-003 | Natural 1 | 3 | 1.5-2s |
| DICE-004 | Skill check | 3 | 1-1.5s (slightly quicker, less dramatic) |

### Music Stems (Priority 2)

| Asset ID | State | Culture | Duration | Description |
|---|---|---|---|---|
| MUS-001 | Exploration | Sunward Accord | 90s loop | See exploration theme prompt above. |
| MUS-002 | Tension | Universal | 60s loop | Fragmented melody, dissonant intervals, quiet pulse underneath. |
| MUS-003 | Combat — standard | Universal | 60s loop | See combat music prompt above. |
| MUS-004 | Combat — boss | Universal | 90s loop | Intensified combat music. Full percussion, aggressive strings, brass-like swells. Higher energy, more complex arrangement. |
| MUS-005 | Wonder | Universal | 30s (one-shot) | See wonder stinger prompt. Extended to 30s with a sustained, breathing chord. |
| MUS-006 | Sorrow | Universal | 60s loop | Solo cello, simple melody, minor key, very slow. No percussion. Space between notes. |
| MUS-007 | Hollow dissolution | Universal | 60s (one-shot) | See Hollow music dissolution prompt above. |
| MUS-008 | Title / Main menu | N/A | 120s loop | The game's identity theme. Opens with the solo cello exploration melody, builds gently to a warm full arrangement, then recedes. Sets the emotional tone before the player enters the world: "this is a place worth caring about." |

### Stingers (Priority 2)

| Asset ID | Event | Duration | Description |
|---|---|---|---|
| STG-001 | Quest stage complete | 3-5s | Bright, warm, ascending phrase. Satisfying resolution. |
| STG-002 | Quest complete | 5-7s | Fuller version of stage complete. More instruments, stronger resolution. |
| STG-003 | Item discovered | 2-3s | A brief "reveal" sound — crystalline and curious. |
| STG-004 | Level up | 5-7s | Warm, ascending, expansive. The player should feel growth. |
| STG-005 | Faction reputation shift | 2-3s | Neutral tone — could be positive or negative. A shift, not a judgment. |
| STG-006 | God whisper arrival | 3-5s | Ethereal, other-worldly. Sets up the god's voice. Varies by god. |
| STG-007 | Death | 5-7s | Low, sustained, fading. Not dramatic — solemn. The world going quiet. |
| STG-008 | Session start | 3-5s | The sound of entering the world. A door opening, air rushing in, the first note of ambience. |
| STG-009 | Session end | 5-7s | The sound of the world gently releasing you. Ambience fading, a final warm note. |

### UI Sounds (Priority 2)

| Asset ID | Action | Variants | Duration |
|---|---|---|---|
| UI-001 | Confirm / Select | 3 | 0.3s |
| UI-002 | Cancel / Back | 2 | 0.3s |
| UI-003 | Error / Unavailable | 2 | 0.3s |
| UI-004 | Notification arrival | 3 | 0.8s |
| UI-005 | Async activity complete | 2 | 1s |
| UI-006 | Menu open | 1 | 0.5s |
| UI-007 | Menu close | 1 | 0.5s |
| UI-008 | Scroll / Navigate | 2 | 0.2s |
| UI-009 | World news jingle | 1 | 3s |
| UI-010 | Decision confirmation (async) | 2 | 0.4s |

### Async Companion Idle Clips (Priority 2)

Per companion archetype, 20-30 pre-rendered voiced clips of 5-10 seconds each. These are generated via TTS using the companion's `voice_id` and personality-appropriate scripts. Examples:

**Kael idle pool (sample):**
- "Still waiting on Grimjaw. You know he won't rush it."
- "Quiet day. Almost suspicious."
- "I've been thinking about what that scholar said. Something doesn't sit right."
- "Nice weather. Reminds me of the road between Accord and Millhaven before... well. Before."
- "You ever wonder what the gods actually do all day? Besides watch us stumble around."

**Lira idle pool (sample):**
- "I re-read those markings in my head three times. Still can't reconcile the dates."
- "Nothing to report. Which itself is interesting, given the circumstances."
- "The market's quieter than yesterday. People are nervous."
- "I suppose patience is a virtue. It's not one of mine, but it's someone's."
- "When this is over, I'm writing a paper about it. Assuming anyone would believe me."

**Tam idle pool (sample):**
- "Hey. Still here. Still bored. Let's go do something."
- "I asked that guard about the north road. He didn't want to talk about it. Classic."
- "Do you think Grimjaw actually likes us? I can never tell with that guy."
- "I had the weirdest dream last night. You were in it, actually. Never mind."
- "If nothing's happening, I'm going to go see if I can climb that wall. Back in a bit."

---

## Audio Technical Requirements

### File Formats and Specifications

| Category | Format | Sample Rate | Bit Depth | Channels | Notes |
|---|---|---|---|---|---|
| Environmental soundscapes | .ogg (Vorbis) | 48 kHz | 16-bit | Stereo | Optimized for seamless looping |
| Sound effects | .ogg (Vorbis) | 48 kHz | 16-bit | Mono | Mono for spatial positioning by client |
| Music stems | .ogg (Vorbis) | 48 kHz | 16-bit | Stereo | Separate stems for adaptive layering |
| UI sounds | .ogg (Vorbis) | 44.1 kHz | 16-bit | Mono | Small file size priority |
| Dice sounds | .ogg (Vorbis) | 48 kHz | 16-bit | Mono | Crisp transients preserved |
| Async companion clips | .mp3 | 44.1 kHz | 128 kbps | Mono | Compressed for fast delivery |
| Pre-rendered async narration | .mp3 | 44.1 kHz | 128 kbps | Mono | Generated per-player, stored server-side |

### Client Audio Engine Requirements

- Simultaneous channel support: minimum 8 channels (2 voice + 1 music + 3 ambience layers + 2 effects)
- Crossfading between soundscapes: 2-3 second linear crossfade on location change
- Ducking: voice-triggered side-chain compression on music and ambience channels (40-60% reduction, 50ms attack, 200ms release)
- Randomized texture playback: ability to select randomly from a pool and trigger at randomized intervals
- Volume bus structure: Master → Voice, Music, Ambience, Effects, UI (each independently controllable in Settings)

### Server-Side Audio Pipeline

Pre-rendered async narrations follow this pipeline:
1. Activity resolves during simulation tick
2. LLM generates narration text (system prompt specifies async voice: concise, conversational, in-character)
3. TTS synthesizes to audio using character's `voice_id` and appropriate emotion tag
4. Audio file stored in player's async content bucket (S3 or equivalent)
5. Client fetches audio URL on next check-in
6. Audio expires after 7 days (player has already heard it or it's no longer relevant)

---

## Open Audio Design Questions

1. **Adaptive music middleware.** What technology handles the real-time mixing of music stems based on game state? Options include FMOD, Wwise, or a custom solution built on the Web Audio API. The choice affects how complex the adaptive music system can be.

2. **Binaural audio library.** For post-MVP spatial audio, which HRTF library and processing pipeline? Resonance Audio (Google), Steam Audio, or a custom solution? This affects headphone-only features.

3. **AI generation consistency.** Current AI audio generation tools produce high variation between generation sessions. How do we ensure that ENV-001 generated today sounds consistent with ENV-002 generated next week? Potential approaches: extensive prompt engineering, reference audio conditioning, post-processing normalization, or generating all assets for a location in a single session.

4. **Voice acting vs. TTS for async companion clips.** The idle pool clips (20-30 per companion) are short and repeated. Would human voice acting produce significantly better results than TTS for these frequently-heard clips? Cost-benefit analysis needed.

5. **Player audio preferences.** Some players may prefer more or less ambient sound, or may want to disable music entirely. How granular should the audio settings be? Current plan: 5 volume sliders (voice, music, ambience, effects, UI). Is that sufficient?

6. **Hollow audio personalization timeline.** The design calls for personalized Hollow audio manifestations (hearing your own companion's voice, sounds from your starting culture) post-MVP. What's the technical path from standardized Hollow audio to player-specific audio? Can TTS generate personalized Hollow whispers in real-time?

7. **Accessibility.** How do we serve hearing-impaired players in a voice-first game? Subtitles/captions are essential for all voiced content. But environmental audio carries gameplay information (enemy position, corruption proximity, location identity) that captions can't fully convey. What alternative systems (haptic feedback, visual indicators on screen) can supplement audio for accessibility?
