# Divine Ruin — Design Decisions Log

> **Claude Code directive:** This is the canonical record of all locked design decisions. Every numbered decision represents a deliberate choice with documented reasoning. When questioning why a system works a certain way, check here first.
>
> **How to use:** Decisions are numbered sequentially (1-57) in the order they were made. Each includes the reasoning that led to the choice. Grouped by system area for readability, but the number reflects chronological design order.

---

## Core Systems, Combat & Character Creation (Decisions 1-53)

1. **Bounded accuracy chosen over escalating numbers.** Reason: d20 must always carry tension in voice-first play. Growth comes through capability breadth, not bigger numbers. (Total modifier spread: 14 points across 20 levels.)

2. **Four skill tiers, not three.** Reason: three tiers only gave 2 advancement moments per skill. Four tiers (Untrained/Trained/Expert/Master) give 3 moments, with Expert and Master adding qualitative capability gates, not just numeric bonuses.

3. **Proficiency bonus compressed to +1/+2/+3.** Reason: with skill tier bonuses stacking on top, a full +1 to +5 proficiency scale would push the ceiling past bounded accuracy limits. The compressed scale keeps the max modifier at +13.

4. **Hybrid skill advancement (session use + Training async).** Reason: Training is one of three async activity categories and must remain useful throughout the entire game. Use-based counters are the primary track; Training accelerates them. Expert→Master additionally requires a qualifying narrative moment for dramatic impact.

5. **Dual resource pools (Stamina/Focus) over spell slots.** Reason: continuous pools create ongoing tension ("do I spend now or save?") which is narratively richer than discrete slot tracking. Two pools prevent martial/magical abilities from competing on the same resource, making hybrid archetypes (Paladin, Bard) feel rewarded rather than punished.

6. **20-skill list over 15.** Reason: breadth is the long-game engine for the Training async loop. More skills = more things to train = Training stays relevant across a full playthrough.

7. **HP half-CON growth rule.** Reason: without it, high-CON characters at level 20 would exceed 200 HP, breaking the damage math and combat pacing target of 3-5 rounds.

8. **Level 5 specialization fork for every archetype.** Reason: this is where build diversity opens up. Combined with 10 divine patrons, 6 base archetypes × 2 specializations × 10 patrons = 120 distinct builds from just the first 6 archetypes.

9. **Resonance system over traditional spell slots or simple Focus spending.** Reason: the Hollow and the damaged Veil are the defining features of Aethos's lore. Resonance makes them *mechanically present* in every combat involving magic, not just narrative wallpaper. It creates risk-reward tension unique to Divine Ruin, differentiates the three magic sources at the mechanical level, and gives racial traits genuine system integration rather than cosmetic flavor.

10. **Three magic sources (Arcane/Divine/Primal) with distinct Resonance rates.** Reason: a single undifferentiated "magic" system would waste the cosmological depth of the lore. Arcane casters pulling from ambient Wellspring residue should feel fundamentally different from Clerics channeling through a divine filter or Druids amplifying the world's immune response. Different Resonance rates make this felt, not just described.

11. **Resonance is DM-narrated, not shown on HUD.** Reason: voice-first philosophy. The player feels their Resonance state through fiction — the DM describes the Veil shuddering, the magic looking wrong, the creeping attention from beyond. This preserves immersion and makes the Elari racial trait and Arcana skill investment meaningful as information channels.

12. **Every race has a unique Resonance interaction.** Reason: race selection should matter mechanically beyond starting attributes. The Elari's passive Veil-sense, the Human's faster Resonance decay, the Korath's earth-grounding, the Vaelti's Hollow Echo warning, the Draethar's fire purge, and the Thessyn's long-term adaptation all create distinct gameplay experiences for casters of different races.

13. **Four-layer divine patron system (gift, resonance modifier, favor abilities, archetype synergy).** Reason: 10 gods × 16 archetypes = 160 combinations. Designing each individually is impractical and impossible for the DM LLM to track. The four-layer system composes cleanly: every follower gets Layers 1–3, Layer 4 enhances specific archetype categories. No god is the "best" choice for any archetype — each creates a distinct playstyle identity.

14. **The Unbound path as a mechanically viable no-patron option.** Reason: "no patron" must not be a trap. The Unbound trade divine safety nets for unmediated Veil awareness (exact Resonance numbers), voluntary Resonance control (+3 on demand), and unique endgame relevance (no divine filter coloring their perception of the Wellspring). Hardest early game, most rewarding late game — the choice for players who trust themselves more than any god.

15. **Crafting as the 20th skill, using higher of INT or WIS.** Reason: supports the Artificer archetype, connects to Aelora's and Thyra's domains, and directly powers the async crafting loop. Using max(INT, WIS) allows both analytical crafters (Artificer studying material science) and intuitive crafters (Druid shaping living wood) without locking the skill to one playstyle.

16. **Crafting skill (competence/ceiling) is distinct from async crafting activity (time/opportunity).** Reason: if they blur together, one loses its identity. The skill determines *what you can make and how good it is*. The async activity provides *hours of labor*. They feed each other: async crafting sessions increment the Crafting skill counter, naturally advancing the player toward Expert through use.

17. **Expert unlocks gate new action categories; Master unlocks grant always-active signature capabilities.** Reason: qualitative tier gates give the DM clear logic ("is this action possible for this character?") and give players aspirational targets that reward long-term skill investment through the Training async loop. Master abilities are deliberately powerful enough to reshape how the character interacts with the world.

18. **Players name spells explicitly, not by intent description.** Reason: intent matching ("I blast them with fire" → fuzzy resolution) adds a round-trip of ambiguity to voice play. Each character has a manageable spell list on their character sheet; learning your toolkit IS the player skill. The DM calls the rules engine with the exact spell name. No fuzzy matching, no disambiguation.

19. **Core + elective split for all archetypes.** Reason: purely fixed ability lists (every Mage identical) sacrifice the "building my character" fantasy. Purely open lists (choose everything) sacrifice archetype identity. The hybrid (~5 core + electives) preserves both: the DM can always assume any Mage has Counterspell, while two Mages at the same level can have completely different elective loadouts.

20. **Three-track spell acquisition (slots from levels, knowledge from Training, preparation on long rest).** Reason: "level up and suddenly know Fireball" is narratively hollow. Separating capacity (slots) from knowledge (library) from loadout (preparation) creates a three-way tension in how players spend their async Training time: learn new spells vs. advance skills vs. train attributes. All three are valid, all create different builds, and the Training async loop becomes the central long-term progression engine.

21. **Martial mentor-style variants as the depth equivalent of caster spell breadth.** Reason: a 1:1 port of the spell catalog model doesn't work for martials (too few techniques to create meaningful choice from a large pool). Instead, martials get *depth* on each technique through cultural style variants trained with NPC mentors. This connects martial Training to exploration, NPC relationships, faction reputation, and cultural lore — turning "learn a fighting move" into 2-3 sessions of organic gameplay. The variant attribution on the character sheet ("Cleaving Blow — Steppe Wind variant, trained under War Captain Dreva") becomes a source of player identity and pride.

22. **Martial elective technique choice is fewer but weightier than caster spell choice.** Reason: a Warrior commits to a fighting philosophy (2 big choices from curated pools of 4). A Mage builds a library (many smaller choices from a large catalog). Both end up with massive build diversity when multiplied across all layers (race, archetype, specialization, patron, electives), but the texture of choice-making matches the fantasy: martial characters commit, casters collect.

23. **87 spells across three source catalogs (Arcane 30, Divine 28, Primal 29).** Reason: each source needs enough spells to fill elective slots across 20 levels while maintaining distinct identity. Arcane leads in raw damage and control. Divine leads in healing, protection, and anti-Hollow. Primal leads in terrain manipulation and area denial with terrain-variable Resonance. The Bard's cross-source access draws from all three, making spell choice the core of Bard build identity.

44. **Phase-based action economy: one declaration per phase, abilities expand the declaration.** Reason: voice-first combat cannot support "I do action A, then bonus action B, then move 30 feet." Players say one thing; the engine resolves everything that thing implies. "Quick action" abilities become declaration enhancers — the Rogue says "I stab and run" and Cunning Action means the engine resolves both. This keeps combat conversational while preserving the mechanical advantage of having more abilities.

45. **Initiative determines resolution priority, not turn order.** Reason: there are no turns. Everyone acts in the same phase. Initiative decides who goes first when it matters — killing before being killed, buffing before attacking, healing before the next blow. High initiative is still valuable (your action lands first) without creating the dead-time problem of turn-based combat.

46. **Reactions are voice interrupts during enemy narration.** Reason: the DM creates reaction windows by pausing mid-narration ("The mawling lunges—"). The player shouts "I block!" in real conversational time. This is the most voice-native combat mechanic in the game — reactions happen at the speed of speech, not at the speed of state-machine processing. The engine holds enemy damage until the reaction window closes.

47. **Character creation is 5 narrative choices; everything else is auto-computed.** Reason: a voice-first game cannot present 16 archetypes, 6 races, 6 attributes, 10 gods, equipment lists, and skill selections as sequential menus. The player makes 3-4 meaningful narrative choices (race, archetype, attributes, patron); the system derives culture, starting region, equipment, starting spells, and companion from those choices. The player discovers their culture and backstory through play, not through a pre-game form.

48. **Divine patron can be deferred.** Reason: new players shouldn't have to choose from 10 unknown gods. Deferring starts you as Unbound (mechanically functional) with a flag that allows a one-time commitment later through a narrative scene. This lets players discover the gods through gameplay before committing — a better experience than guessing from descriptions.

49. **Death is consequential but never permanent.** Reason: a voice RPG player has invested hours of conversation, NPC relationships, and emotional energy. Permanent death destroys all of that. Instead, death has escalating mechanical costs (stat reductions, item loss, Mortaen's debts) that make careless play expensive without ending the story. The death counter never resets — every death leaves a mark. By death 5+, the character is noticeably weakened, creating natural pressure to play carefully without the cliff of permadeath.

50. **Hollowed Death is the most horrifying moment in the game.** Reason: the Hollowed condition should terrify players. If dying while Hollowed (Stage 2+) merely sends you to Mortaen's domain like normal, the condition is just another debuff. Instead, your body rises as a Hollow creature that your allies must fight — and you hear it happen. Your companion screams your name. The DM uses your character's voice, distorted. This is the moment that makes players prioritize Greater Restoration above all other healing. The mechanical consequence (your body fights your party, then you die normally) is moderate — but the emotional consequence is devastating.

51. **Resurrection location uses an anchor-point hierarchy, not fixed respawns.** Reason: "you wake up at the last inn" is gamey. The hierarchy (battlefield if safe → nearest allied camp → last rested settlement → starter zone) creates narrative-appropriate results. Dying near the Ashmark with allies nearby means you wake on the battlefield. Dying deep in Hollow territory alone means you wake far away and days have passed — the world moved on. This makes where you die matter, which makes exploration risk meaningful.

52. **Mortaen followers get a free first death.** Reason: worshiping the god of death should have a tangible benefit related to death. The free first death (no cost, counter still increments) is the most elegant reward — it doesn't break the escalation curve, it just delays it by one. Combined with +2 to death saves, Mortaen followers are significantly harder to permanently weaken through the death system. This makes Mortaen an attractive patron for players who expect dangerous gameplay.

53. **Training cycles are variable-duration activities with midpoint decisions, not flat timers.** Reason: a flat "wait 8 hours" timer is a notification you dismiss. A variable-duration activity with a midpoint decision ("your study of Fireball reached a crossroads — power or control?") creates two engagement points per cycle: one to make the decision, one to collect the result. The variable time ranges (5-14 hours total depending on activity) mean players can't perfectly schedule around it — they check in when the notification fires. Dedicated players complete 2 short cycles/day; casual players complete 1. The midpoint decisions accumulate into micro-bonuses that make each character's learned abilities slightly unique.

---

## Bestiary & Materials (Decisions 24-29)

24. **Tier is a universal threat scale (1-4), not Hollow-specific.** Reason: natural creatures, constructs, and humanoids can be just as dangerous as Hollow expressions. A dire bear or ancient golem at Tier 3 provides encounter diversity without requiring every mid-game fight to involve the Hollow.

25. **Every creature drops materials that feed the crafting system.** Reason: combat must have tangible rewards beyond XP. The loot-harvest-purify-craft loop connects combat to the async crafting activity, the Artificer archetype, and the material economy. Every encounter is an investment, not just a resource drain.

26. **Hollow materials are tainted by default.** Reason: using Hollow materials without purification creates a meaningful risk-reward choice (power now vs. clean gear later) and creates inter-archetype dependency (Clerics purify with Dispel Corruption, Artificers purify through async activity). This ensures the party needs diverse archetypes to extract full value from Hollow encounters.

27. **Harvesting is skill-gated.** Reason: a party without Survival, Crafting, or Arcana proficiency misses loot from kills. This gives non-combat skills direct combat-adjacent value and ensures Druids, Rangers, Artificers, and Seekers contribute economically to the party even beyond their spells and abilities.

28. **The Named have full mechanical stat blocks, not just narrative descriptions.** Reason: endgame bosses need to be mechanically resolvable by the deterministic rules engine. The Choir, The Still, and The Architect are designed as fundamentally different encounter types (audio zone, distributed zone entity, dynamic terrain boss) that challenge players to solve the fight, not just survive it.

29. **The Still does not attack unless attacked.** Reason: the most horrifying enemy is the one that offers you everything you want. The Still's encounter is a psychological and moral challenge — players must destroy something beautiful to save people. This is the most narratively powerful fight in the game.

---

## NPCs, Mentors & Companions (Decisions 30-57)

30. **NPC schema extends creature stat block rather than replacing it.** Reason: every NPC that can enter combat resolves through the same engine as creatures. The NPC extension adds social, economic, and world simulation fields on top. A guard is both a social NPC (disposition, knowledge, schedule) and a combatant (HP, AC, attacks).

31. **Role archetypes are templates, not fixed stat blocks.** Reason: the world needs hundreds of NPCs. Templates let the world simulation instantiate "a blacksmith" at any settlement with appropriate stats, inventory, and personality tags without hand-authoring each one. Tier 1 NPCs override template defaults with authored personality.

32. **Mentors are distributed geographically and culturally.** Reason: training a martial variant should require traveling to the mentor's location, building relationship, and completing requirements. This turns "learn a fighting style" into 2-3 sessions of organic content (exploration, social engagement, possibly a quest). The mentor's culture gives the variant its story — "Steppe Wind" means something because you learned it from a Drathian war captain.

33. **Settlement templates define minimum role populations by size.** Reason: when the world simulation populates a new settlement, it needs to know what NPCs to create. A hamlet has no blacksmith (players must travel to a village). A city has multiple merchants of each type. This creates geographic incentive — players return to cities for services and venture to wilderness for materials.

34. **Sergeant Kael Thornridge appears as a potential mentor.** Reason: the Vigil of Greyhaven story established him as a legendary figure. If the player completes the "Vigil of Greyhaven" quest chain and finds the ruins of the watchtower, Kael (or his legacy) teaches the "Last Wall" variant of Iron Stance — an ability earned through narrative, not just Training cycles. The most powerful mentor variants require the most meaningful journeys.

35. **Every merchant type has a price modifier affected by disposition and faction reputation.** Reason: the economy must be socially responsive. An unfriendly blacksmith charges 20% more. A trusted alchemist gives 20% off. Faction reputation shifts pricing across all merchants in that faction's territory. This connects the social system to the economic system — investing in relationships has tangible mechanical reward.

54. **Companions are 75% of player combat effectiveness, scaling automatically with player level.** Reason: the encounter math assumes 1.75× a single character. The companion must be strong enough to matter (a weak companion makes combat feel solo) but not so strong that the player becomes the sidekick. 75% HP, ~65% damage output, equal AC, no elective abilities. The companion is a reliable partner, not a second player character.

55. **Each companion archetype complements the player's weaknesses, not duplicates their strengths.** Reason: a Mage who gets an arcane companion has two glass cannons and no frontline. A Mage who gets Kael (martial frontline) has a balanced party. The assignment logic matches player archetype category to the companion that fills the gap. This means every player has a functional party regardless of their build choice.

56. **Sable is mechanically distinct — lower HP, no verbal combat, perception-focused.** Reason: Sable is a shadow-fox, not a humanoid. She shouldn't fight like a person. Her 50% HP (vs 75% for others) reflects her physical fragility; her value is information (Veil Sense, Shadow Meld, Alarm) and emotional presence. The Pack Bond passive (disadvantage on attacks against a Fallen player) is her most powerful ability — protecting the player when they're most vulnerable, purely through narrative loyalty.

57. **Companion relationship progression gates secrets, not abilities.** Reason: gating combat abilities behind relationship would punish players who don't engage socially. Instead, relationship gates narrative content — the companion's secrets, personal quests, and emotional vulnerability. A player who rushes through combat and ignores the companion still has a functional combat partner. A player who talks to their companion discovers a person with depth, pain, and a story intertwined with the main mystery.

---

## Crafting & Items (Decisions 36-43)

36. **Crafting mirrors the spell acquisition three-track model.** Reason: consistency. Players who understand how spell learning works immediately understand how recipe learning works. Capacity (recipe slots), knowledge (learned recipes), and workspace (crafting location) parallel slots, library, and preparation. This reduces cognitive load for a voice-first game where the player can't reference a manual.

37. **Recipes must be learned, not inherent.** Reason: if any crafter can make anything they have materials for, there's no progression incentive and no discovery reward. Finding a schematic in a dungeon should feel exciting. Learning a recipe from an NPC should feel earned. The recipe library IS the crafter's progression, the same way the spell library is the Mage's.

38. **Experimentation allows crafting without recipes at higher DC.** Reason: voice-first play means players will say creative things the system didn't predict. "Can I mix cave wyrm acid with this Hollow residue?" deserves a real answer, not "you don't have a recipe for that." Experimentation channels creativity through the deterministic engine: valid combination + passed check = new recipe discovered.

39. **Four quality outcomes (Exceptional/Success/Partial/Failure) instead of binary.** Reason: crafting should feel like combat — tension in the roll, gradation in the result. An Exceptional outcome is the crafting equivalent of a critical hit. A Partial success is the equivalent of "you hit but they're still standing." Failure consuming materials is the cost of attempting, the same way a failed spell still costs Focus.

40. **Items have durability that degrades faster against the Hollow.** Reason: the Hollow should corrode everything — including the player's gear. This creates a logistical dimension to Hollow campaigns: you need supply lines, repair services, spare equipment. It makes the Artificer's repair abilities and the blacksmith NPC genuinely valuable. And it means the best-crafted items (Masterwork, legendary) have tangible survivability advantages beyond raw stats.

41. **Magic items are not mass-produced.** Reason: in a voice-first game, every item needs to be worth the DM describing it. A +1 sword is a story — who forged it, from what, and why. The rarity system ensures magic items feel earned and significant rather than disposable inventory.

42. **Legendary items have drawbacks or narrative weight.** Reason: Stillheart's weekly temptation, the Architect's Edge reshaping itself, Thornridge's Stand whispering names — these aren't penalties, they're *character*. An item that's pure upside is a number. An item with personality is a companion. In voice play, the DM performing the shield whispering names when the player is afraid creates a moment no stat bonus can match.

43. **Workspaces are rented or earned through reputation, never owned (Phase 1).** Reason: building ownership is a multiplayer/MMO feature (guilds, player housing, shared facilities). In single-player Phase 1, the rental model connects crafting to the economy (gold cost), the social system (disposition gates access, trusted disposition earns standing access), and geography (not every settlement has every workspace). The standing-access system through NPC relationships creates a persistent social loop — neglect the blacksmith and lose forge access. This naturally evolves into ownership in Phase 2-3 by adding deed-based access alongside the existing disposition-based access, with no structural changes to the crafting engine.

---


## Async Activities — Companion Errands & Concurrency (Decisions 58-61)

58. **Companion errands use two different decision models based on narrative logic.** Reason: a scout deep in hostile territory wouldn't break cover to ask a question — the return IS the content. But a companion gathering herbs locally who stumbles on something unexpected would naturally pause and ask "change of plans?" Scouting and relationship errands use end-of-errand decisions only. Social and acquisition errands use midpoint decisions like Training. The player learns instinctively which errands need a check-in and which are fire-and-forget.

59. **Companions on errands are unavailable for sync combat.** Reason: if there's no tradeoff, the player always sends the companion on errands. Making the companion physically absent during errands creates a real decision: intel and resources vs combat support. Short relationship errands (2-4 hours) are low-risk. Long scouting missions into dangerous territory (8+ hours) are a deliberate gamble — you might enter a voice session alone. This makes errand planning feel strategic, not automatic.

60. **Three independent activity slots, not three activities of any type.** Reason: one Training + one Crafting + one Companion Errand as separate slots means the three systems don't compete with each other. A player doesn't have to choose between learning a spell and crafting a sword — they do both. This encourages the 3-4 concurrent activity baseline the GDD describes as the natural engagement state. The Artificer exception (Portable Lab frees a second crafting slot) is a class-specific reward that reinforces the Artificer's identity as the master async crafter.

61. **Companion errands carry actual risk that creates organic content.** Reason: risk-free errands are just timers. When a scouting mission into dangerous territory has a 25% chance of the companion returning injured and a 5% chance of an emergency (rescue side quest), the player feels real tension when choosing dangerous destinations. The rescue mission that triggers from a failed errand is content the async system generated organically — no author scripted it, the rules engine created a quest from a dice roll. This is the async system at its best: mechanical resolution creating narrative.


## Racial Traits & Level Progression (Decisions 62-63)

62. **Humans and Thessyn get flexible attribute bonuses; other races get fixed.** Reason: Humans (+1 to any two) and Thessyn (+1 to any three, max +1 each) represent adaptability — the defining trait of both races. Elari (+2 INT, +1 WIS), Korath (+2 CON, +1 STR), Vaelti (+2 DEX, +1 WIS), and Draethar (+2 STR, +1 CHA) have fixed bonuses that reinforce their biological identity. Fixed bonuses create natural archetype affinities (Elari lean Mage, Korath lean Guardian) without preventing any combination — a Korath Mage is viable, just not optimized. Flexible races can optimize any archetype, which is their racial advantage.

63. **Thessyn Deep Adaptation is a long-term evolving trait, not a static bonus.** Reason: Thessyn are defined by environmental attunement — their bodies literally change over time. A static racial ability would betray that identity. Instead, Thessyn gain adaptations based on where they spend time (10 sessions per adaptation, max 3, newest replaces oldest). This is the most mechanically complex racial trait and the most narratively rewarding — the DM narrates physical changes as they occur, making the Thessyn's body a record of their journey through Aethos. A Thessyn who spent 30 sessions moving between three regions has three different adaptations that tell their story.


## Social Encounter Resolution (Decisions 64-67)

64. **Social encounters use three tiers of resolution: simple checks, contested exchanges, and structured scenes.** Reason: a single resolution model can't handle both "convince the guard" and "negotiate a faction peace treaty." Simple checks (80% of interactions) are invisible — the player talks, the engine resolves, the NPC reacts. Contested exchanges (Spy probing, Deception vs Insight) are always dramatic — both sides are actively engaged. Structured scenes (Diplomat De-escalating combat, faction negotiations) play out over multiple argument phases like social combat. Each tier matches the narrative weight of the interaction.

65. **Disposition shifts are the "damage" of social encounters.** Reason: social encounters need a mechanical currency that connects to the world simulation. Disposition is already tracked per-NPC and affects prices, knowledge gates, quest access, workspace access, and mentor availability. Shifting an NPC from Hostile to Neutral through conversation is the social equivalent of winning a combat encounter — it unlocks gameplay that was previously unavailable. This means social specialists (Diplomat, Spy, Bard) have tangible mechanical impact beyond flavor.

66. **Intimidation achieves compliance but damages the relationship.** Reason: if Intimidation is just "Persuasion but scary," there's no reason to ever use Persuasion. Making Intimidation shift disposition negative on success (resentful compliance) creates a real tradeoff: you get what you want now, but the NPC will charge you more, refuse service, or report you later. Persuasion is slower but builds lasting goodwill. This makes skill choice in social encounters meaningful — the Warrior who intimidates the merchant pays for it; the Diplomat who persuades pays nothing.

67. **Most social checks are invisible; only high-stakes moments get visible dice.** Reason: this follows the GDD's "Narrative-First with Dramatic Dice" philosophy. Routine social checks would break immersion if the player saw dice rolling every time they talked to a shopkeeper. But when a Diplomat tries to stop a war, or a Spy tries to extract a secret from a suspicious NPC, the dice animation and audio cue create real tension — the player watches the die tumble and waits for the result. The `dramatic` flag in the resolution engine determines which moments earn the visible treatment.


## Dramatic Dice System (Decision 68)

68. **Dramatic dice are rare by design — 0-2 per typical combat, 0-1 per social encounter.** Reason: the visible dice roll (HUD animation, audio cue, DM pause) is the most powerful tension tool in the game. Its power comes entirely from scarcity. If every attack triggers the animation, the player stops noticing. If the dice only appear for death saves, killing blows, boss attacks, crits, Counterspell contests, and razor-thin outcomes, the player's heart rate spikes every time they hear the dice audio cue. The "always dramatic" list (7 roll types) and "contextually dramatic" engine rules are calibrated so that a 5-phase Tier 2 combat shows 0-2 dramatic dice, a boss fight shows 3-5, and a social encounter shows 0-1. The player learns that when the dice appear on screen, this moment actually matters — and that Pavlovian response is worth more than any visual effect.


## Travel, Exploration & Gathering (Decisions 69-71)

69. **Travel has three modes (compressed/scenic/dangerous) selected by the engine, not the player.** Reason: voice-first travel can't be a menu. The engine evaluates route danger, player level, and world state, then selects the mode. Safe routes are compressed to 15-second montages — no one wants to roleplay walking down a safe road. First-time routes are scenic — 2-5 minutes of worldbuilding narration that IS the content. Dangerous routes are full gameplay with encounters, decisions, and exhaustion. The player says "I head to Millhaven" and the engine decides how that journey plays out.

70. **Gathering happens during travel and exploration, not as a standalone activity.** Reason: a separate "gathering mode" would feel like a mobile game resource grind. Instead, gathering is woven into the journey — "I search for herbs while we travel" or the DM offers a discovery encounter. One attempt per travel segment prevents spam. The skill check (Survival for minerals, Nature for plants, Arcana for magical components) connects gathering to the skill system. A player with Expert Nature finds better herbs; a player with no Nature skill finds common weeds. The material pipeline flows naturally: travel → gather → craft.

71. **Gathering nodes are discovered through exploration, not marked on the map by default.** Reason: if every ore vein and herb patch is pre-marked, gathering becomes a checklist. Discovery through Perception checks, companion scouting, NPC tips, and quest rewards makes finding a good gathering spot feel earned. Once found, nodes are marked for return visits — but they deplete and respawn on the simulation tick, creating a natural rhythm of visit → gather → wait → return. In multiplayer (Phase 2), this creates competition for prime gathering spots.


## Economy Reconciliation (Decision 72)

72. **1 gc = 10 sp (not 100 sp), matching the lore bible's Sun/Mark ratio.** Reason: the lore bible defines 10 Marks (silver) = 1 Sun (gold). The GDD originally said 1 gc = 100 sp, creating an incompatibility. Adopting 1 gc = 10 sp keeps a clean decimal system (10 cp = 1 sp, 10 sp = 1 gc), matches the lore's established ratio, and makes "gold crown" prices intuitive: Half Plate at 50 gc = 500 sp (~1.4 years' unskilled labor) is appropriate for rare military armor. Plate at 100 gc = 1,000 sp (~2.7 years) is appropriate for the most expensive mundane item. Revivify diamond at 50 gc = 500 sp is appropriate for a death-prevention component. The GDD's economy section needs to be updated to match. All "gp" notation in mechanics docs has been corrected to "gc."

