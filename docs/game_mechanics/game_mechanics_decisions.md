# Divine Ruin — Design Decisions Log

> **Claude Code directive:** This is the canonical record of all locked design decisions. Every numbered decision represents a deliberate choice with documented reasoning. When questioning why a system works a certain way, check here first.
>
> **How to use:** Decisions are numbered sequentially (1-128) in the order they were made. Each includes the reasoning that led to the choice. Grouped by system area for readability, but the number reflects chronological design order.

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

13. **Four-layer divine patron system (gift, resonance modifier, favor abilities, archetype synergy).** Reason: 10 gods × 18 archetypes = 180 combinations. Designing each individually is impractical and impossible for the DM LLM to track. The four-layer system composes cleanly: every follower gets Layers 1–3, Layer 4 enhances specific archetype categories. No god is the "best" choice for any archetype — each creates a distinct playstyle identity.

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

47. **Character creation is 5 narrative choices; everything else is auto-computed.** Reason: a voice-first game cannot present 18 archetypes, 6 races, 6 attributes, 10 gods, equipment lists, and skill selections as sequential menus. The player makes 3-4 meaningful narrative choices (race, archetype, attributes, patron); the system derives culture, starting region, equipment, starting spells, and companion from those choices. The player discovers their culture and backstory through play, not through a pre-game form.

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


## Encounter Roles (Decisions 73-81)

73. **Encounter roles are modifiers on base stat blocks, not separate creature entries.** Reason: the bestiary should contain one canonical entry per creature. Roles (Minion/Standard/Elite/Boss/Named) are a *presentation layer* applied by the encounter builder, not a data layer. This keeps the bestiary clean, avoids stat block proliferation, and means adding a new creature automatically gives the encounter builder five usable variants without additional authoring. Named creatures are exempt — their bespoke stat blocks already define their identity.

74. **Minions lose all active abilities.** Reason: Minions exist to create threat through numbers with minimal tactical overhead. If Minions have special abilities, the DM must track ability uses across potentially 6-10 creatures per fight — that's too much state for the rules engine and too much narration for a voice-first game. Minions attack. That's it. Their danger comes from Pack Tactics, flanking, and action economy pressure.

75. **Elites get enhanced existing abilities; Bosses get one new signature ability.** Reason: the hybrid model. Elites are recognizably the same creature, just better — the player's knowledge of the base creature transfers. Bosses are tactically distinct — the signature forces the player to adapt. Authoring new abilities per creature per role would be unsustainable at scale; limiting it to one signature per Boss keeps the authoring burden manageable while ensuring Boss fights feel unique.

76. **Boss legendary action is 1 per round, not per turn.** Reason: in a solo-player game with one companion, "per turn" and "per round" are nearly equivalent (only 2-3 turns per round). 1 per round gives the Boss one extra action — enough to create tactical pressure without overwhelming a single player. In multiplayer (Phase 2+), this may need re-evaluation as more turns per round dilute the Boss's relative action economy.

77. **Harvesting is auto-success if skill requirement is met.** Reason: the gate is investment (Training in the right skill), not luck. A player who invested in Survival: Expert should reliably harvest Expert-tier materials. Adding a roll creates a double gate — you need the skill AND a good roll — which punishes the player's investment rather than rewarding it. The drama is in the fight, not the looting.

78. **Material sell values are always lower than crafting value.** Reason: the economy must incentivize the crafting loop. If selling raw materials is more profitable than crafting, the Artificer archetype loses economic identity and the async crafting system becomes irrelevant. Sell values are the floor; crafting is the multiplier. This also creates natural market dynamics — players with Crafting skill extract more value from the same materials.

79. **Minions never drop currency.** Reason: currency drops from Minions would create a farming exploit — throw yourself at the largest possible Minion swarms for maximum coin per encounter. By restricting currency to Standard and above, the economy rewards *harder* fights, not *bigger* ones. This aligns with the GDD's philosophy that engagement, not grind, drives income.

80. **Boss bonus loot is context-driven, not creature-driven.** Reason: a bandit captain in a mountain pass should drop something different from a bandit captain in a harbor. Context loot connects the encounter to the story — a letter, a key, a badge, a map fragment. This gives the DM (or the quest author) a loot slot that serves narrative, not just economy. It also makes Boss encounters memorable beyond their mechanics.

81. **The encounter budget system uses fractional points with Minions at 0.5.** Reason: Minions should be cheap enough to field in large numbers (that's their purpose) but not free (that would create infinite swarms). At 0.5, a Standard encounter budget of 3.0 supports up to 6 Minions — enough for a cinematic swarm — while a tighter budget of 2.0 limits Minion groups to 4, keeping early-game encounters manageable.

---

## Faction Reputation Pricing (Decisions 82-86)

82. **Faction price modifiers are smaller than disposition modifiers.** Reason: disposition represents a personal relationship — a merchant who trusts you gives you a better deal because they know and like you. Faction reputation is institutional policy — the merchant follows the rules their organization sets. Personal relationships should always be more impactful than bureaucratic standing because this is a game about human connection, not organizational management. The multiplicative stacking ensures both matter without either dominating.

83. **Economic activity grants reputation only through meaningful contributions, not purchase volume.** Reason: if buying rations shifted reputation, the system collapses into "spend money to get discounts to spend less money" — a pure economic loop with no narrative content. By limiting reputation-granting actions to meaningful contributions (selling rare materials, donating, fulfilling bounties), the system ties economic behavior to story. You earn the Thornwatch's respect by supplying what they need, not by shopping at their stores.

84. **Economic reputation gains cap at Trusted (+15), not Honored (+25).** Reason: Honored represents deep narrative commitment — command authority, classified intelligence, the faction treats you as one of their own. That level of trust cannot be purchased. It requires quest completion, difficult choices, and demonstrated loyalty. Allowing economic activity to reach Honored would cheapen the narrative weight of the highest tier and create a pay-to-win dynamic. The cap at Trusted means economic contributions *supplement* the relationship but can never *replace* it.

85. **Faction-exclusive items use a tiered access framework, not exhaustive catalogs.** Reason: exhaustive per-faction catalogs would be enormous and would lock content design too early. The framework defines the *pattern* (what each tier unlocks categorically) while leaving specific items to faction content authoring. This means new factions can be added without modifying the economy system — they just populate their tier slots. The Thornwatch and Merchant Guild examples demonstrate the pattern; other factions follow the same structure.

86. **Detection gates negative reputation from economic activity.** Reason: if every negative economic action automatically triggered reputation loss, stealth-oriented archetypes (Spy, Rogue) would be disproportionately punished for their core gameplay loop. By gating negative consequences behind detection, the system creates risk-reward tension: selling stolen Thornwatch goods is profitable but dangerous. Getting caught is devastating. This makes the Spy's Deception skill economically valuable — they can play both sides if they're skilled enough — while ensuring consequences exist for those who aren't.

---

## Merchant Inventory & Restock (Decisions 87-95)

87. **Three-tier stock model balances frictionless basics with meaningful scarcity.** Reason: an inventory system where every item can deplete creates frustration without gameplay value (running out of torches isn't a meaningful choice — it's just annoying). An inventory system where nothing depletes destroys the geography of trade. The three-tier model resolves this: trivial supplies are always available, quality goods can run out (creating real choices), and unique items create destination-driven gameplay. This mirrors real-world retail patterns players intuitively understand.

88. **Restock cadence is once per in-game day at dawn.** Reason: predictability matters. Players need to be able to plan around restock — "we'll rest in town tonight, the smith will have new stock in the morning." Probabilistic per-tick restock would create unpredictable patterns that players can't reason about. Daily cycles also give the world a natural rhythm and integrate cleanly with the existing time-driven simulation layer (no new infrastructure needed).

89. **Merchant gold pools are finite and scale with settlement size.** Reason: this creates economic geography. Small settlements can't afford big-ticket items, which drives players toward cities for high-value sales. Without this, settlement size becomes economically irrelevant — every shop is an infinite gold sink. The finite pool also creates interesting decisions: "do I sell the masterwork blade to the village smith for what he can afford, or carry it to the city for full price?" This is real gameplay. The implementation cost is modest — each merchant tracks one number that resets daily.

90. **Merchant gold pools restock daily at dawn, parallel to inventory.** Reason: consistency. Players already learn "restock happens at dawn" for inventory; extending the same rule to gold means one mental model, not two. This also prevents the edge case where a merchant has plenty of inventory but no gold to buy from the player (or vice versa) for asymmetric durations.

91. **Buyback limits prevent farming exploits.** Reason: without limits, a player could clear a bandit camp and unload twelve short swords on the village blacksmith for full price — far more than the in-world economy of a village should support. The buyback limit (3 same items per day for common weapons) reflects the reality that a village smith doesn't need twelve short swords. Beyond the limit, the merchant offers reduced prices, providing economic friction without hard refusal. This is an exploit-prevention mechanism that emerges naturally from the worldbuilding.

92. **Always-stocked items are limited to truly trivial supplies.** Reason: every item moved into Tier 1 (infinite stock) is one less point of friction in the economy. The line is drawn at items where running out creates frustration without gameplay (torches, rations). Quality items, even common ones (healing potions, basic weapons), are Tier 2 because their availability creates meaningful choices. The catalog of Tier 1 items is intentionally short and unlikely to grow.

93. **Consignment is a Friendly+ relationship feature, not a default option.** Reason: consignment requires the merchant to trust the player will return for payment, and trust the player won't dispute the eventual sale price. That trust requires existing relationship investment. Making consignment available only at Friendly+ disposition reinforces the relationship-investment loop (merchant likes you → unlocks consignment → enables high-value sales in small settlements → strengthens relationship). It also creates narrative content — "I'll hold onto this for you, Marn. Bring me your business when you can. We'll work out a fair price when it sells."

94. **Shop entry narration uses 3-4 highlights, not full inventory listing.** Reason: voice-first design. A complete inventory recitation would take 30+ seconds and overwhelm the player with information they'll forget. Highlights focus the player's attention on what's interesting (Tier 2 changes, Tier 3 presence) and lets them ask specific questions about the rest. This mirrors real shopping — you walk in, scan the highlights, ask about specifics.

95. **Settlement personality stacks multiplicatively on size.** Reason: the personality system already exists (`game_mechanics_npcs.md`) — leveraging it for inventory creates richer worldbuilding without new infrastructure. A Struggling Village feels meaningfully different from a Prosperous Village even though both are Villages. The multiplicative stacking ensures personality matters at every settlement size — a Struggling City is still richer than a Struggling Village, but both feel poorer than their Prosperous counterparts.

---

## Supply & Demand Engine (Decisions 96-104)

96. **Hard price bounds clamp final prices to [0.5×, 3.0×] of base.** Reason: without bounds, multiplicative stacking can produce pathological prices (5+ events stacked = 7-10× base, breaks player ability to transact). The 0.5× floor preserves crafting/trading economics; the 3.0× ceiling preserves player ability to buy critical items even in the worst crises. Bounds are a safety net, not a target — most events stay well within them.

97. **Event modifiers stack multiplicatively, not additively.** Reason: events represent independent market pressures. A Hollow incursion creates demand pressure; a trade route disruption creates supply pressure; a refugee influx adds population pressure. All three are real and all three should compound. Additive stacking would understate the impact of confluence — three separate crises wouldn't feel like a real disaster. Multiplicative stacking with a 3.0× clamp captures both the compounding and the protective ceiling.

98. **Item granularity is tag-based, not category-based.** Reason: the item schema already supports tags. A Hollow incursion specifically demands `anti-hollow` items, not all weapons — Hollow-Ward Amulets and blessed weapons see massive demand spikes, while a regular dagger is barely affected. Tag-based targeting also lets us layer events naturally (Hollow Incursion affects `anti-hollow` and `healing` and `divine`, each at different multipliers) without artificial categorization. Tags also handle multi-attribute items naturally — a blessed sword is both `weapons` and `divine`, and gets the highest applicable event modifier.

99. **Tag matching is once-per-event, not stacking across tags within an event.** Reason: if a Hollow Incursion event boosts both `anti-hollow` (2.0×) and `divine` (1.4×), and an item has both tags, applying both would yield 2.8× — which over-counts the same demand pressure. Instead, the event's strongest applicable tag wins for that item. This ensures multiple events compound (independent pressures), but redundant tag effects within a single event don't double-count.

100. **Events have three phases (Active / Recovery / Resolved) with linear recovery decay.** Reason: binary on-off events create jarring "prices snap to normal the moment you kill the boss" moments. Real economies recover gradually — supply chains rebuild, fear subsides, surpluses get absorbed. The recovery phase makes the world feel responsive but realistic. Linear decay is mathematically simple and produces intuitive narration ("prices are coming back down"). The three-phase model adds minimal state (one extra field per event instance) for significant narrative gain.

101. **Recovery duration is half active duration, minimum 2 in-game days.** Reason: recovery shouldn't be instantaneous (defeats the purpose) or longer than the original crisis (would feel disproportionate). Half-duration with a 2-day floor produces good results across the range — a 14-day Hollow incursion has a 7-day recovery; a 1-day festival has a 2-day recovery. Players experience meaningful but bounded recovery periods.

102. **Player intervention can resolve events early; time-based resolution is the fallback.** Reason: agency matters. The player should be able to *cause* recovery by acting (defeating the Hollow boss, clearing the bandit camp, completing the plague-cure quest). But events shouldn't be permanent if the player ignores them — the world keeps moving, threats burn out or get resolved by NPC factions over time. Active duration is a maximum; resolution conditions can end events sooner. This balances agency with world-as-living-system.

103. **DM narrates causes; character sheet shows numbers.** Reason: voice-first design. The DM never says "healing potions are 1.95× their normal price due to active Hollow Incursion (1.5×) and Disease Outbreak (1.3×) events." The DM says "the alchemists are running low — the incursion's been brutal on supplies." The character sheet shows the actual price (39 sp instead of 25 sp). Players learn to read the world's narrative state and connect it to mechanical impact, which is a core gameplay loop in a voice-first RPG.

104. **Event narration should reference player intervention for resolved events.** Reason: making the player's actions narratively visible is critical for agency. When prices come back down because the player solved the underlying crisis, the merchant should mention it. "Heard about what you did at the breach — caravans are running again." This creates the closed loop: player acts → world changes → merchant notices → player feels their impact. Without this narration, recovery feels like passive time-passing rather than earned consequence.

---

## Gold Sinks & Economy Balance (Decisions 105-113)

105. **Gold sinks fall into eight categories with distinct design intents.** Reason: the categorization (Maintenance/Subsistence/Combat/Progression/Crafting/Service/Lifestyle/Endgame) ensures each sink serves a clear purpose and that the sink ecosystem is balanced. Without categorization, sinks tend to cluster in one area (combat consumables, for example) leaving other player activities economically inert. The category framework also makes gap analysis easier — if no Lifestyle sinks exist, that's a clear design issue.

106. **All forced sinks must have player-agency mitigations.** Reason: forced sinks the player can't avoid become punitive taxation. Item repair is forced (durability is real) but mitigated by Crafting skill (self-repair). Death is forced (combat happens) but mitigated by archetype choice (divine archetypes self-resurrect) and gameplay (avoid dying). Subsistence is forced (you must rest) but mitigated by camping (free, riskier). Every "forced" sink in the ledger has at least one mitigation path, preserving player choice.

107. **Mortaen's death costs are non-monetary; gold sinks for death come from spell components and NPC services.** Reason: the death system's narrative weight comes from attribute loss, item loss, and memory fragments — things the player can't simply spend gold to recover. Making death a *gold* sink would convert a profound narrative system into an economic transaction. Keep them separate: Mortaen's domain extracts narrative cost; resurrection magic extracts gold cost. Both can apply to the same death (you spend 50 gc on Revivify *and* still see Mortaen if it doesn't take effect in time).

108. **Endgame sinks must absorb wealth at high magnitudes (1,000+ sp).** Reason: at high levels, players accumulate wealth faster than mid-game sinks can absorb. Without endgame sinks, gold becomes meaningless to high-level players. Resurrection services (1,000+ sp), legendary repair (200+ sp), faction investments (100+ sp minimum), and property maintenance (Phase 2+) all serve as wealth absorbers for the post-mid-game economy. The 3.0× price ceiling from the supply/demand engine ensures these costs don't escape into pathological territory.

109. **Lifestyle sinks reward wealth without granting mechanical advantage.** Reason: the player should be able to spend money on status, identity, and roleplay without affecting combat balance. Fine clothing, jewelry, and exotic goods absorb wealth from rich players who don't need more combat gear. The reward is narrative — NPCs notice the player is well-dressed, the DM describes their entrance with weight, certain social interactions become easier. This separates "I have the best gear" (combat power) from "I am rich" (status and roleplay), which lets both be progression axes without one dominating.

110. **Travel tolls must always have a free alternative.** Reason: tolls are a useful sink and worldbuilding tool, but pure taxation violates the design philosophy. Every toll point in the world should have an alternative: longer routes, faction relationship that waives the toll, or a skill check (Survival, Stealth) to bypass. This preserves player agency — the toll becomes "the convenient option" rather than "the only option."

111. **Bribery is a real social mechanic, not just a thematic option.** Reason: in a world with corrupt officials, desperate guards, and grey morality, players should be able to use gold to influence outcomes. The skill-check alternative remains (Persuasion, Deception, Intimidation), but bribery offers a wealth-conversion path: spend money to skip a check. This makes gold relevant to social play, not just combat/crafting/services. The refusal mechanic (NPC declines, minor disposition penalty) ensures bribery isn't risk-free — corrupt NPCs accept; honorable ones don't.

112. **Companion equipment maintenance is half player gear cost.** Reason: companions in combat take damage and use equipment, but charging full repair cost would double the maintenance burden on the player. Halving it acknowledges that companions use simpler gear (Kael's longsword is functional, not masterwork) while still creating a real sink. This also opens companion gear upgrades as a meaningful gold sink — the player can invest in better companion equipment for tactical benefit.

113. **Sink event logging is required infrastructure for inflation control.** Reason: without per-sink tracking, balance analysis is impossible. The aggregated sink data feeds inflation control (Decisions 114-121), live balance monitoring, and narrative systems (god-agent attention to player spending patterns). The implementation cost is minor (one log entry per sink event); the analytical value is significant.

---

## Inflation Targets & Controls (Decisions 114-121)

114. **Inflation control is a Phase 2+ primary concern; Phase 1 implements the data infrastructure only.** Reason: in a single-player game, "inflation" is just per-character economic balance, which is handled by the wealth-by-level curves and per-session targets. Building a full automated inflation control system for single-player is over-engineering. But the *data infrastructure* (per-event logging, aggregate metrics) must exist in Phase 1 because retrofitting it into a live multiplayer service is enormously expensive. Build the foundation now, activate the controls later.

115. **The wealth-by-level curve has three phases — steep growth (1-9), moderate growth (10-15), plateau (16-20).** Reason: players need to feel wealth accumulation early to be invested in the economy. Mid-game requires harder choices as sinks scale up. Endgame requires sinks that absorb excess wealth so gold remains meaningful. The three-phase curve captures all three needs. Specific numbers will need playtesting validation, but the curve shape is the design intent.

116. **Target per-session balance is net positive 50-150 sp.** Reason: this produces a satisfying wealth growth experience without trivializing the economy. Net negative sessions feel punitive; net positive 500+ sessions feel like the system is breaking. The 50-150 sp range gives the player visible progression while preserving meaningful spending decisions. Outliers in either direction are acceptable but shouldn't be the norm.

117. **Long-term faucet/sink ratio target is 1.0 with controlled variance.** Reason: zero growth (perfect 1.0) would mean players never feel they're getting richer over time, which kills the sense of progression. Runaway growth (significantly above 1.0) creates classic MMO inflation. The target ratio of 1.0 with widening acceptable variance over shorter windows (1.4 at 24h, 1.05 at 90d) acknowledges that short-term swings are normal while long-term drift is the real problem.

118. **God-agent economic intervention is the primary Phase 2+ control mechanism.** Reason: macroeconomic adjustments expressed as authored content (god actions, seasonal events) are narratively elegant and player-visible. Players experience the world responding to their collective behavior, not "the developers nerfed quest rewards." This converts a backend balance problem into a worldbuilding feature. Manual parameter tuning remains as a fallback for cases the narrative systems can't handle, but it's the lever of last resort.

119. **Seasonal economic events are authored content with calendar triggers, not procedural.** Reason: seasonal events should feel cultural and intentional — Lantern Festival is a real festival that real NPCs celebrate, not a random discount event. Procedural generation would make seasons feel artificial. Authored content gives each season a distinct character that players can learn, anticipate, and engage with. The cost is that seasonal content must be authored and rotated, but this is a content-team responsibility, not engineering complexity.

120. **The player must never see the inflation control system directly.** Reason: economic dashboards, "inflation indicators," or any UI that exposes the macro-economic state would break the worldbuilding. The player should experience economic shifts as Mortaen's tribute demands, Aelindra's blessings, the approach of Forge Day, the deepening of the Long Dark — narrative phenomena, not statistical readouts. This is voice-first design extended to the economy: the world responds, the DM narrates, the player feels.

121. **Wealth variance from player choice is not a bug.** Reason: hoarders, spenders, and crafters will naturally land at different wealth levels. The curve targets are *typical experience targets*, not constraints. The economy should produce different experiences for different play styles — that's a feature. Inflation controls target *aggregate* drift, not individual deviation. A player choosing to hoard wealth shouldn't be penalized; they just have nothing exciting to spend it on until endgame sinks unlock.

---

## Player-to-Player Trade (Decisions 122-128)

122. **Player-to-player trade is Phase 2+ deferred; Phase 1 implements supporting infrastructure only.** Reason: Phase 1 is single-player; P2P trade is meaningless without other players. But the architectural foundations (item provenance, atomic transaction primitives, settlement-aware APIs, transaction logging) must exist in Phase 1 to avoid expensive retrofitting at Phase 2 launch. Build the bones now, the muscle later.

123. **P2P trade must obey the same world rules as merchant trade.** Reason: a parallel P2P economy that bypasses faction reputation, supply/demand, and gold sinks would undermine the entire economic design. P2P trade in Thornwatch territory is witnessed by Thornwatch authority. P2P trade of faction-restricted items carries reputation risk. P2P trade includes its own sinks (fees, taxes, transport). The world's economic rules apply uniformly regardless of who the other party is.

124. **P2P trade is voice-first; no menu-driven trade interfaces.** Reason: this is the core design pillar of the game extended consistently to trade. Players negotiate verbally, the DM facilitates, the character sheet shows current state. Auction houses (if they exist at all) are queried verbally and listings are placed verbally with a faction agent — they're not menu interfaces.

125. **Item provenance must be tracked from Phase 1.** Reason: provenance enables audit, anti-fraud, narrative ("where did you get this?"), and stolen-goods enforcement. Adding provenance retroactively to a multiplayer service requires migrating every existing item — vastly more expensive than building it in from the start. Phase 1 logs the trail; Phase 2+ uses it.

126. **Atomic transaction primitives are required infrastructure.** Reason: in Phase 1 they prevent edge cases (inventory full mid-transaction, partial loot drops). In Phase 2+ they prevent fraud and griefing. The cost is small — design the API once with atomicity in mind. The retrofit cost is enormous.

127. **Auction house design is genuinely uncertain and worth real debate at Phase 2 planning.** Reason: auction houses are a common MMO feature but they fundamentally reshape economies in ways that may conflict with our design goals (regional economic identity, voice-first interaction, narrative-rich trade). The decision shouldn't be made now. The constraints document captures the tradeoffs; the actual choice happens at Phase 2 design time with full context.

128. **Direct trade in non-faction territory carries no fee.** Reason: face-to-face trade between players adventuring together (a party splitting loot, friends gifting items) should be the most frictionless interaction. Imposing fees on every social trade would discourage the cooperative gameplay we want to enable. Faction territory adds taxes; lawless territory has none. This also creates a smuggling/frontier-market vector for legitimate gameplay.
