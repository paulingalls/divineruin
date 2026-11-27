# Changelog

## 0.85.2

Documented the behavior of all 87 catalog spells. The spell ledger identifies 11 engine-resolved spells, 4 narration-owned spells and 72 spells with unfinished mechanics, each linked to its Phase 14 follow-up.

Release steps: none.

## 0.85.1

The engine-completeness milestone now records Guardian Intercept and druid/warden Bark Skin as built (v0.85.0).

Release steps: none.

## 0.85.0

A guardian can spend 3 Stamina to take a hit's damage for an ally within 5 ft.
The guardian's own reductions apply, and the struck ally still gets the hit's
non-damage effects. One guardian can Intercept each hit. Shield wear and broken
concentration follow whoever took the damage.

Druids and wardens can use Bark Skin to turn a narrow hit into a miss. It adds
2 AC against the triggering attack and until the end of the round. A natural 20
still hits.

Aelora's guardians regain up to 2 Stamina when Intercept takes damage for an
ally, and her wardens regain the same when Bark Skin applies. Her artificers,
bards and diplomats gain +1 from Common Bond on live Crafting checks, recipe
experiments and newly started crafting projects, and it stacks with Craft
Blessing. Projects queued before this release resolve without it.

Still pending, and recorded in docs/milestones/REMAINING.md and
14_engine_completeness.md:
- Guardian upgrades: Shield Mastery's 1d8 reduction, Warden-Commander's 10 ft
  range, and the Thornridge's Stand 15 ft override and Last Wall.
- Bark Skin: the Primal Bark Skin spell (no reaction path offers it) and the
  Thornveld Guardian Shield's free cast.

Release steps:
- Run these after the existing deploy (scripts/deploy-up.sh), from the deployed
  repository root with its production environment loaded:
  `SEED_PRODUCTION=1 bun run seed`. It is unpaid, writes production content
  (patron catalog, abilities, spells) and invalidates catalog caches.
- Then restart the agent and the worker using the existing deployment procedure,
  so they reload the patron catalog.

## 0.84.2

Updated the agent's LiveKit, OpenAI, Pydantic, and Ruff dependencies and the server's LiveKit SDK and jose dependencies.

Release steps: none.

## 0.84.1

Track the remaining game engine, selling and content work with runnable milestone measures. Reconcile previously shipped capabilities, phase totals and the design index.

Release steps: none.

## 0.84.0

Valdris judges. Turn Undead/Hollow is now a real spell in combat. Nearby undead and Hollow creatures save or flee, and from level 5 it destroys weakened creatures that fail. Valdris clerics and oracles turn at DC +1.

A player or companion can yield in combat. Measured Reprisal gives a Valdris warrior +1 damage against any foe that attacks a yielded ally.

Temple Row and the Accord guild hall are sanctuaries. When enemies start a fight there, a Valdris marshal gets +1 initiative.

In Millhaven, Elder Yanna accuses the Cult Cell's leader and one cultist. While she is present, a Valdris guardian gets +1 AC against the accused.

The paladin Oath of Justice and Zhael's Promised Hour are designed and approved. They will be built next.

Release steps:
- After deploy, on the deployment host, run `bun run seed`. It writes the production database, costs nothing, and loads the changed locations, encounter templates, gods and spells content.

## 0.83.1

Seeding a remote database now requires `SEED_PRODUCTION=1` for production content or `SEED_PRODUCTION=0` to include fixtures. Local seeding still defaults to fixtures.

Release steps: none.

## 0.83.0

Syrath’s clerics gain +1 Religion when interpreting concealed devotional symbols. Syrath’s paladins gain +1 History when identifying oaths whose patron’s name was erased. Mortaen’s diplomats gain +1 Persuasion when negotiating the return of a body for burial, on both skill and social checks. Zhael’s artificers gain +1 to any skill check to repair a clock or timing mechanism. Zhael’s seekers gain +1 Investigation when comparing accounts of the same foretold event.

Veythar’s rogues and spies gain +1 Investigation when searching for hidden information, including when they investigate a Still illusion or reroll a discovery with Lorekeeper’s Insight.

Veythar’s paladins gain +1 Religion when interpreting an ancient oath. His oracles gain +1 Arcana when interpreting a remembered vision. Kaelen’s clerics gain +1 Religion when conducting a fallen soldier’s funeral rites. His oracles gain +1 History when interpreting a martial omen.

Release steps:

- Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host. The migrate job reseeds production gods content before the server, agent and worker are recreated, and the restart refreshes the check schema's tag list. This writes to production and makes no paid provider calls.

## 0.82.1

Seven Valdris archetypes gain +1 on skill checks when the DM names a matching situation. Rogues and spies also gain the bonus on social Deception for a just cause. The patron query shows each follower’s available context, and the check result names the clause it applied.

Release steps:
- After deploying the updated code and content, run `SEED_PRODUCTION=1 bun run seed` from the deployed repository root with the production database and cache configured. The command is unpaid and writes to production. Complete the seed before starting gameplay services with this release.
- If a gameplay agent is already running the deployed release, restart it after the seed to reload patron content and the check context enum. On the production Compose host, run `DEPLOY_ENV_FILE=/absolute/private/production.env DEPLOY_HTTP_PORT=3001 COMPOSE_PROJECT_NAME=divineruin docker compose -f deploy/compose.yml restart agent` from the deployed repository root with the actual deployment settings. The command is unpaid and restarts the production agent.

## 0.82.0

Aelora's clerics gain +1 Religion when blessing a shared meal. Her paladins gain +1 Persuasion when negotiating a community's shared duties. The DM can discover both bonuses through the patron query and see them on settled rolls.

Aelora’s oracles gain +1 Insight when interpreting a household omen, stacking with Hearthkeeper’s Bond when an ally is present. Aelora’s rogues gain +1 Persuasion on commerce checks, including negotiations with merchants. Thyra’s paladins gain +1 Religion when honoring a sacred grove, and her oracles gain +1 Nature when interpreting a seasonal omen.

Nythera’s wardens gain +1 Survival to find shelter on unfamiliar coasts. Her diplomats gain +1 Persuasion to seek peaceful passage through unfamiliar ports, and her artificers gain +1 on any check to repair a vessel during a journey.

Orenthel’s artificers gain +1 on any check to repair equipment for a damaged sanctuary. His wardens gain +1 Nature to restore a blighted grove, and his diplomats gain +1 Persuasion to negotiate care for wounded enemies.

The DM passes a `synergy_context` tag on a skill or social check when the narrated moment matches a clause the player holds, and finds the player's tags through the patron query. A tag the player does not hold grants nothing and is reported as not applying.

Release steps:

- Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host. The migrate job reseeds production gods content before the server, agent and worker are recreated. This writes to production and makes no paid provider calls.

## 0.81.5

Commit hooks generate Proof declarations faster and check the environment templates directly. Cross-language server purification and inventory-taint tests run at story land.

Release steps: none.

## 0.81.4

Require combat mirrors to rewind with their database rows or block the rewind, with both stores exercised in Verify. Require negative-control evidence to apply the real effect at the excluded site and change the asserted outcome.

Release steps: none.

## 0.81.3

Acceptance tests can rebuild database and Redis clients left bound to an earlier test's event loop. The speaker recap test isolates Redis outcome completion.

Release steps: none.

## 0.81.2

Combat action economy (Phase 4) and Hollow creatures (Phase 7 M7.3) are recorded as met goals.

Release steps: none.

## 0.81.1

Reviewers now require a fault injection's red to come from the game's own output (a receipt, row, packet or event), never from a count the test builds for itself. The sprint hollow-finish retro found the Architect benchmark's rider probe checking its own report.

Release steps: none.

## 0.81.0

The Hollowing now gets worse if it goes untreated, and it can be cured:
- An untreated Hollowed character worsens from Stage 1 to Stage 2 at a long rest. At Stage 2 the DM starts describing sounds and sights only that character notices. Each one is woven in once, at a quiet moment.
- At Stage 3, every untreated long rest drains a point of Wisdom, never below 1. Focus and Stamina limits follow the new Wisdom.
- Greater Restoration lifts the Hollowing at any stage and gives back the Wisdom it took, up to 20. Death clears it the same way. With no Hollowing on the target, it removes Charmed or Petrified instead, including the Still's charm.

Magic weapons now count against the Hollowed Knight. An equipped magical weapon gets past its resistance to nonmagical damage on basic attacks, martial techniques and opportunity strikes, even after a reload.

The artificer's Infuse Item makes its equipped plain weapon magical, with +1 to attack and damage, until the next long rest. At level 10 the bonus is +2 and Arcane Armory keeps up to three weapons infused, so a fourth replaces the oldest.

The Choir now waits in its own corner of the deep Ashmark, where a party of the right level can find it, and fights there to the end with its whole kit. Silence stops its abilities for exactly one of its turns.

The Architect now has 205 HP, up from 175 (the spec is 300). The reference party takes its strongest electives, and at 205 HP it beats the Architect 12 times in 20.

Release steps: `bun run migrate` then `bun run seed`, after deploy, on the target stack, not paid. Migration 068 adds the Hollowed hallucinations catalog, and content/hollowed_hallucinations.json, creatures.json, archetype_abilities.json, encounter_templates.json, locations.json and scenes.json changed.

## 0.80.2

Native iOS verification now removes Xcode build data when it deletes a temporary checkout and clears build data from earlier runs whose workspaces are gone.

Release steps: none.

## 0.80.1

Proof now rejects undeclared tests in whole-directory Bun tasks and keys the five previously omitted tests, so edits invalidate stale passes.

Release steps: none.

## 0.80.0

Healers and skirmishers get more from their gods.

- A bard's Song of Rest now really heals: on a short rest, the bard sings and every resting ally who can hear regains an extra 1d8 HP. The bard pays their technique's Focus cost.
- Orenthel's bards heal 1d6 more with Song of Rest, and can turn Inspire into an instant heal (`orenthel_inspire_heal`) instead of a bonus die.
- Orenthel's druids and beastcallers draw 1 Resonance out of the player their Healing Touch heals.
- Once per fight, a Nythera skirmisher or rogue can make one move that provokes no opportunity attacks.
- Veythar's clerics are trained in Arcana.
- Mortaen's Threshold Shield now says what it does: +1 AC while another party member is down at 0 HP.

Release steps: none.

## 0.79.0

Three patron synergies now work in combat. Sheltering Light gives a standing Orenthel guardian +1 AC against attacks while a standing ally below half HP is within 5 feet. Dawnward Strike gives an Orenthel warrior's hits 1 extra damage against Hollow and undead foes while another standing ally in the fight is below half HP. Saltwind Casting gives a Nythera mage +1 on spell attack rolls during their first stay at any Sunward Coast location. Attack receipts name each bonus when it applies.

Release steps:

- After deploy, run `SEED_PRODUCTION=1 bun run seed` from the deployed checkout with its production environment configured. This writes production content and uses no paid providers.

## 0.78.1

Proof uses measured agent acceptance coverage to pick the tests that check shared Python changes.

Release steps: After merging, run `bash scripts/super-test-install.sh` from updated develop on the Mac Mini as the scheduler owner. The command is unpaid and writes no production data. The owner needs existing GitHub CLI authentication for weekly map PRs.

The measured representatives would have missed #757. On merge `98ffe31a`, the selected concealed-target reader `test_architect_balance` passed. `test_vanish` and `test_martial_core_resume` failed.

## 0.78.0

Enemies now carry their rolled loot from the start of a fight and keep it across saves; victory awards what defeated enemies still carry. Rogues who learn Quick Fingers can steal, plant or swap a real item just before a melee strike. A failed attempt leaves the foe wary until the round ends, so a second attempt fails and its first attack on that rogue has advantage. Unravel Fate refuses a rewind that would split a Quick Fingers transfer between a fighter's inventory and an enemy's pocket.

Release steps:

- After deploy, run `SEED_PRODUCTION=1 bun run seed` from the deployed checkout with its production environment configured. This writes production content and uses no paid providers.

## 0.77.0

The Marshal's five orders now work as rules, not just narration. Direct Strike gives an ally advantage and an extra 1d4 on their next attack against the named foe. Coordinated Assault gives two allies advantage, and if both hit the same foe, each adds 1d6. Sacrifice Play costs the ally 2d6 at once, and their next attack automatically hits and crits. Reposition moves an ally up to 15 feet at once, without provoking reactions. Field Medic Order lets a player ally attack and drink or apply a healing item in the same phase. An unused order lasts through the end of the following round and never carries into the next fight.

Fixes: an ally who does not declare an action still makes their Corruption Field and Choir aura saves at the start of their turn. Acceptance test teardown now reports LiveKit cleanup errors instead of hiding them, and still runs every cleanup step.

Release steps: none.

## 0.76.0

Every warrior and rogue technique except Quick Fingers now works in a fight:
- Iron Stance plants the warrior until its next turn. It cannot be pushed, it saves with advantage (death saves too), and it takes half damage from everything. Petrified now halves damage the same way.
- Vanish hides a rogue on the spot, with no Stealth check.
- Hidden players can no longer be targeted. No foe can pick a concealed player for an attack, an automatic hit or a single-target save, whether they hid with Hide, the Shadow Veil or Vanish. A strike already aimed at them is lost, unless its die was already rolled. Areas and auras still reach them. Making an attack, spell attacks included, reveals them.
- Smoke Bomb leaves a 10-foot cloud where it was thrown. Until the rogue's next turn, any attack into or out of the cloud has disadvantage.
- Shadow Step slips the rogue, unseen and drawing no opportunity attacks, to a spot beside a wall, a structure or smoke, and leaves it hidden.

The Marshal's War Cry frightens foes within 30 feet that fail a Wisdom save. It also gives every other ally who can hear it +1 to attacks until the marshal's next turn, even with no foe in range.

The Architect now has 175 HP, up from 154 (the spec is 300). At 175 HP the reference party still beats it 13 times in 20.

Release steps: `bun run seed` after deploy (content/archetype_abilities.json, content/mentor_variants.json and content/creatures.json changed).

## 0.75.0

Every catalog weapon now has a category, range and kind, and both catalog loaders validate weapon profiles and archetype proficiency. A character can equip a weapon they are not trained with, and the DM warns them when they do. Their attacks with it roll at disadvantage, which cancels with advantage as usual. The proficiency bonus still applies. Artificers, spies and bards are now proficient with their starting Warhammer, Rapier and Lute, so every starting kit is proficient.

Release steps:

- Set `SEED_PRODUCTION=1` in the deployment seed environment and run `bun run seed` from the repository root after deploying the updated seed code and before restarting the catalog consumers. This unpaid command writes the production catalog.

## 0.74.0

Aelora's Exalted followers can light Hearthfire once a session in a fight. It is a fixed 15 ft hearth that lasts 3 rounds. At each round's end it heals every ally inside by 1d6 before the round's outcome is decided, so fallen allies inside rise. Allies inside roll their ability saves with advantage (not death saves), including the condition saves at the end of the third round. A foe moving in must pass a Wisdom save or stop at the edge, and Zhael's Fate's Thread can reroll that save. Every patron tier ability now works in play.

Release steps: after deploying the compatible code, run `bun run seed` from the deployed repository root against the target database (gods.json changed). This is an unpaid production write.

## 0.73.0

An Exalted Zhael follower can unravel fate once per session. At the start of a combat round, before anyone has acted, they can ask the DM to undo the round that just ended. Everyone's health, Focus, Stamina, Resonance, concentration, items, positions and patron gifts return to how they stood when that round began, and the party declares again. Unravel Fate's own use is the exception: it stays spent. The follower takes 8 Resonance for bending time, whether or not they cast spells. Each combat round now starts with a saved checkpoint of the fight and the party, which makes this possible.

Release steps: none.

## 0.72.0

Water and mud now slow a fight. Mud on the bandits' slope and shallow water at the mawling crossing cost twice the movement for anyone crossing them. Nythera's Acknowledged followers (Tidewalker) stride through water, mud and the Architect's shifting ground at full speed, while every other kind of slowing ground still costs them as usual.

Release steps: after deploying the compatible code, run `bun run seed` from the deployed repository root against the target database (encounter templates and gods.json changed). This is an unpaid production write.

## 0.71.1

Refresh the app, agent, and browser test dependencies. LiveKit now registers voice event callbacks without triggering Python's asyncio deprecation warning.

Release steps: none.

## 0.71.0

Marshals can now give orders in a fight. Direct Strike, Reposition, Coordinated Assault, Field Medic Order and Sacrifice Play can be declared in combat. The engine checks each order's targets and charges its cost, and the DM narrates what the order does.

A Zhael marshal's order steadies the ally it names (Moment to Rally). Once per encounter, the first ally a Zhael marshal orders, by Interceding Order or any of the five commands, gains +1 on their next saving throw of any kind, death saves included. An unused +1 fades when the fight ends.

Zhael bards and diplomats hear the threads before they speak (Foretold Words). Once per NPC each session, they learn the exact DC of their next social check against that NPC, and that DC holds even if the NPC's mood shifts before they try.

Release steps:
- Apply migration 067_zhael_foretold_words.sql (adds the zhael_foretold_words table) with the normal migrate step, before deploying the agent and server. It is free and writes the production schema.

## 0.70.0

Warriors and rogues can now use ten more of their chosen techniques in a fight:
- Precision Strike and Reckless Assault ride an attack.
- Dirty Trick spoils a foe's next swing.
- Taunt draws a foe's next attack.
- War Cry frightens every foe in earshot that fails its save.
- Crippling Strike halves a foe's speed.
- Exploit Weakness studies a foe for a maximum Sneak Attack.
- Cleaving Blow and Whirlwind strike every foe in reach.
- Blade Flurry strikes three times, and each hit can Sneak Attack.

Retreat now moves the player away from the fight. Foes it leaves get an opportunity attack, unless a rogue Disengages with Cunning Action.

Release steps: `bun run seed` (content/archetype_abilities.json and content/mentor_variants.json changed).

## 0.69.0

Three more patron gifts work in play. An Exalted follower of Veythar can arm Wellspring Echo: their next spell that costs Focus is free, but it stirs the Veil twice as much. Cantrips leave the echo armed. Aelora's Acknowledged followers craft a quarter faster, and a plain success has a one-in-four chance of a blessed bonus property, by voice or through the app. The world now has a season, starting in spring, and Thyra's Acknowledged followers feel it: extra healing in spring (Dawn's Embrace included), extra fire and lightning damage in summer, sharper Insight in autumn, and quieter Stealth in winter.

Release steps:
- After deploy, run `bun run migrate` from the deployed repository root against the production database. It applies 066_world_season, which seeds the world season as spring and is idempotent. This is an unpaid production write.
- Then run `bun run seed` there, so gods.json carries the three active gift rows. This is an unpaid production write.

## 0.68.2

Proof now reruns the relevant acceptance tests when a content catalog they read through a test helper changes.

Release steps: none.

## 0.68.1

Devoted followers of Thyra can raise a Thornwall in combat. The barrier stops movement and melee attacks, tears enemies that run into it, and lets arrows and spells pass through. Foes can hack it apart.

Release steps: After deploy, run `bun run seed` from the deployed repository root against the production database. This is an unpaid production write.

## 0.68.0

Moving in a fight now matters. Walk out of an enemy's reach and it gets a free swing at you as you go. A rogue can avoid that with Cunning Action's Disengage, for 2 stamina. A warrior with Opportunity Strike gets the same chance when an enemy walks away. Either way, the mover stops at the edge of reach and the blow lands there. If it survives, it carries on where it was going.

Winged creatures (the Hollowmoth, the Steppe Razorwing and the Thunderbird) now fly when they close in. A low ceiling forces them onto the ground. Razorwings and Thunderbirds don't provoke when they fly away. A rogue or spy's Slippery now escapes the Architect's Entomb as well as a grapple. A Bandit Captain's Rally heals only the bandits within 30 ft of it. To keep the Architect beatable with opportunity attacks in play, its Construct Slam hits for one point less.

Release steps:
- `bun run seed`, against the deployed database after deploy, to load the changed creature catalog (Rally range, fly speeds, Flyby, Architect Slam damage). It writes production data; it is not paid.

## 0.67.0

Syrath's shadow archetypes and Zhael's oracles gain their patron synergies:

- A Syrath rogue's, spy's or whisper's Shadow Veil now lasts two rounds instead of one. Attacking, casting or the end of combat still ends it early.
- The first strike from Shadow Veil hits harder. A Syrath rogue's Sneak Attack rolls one more d6, and a Syrath spy's or whisper's weapon hit deals +1d6. The die doubles on a critical hit.
- A Zhael oracle can use Fate's Thread twice between long rests. The DM hears how many uses remain.

Release steps: none.

Repair the Choir re-entry regression test so it verifies that old silence exposure is cleared and suppression keeps its original expiry.

Release steps: none.

## 0.66.1

Sprint close now runs the fast lane on the final sprint tree before the acceptance and browser tests. A commit made after the last story landed can no longer reach develop untested (#730).

Release steps: none.

## 0.66.0

The Still and the Architect remember whom their attacks targeted when the party flees and returns. Combat now keeps that history for misses and resisted offensive actions too.

Release steps: none.

Exalted followers of Valdris can call down The Scale's Verdict once per session in combat. Name a foe, and Valdris judges it by what it did this fight. A foe that attacked anyone in the party, even if it missed, takes 4d8 radiant damage and is stunned for a round. Judge an innocent foe and you take 2d8 radiant yourself. Fights now remember who attacked whom, even if you retreat from the Still, the Architect or the Choir and come back.

Release steps: none.

## 0.65.1

The Python test run no longer prints pytest-asyncio's fixture loop-scope deprecation warning. Behaviour is unchanged.

Release steps: none.

## 0.65.0

Three more patron synergies now work in combat. A Mortaen guardian gains +1 AC while another ally lies at 0 HP. A standing Mortaen marshal gives fallen allies, companions included, +1 on death saves; it adds to a Mortaen roller's own +2 and holds through Fate rerolls and flips. A Kaelen bard's Inspire and Mass Inspire give a d6 instead of a d4 on attack rolls. The DM reads each bonus by name in the roll result.

Fixed: a destroyed Hollowed echo was offered a death save, and a natural 20 could bring it back as a living hostile that kept the fight from ending (#719).

Release steps: none.

## 0.64.4

The out-of-combat lock-order concurrency check passes again with player data in its production shape.

Release steps: none.

## 0.64.3

Patron healing effects now resolve for Valdris, Mortaen, and Nythera followers. Nythera followers also get their first-visit bonuses on eligible skill checks.

Release steps: none.

## 0.64.2

The scheduled native checks now open the Iron Resolve HUD with an authenticated character and verify its temporary hit point display.

Release steps: none.

## 0.64.1

The xp config opts into GitHub issues, so bug and debt records keep filing as issues after the xp-plugin 1.7 upgrade.

Release steps: none.

## 0.64.0

The Architect fights with its own architecture. Walls rise and block every line between combatants. The floor opens into pits, the ceiling drops, and the Architect can seal a hero inside a stone chamber (Entomb). It raises a cathedral that turns the room into its domain, and summons constructs. Between turns it takes legendary actions, and it can shrug off a costly save three times a fight. It is tuned against a full level-20 party of four, which beats it in about 12 of 20 fights, typically in 11 rounds.

Warriors and rogues can use their core kit in a fight: Second Wind, Rallying Shout, Devastating Strike, Shield Bash, and Cunning Action to Dash or Hide. Disengage waits for opportunity attacks.

Players can equip the weapons and armour they win, outside combat. Starting gear goes back into the pack instead of vanishing. Characters with elective techniques choose one at level 4 and level 8. Most martial techniques are owned but not yet usable in a fight.

Release steps: after deploy, reseed content on each environment so the four new starting-gear items (mace_common, lute_common, robes_common, shield_wooden) and the Architect's tuned stats are loaded (`bun run seed` from the repo root on a host with that environment's DATABASE_URL; free; writes content rows only).

## 0.63.0

Temporary HP arrives. A player's temporary HP takes damage before their real HP. It lasts until it's used up or they take a long rest, and healing never restores it. A new grant replaces the pool only if it's larger. The HUD shows it beside HP, and the DM hears how much a hit was absorbed.

Aelora's Devoted followers can now cast Community Shield: once per long rest, they grant another present party member temporary HP equal to their level plus their Charisma modifier, in or out of a fight. It's refused, and stays unspent, on themselves, on companions, on a fallen or absent ally, and on an ally who already has as much temporary HP or more.

Fixed: a guest whose Hollowed echo was destroyed in a fight now sees their revived HP on the HUD.

Release steps: reseed content (bun run seed) so gods.json carries the active Community Shield row.

## 0.62.1

Only Diplomats can use De-escalate to talk enemies down in combat.

Release steps: none.

## 0.62.0

Combat now remembers what happens in a fight, and seven patron synergies act on it:

- Mortaen warriors deal 1 extra damage to whatever downed an ally this fight.
- Zhael warriors deal 1 extra damage, once per fight, on a melee hit against a foe they missed earlier.
- Kaelen paladins add 1d6 radiant to weapon hits while living enemies outnumber the living party (2d6 on a critical).
- Zhael guardians gain +1 AC against the first attack aimed at them each fight.
- Zhael clerics heal 1 more HP to an ally who won a death save this round.
- Mortaen druids and wardens regain 2 Focus whenever a creature dies in the fight, up to their maximum. A stabilized companion is not a death, and an ally saved by Death Ward or Dawn's Embrace is not one either.

The DM hears each bonus by name in the attack, heal or phase result. A rolled-back round leaves no record behind.

Release steps: none.

## 0.61.0

Thyra's Exalted followers can now call down Wildmother's Wrath: once per session, in a fight on natural ground, the land itself strikes every foe for 3d8 with no save. The terrain picks the damage: thorns and roots in forests (piercing), razor grass in grassland and farmland (slashing), stone in mountains and underground (bludgeoning), surf on the coast (cold), and miasma in wetlands (poison). Each foe's resistances, vulnerabilities and immunities apply. Allies are never hit. Foes a boss protects, such as the Still's owner and its hidden anchors or the Choir's unexposed core, are spared, and the DM says why. Wrath is refused in villages and cities, outside a fight, and while a reaction or Fate decision is open; a refused Wrath stays unspent.

Release steps: reseed content (bun run seed) so gods.json carries the active Wildmother's Wrath row.

## 0.60.0

Two patrons now keep their followers on their feet.

Mortaen's Death Ward (Acknowledged): the first time each long rest that a Mortaen follower would drop to 0 HP, they stay standing at 1 HP instead. It holds against instant death and a Hollowed rise too. The DM hears "Mortaen decides when you cross."

Orenthel's Dawn's Embrace (Exalted): once per session, the first time an ally of an Orenthel follower drops to 0 HP, at any distance, the ally is caught at half their max HP and stays standing. Companions count; the follower does not. If the ally has Death Ward ready, Death Ward holds first and Dawn's Embrace is kept. With two Orenthel followers present, one of them spends it.

A held enemy blow that one of these will stop no longer announces itself as a killing blow before it lands.

Release steps: reseed content (bun run seed) so gods.json carries the active Death Ward and Dawn's Embrace rows.

## 0.59.0

Mortaen followers at Exalted can use Threshold Walk once per session. In a fight they turn incorporeal until the end of the next round. Slashing, piercing and bludgeoning pass through them, magical or not. Attacks against them have disadvantage, and theirs have advantage. Their weapon strikes deal necrotic. No damage can take them below 1 HP while it lasts. When it ends they return Shaken, with disadvantage on their next attack. If the fight ends first, nothing carries over. Outside a fight the DM narrates it.

Fix: Veilstep and Threshold Walk are now refused, with nothing spent, while any Fate's Thread offer is pending. Before, activating Veilstep then settled the offer and returned the roll's result as if the gift had been used.

Release steps: reseed content (bun run seed) so gods.json carries the active Threshold Walk row.

## 0.58.0

Healing spells now carry patron synergies. Orenthel's clerics and paladins add the better of their Wisdom or Charisma modifier to every heal. Mortaen's clerics restore double to an ally at 0 HP, and Mortaen's paladins restore 1 more. Thyra's clerics heal 1d4 more on natural ground. Nythera's clerics heal 1 more on their first stay in a place. Healing items and Regenerate's later ticks are unchanged. The DM hears each bonus by name.

Release steps: none.

## 0.57.0

Two more patron gifts are live.

Syrath followers at Devoted can Veilstep once per long rest. In a fight they step through shadow to a point up to 60 ft away without using their move, even when restrained. If they had already declared a move that round, Veilstep drops it and the DM asks where they move from the new spot. Outside a fight the DM narrates it.

Nythera followers at Exalted can open Beyond the Horizon once per session. Outside a fight, the whole party steps through to a place the follower has visited before, and the follower gains 5 Resonance. Quest stages reached at the destination advance as they do on foot. It is refused, and nothing is spent, during a fight, for a place they haven't been, for where they already stand, or when the Still's charm holds a party member. The patron query lists the places the gateway can reach.

Release steps: reseed content (bun run seed) so gods.json carries the active Veilstep and Beyond the Horizon rows.

## 0.56.5

Pytest gives each Python test 630 seconds for fixture setup, the test body and teardown. A test that hangs in a sync call or an idle await fails with a timeout traceback, and the run goes on. A hang that keeps the asyncio loop busy can swallow that timeout. At twice the bound, a backstop dumps every thread's stack and ends the process. Under xdist only that worker ends, and the run reports the test as crashed. Collection and session startup run before the timer starts.

Release steps: none.

## 0.56.4

Still and terrain acceptance tests remove their temporary locations and cache entries so later tests can start the game server in the same run.

Release steps: none.

## 0.56.3

Voice acceptance failures now identify the LiveKit object and source location that created a handle the native runtime could not release.

Release steps: none.

## 0.56.2

Veythar gift acceptance checks rolled searches after the guaranteed scout clue at the Greyvale Ruins entrance.

Release steps: none.

## 0.56.1

Local Python test startup refreshes stale catalog rows in the development database while preserving gameplay state.

Release steps: none.

## 0.56.0

Valdris followers at Devoted can now use Mark of Justice. Once per long rest, a follower marks an enemy in the fight. For the rest of that fight, the marked creature takes −2 on saves against that follower's spells and abilities. That includes round-end saves to shake off a condition the follower landed. Saves against anyone else are unchanged, as are saves from the creature's own traits, such as Unholy Fortitude. Two followers can mark the same creature; each penalty counts only against its own follower. The mark ends with the fight. The gift and the mechanics doc now say "for the rest of the encounter" instead of 24 hours. The HUD shows the mark as a condition.

Release steps: reseed content (bun run seed) so gods.json carries the active Mark of Justice row.

## 0.55.1

The Proof key breadth goal check now reads all task keys in seconds and reports the same measurement.

Release steps: none.

## 0.55.0

Torin's missing scout can be found. Search the entrance to the Greyvale Ruins and you turn up Ressa Corrow's scout token, with her name on it. Deeper in, in the inner chamber, what is left of her waits. You can fight her or walk away; she will not follow. Once, in the fight, she says a name: Tam, the younger brother she left in Millhaven. Whatever you choose, tell Torin. He trained her himself, and what he says depends on what you did. She no longer turns up in random fights.

Release steps: none.

## 0.54.2

The scheduled super test now runs all nine native iOS Maestro journeys on the simulator. One journey sends real audio through the BlackHole loopback; the rest, Choir included, are driven by the probe. Native Maestro runs alone in Proof's solo lane, after every other super task.

Release steps: none. (The super host needs BlackHole 2ch installed; the mini already has it.)

## 0.54.1

Guardians now gain Extra Attack at level 10, alongside Shield Mastery: two attacks per round, plus the shield's +1 AC and Intercept. A Kaelen Guardian's two swings each carry Tempered Resolve's +1d4 weapon damage. Guardians already past level 10 keep their current flags; the game is pre-launch, so no data is migrated.

Release steps: none.

## 0.54.0

Healing works. Heal Wounds, Healing Touch, Mass Heal, Prayer of Healing and Regenerate now restore real HP, in combat and out, and the DM is told exactly how much each target regained. Before, a cleric's heal spent Focus and healed nothing. Mass Heal reaches every ally in the fight, or every party member where you stand. Prayer of Healing is for between fights, up to six people. A healed ally who was dying gets back up.

Healing potions, salves and poultices heal when you drink or apply them, on yourself or on an ally. In a fight that takes your turn. Before, using one spent it for nothing. Goodberry fills your pack with five berries that heal 1 HP each.

Regenerate keeps working after its first surge: 1 HP at the start of each of the target's turns. When the fight ends, the rest of the hour's healing lands at once. A character Regenerate is still healing survives a retreat or defeat that would otherwise kill them.

Orenthel's followers mend as they mend others. Dawn's Resilience gives the healer 2 HP for each other creature they heal, with a spell or an item.

Release steps: none.

## 0.53.0

The Still waits in the deep Ashmark, beyond the Corrupted Front. It does not fight until someone harms what holds it there. Six hidden anchors bind it, and a Perception or Arcana check at DC 18 finds one. Strike an anchor, hit or miss, and the Still answers with Rejection, a burst from that anchor that divine, radiant, fire and thunder magic can break through. It falls when the last anchor breaks.

Walking into the Still charms you. A charmed traveller cannot leave, and a party that would take one out refuses to move until that member is free. Every in-zone hour brings another save to break the charm. Hours do not pass during combat. A day spent charmed starts to drain the traveller, and a drain that empties an attribute is a character's death, handled like any other.

Locations can now carry a recommended level. The DM warns a party heading somewhere well above its level: the Corrupted Front is recommended at 14 and the Still at 18.

Release steps: none.

Twelve patron synergies now apply in combat:
- A Zhael rogue or mage crits on a natural 19 as well as a 20, including when Fate's Thread rerolls the d20 to a 19.
- A critical hit from a Thyra warrior or skirmisher adds 1d4 lightning.
- Kaelen warriors, guardians and skirmishers who have Extra Attack add 1d4 to every weapon hit.
- A Veythar mage, artificer or seeker's arcane cantrips roll two extra damage dice in any Resonance state, and four in Overreach.
- A Mortaen mage gains +1 on spell attacks against undead. No current creature is undead, so this waits for undead content.
- A Mortaen cleric's Sacred Flame deals necrotic damage instead of radiant. A Veilrender absorbs it like any other non-radiant spell.

In multiplayer, each player's own patron and archetype decide their bonuses. Fixed: a resisted hit can no longer heal its target.

Release steps: none.

## 0.52.0

Damage spells now hurt what they hit: outside the Choir, a mage's spells used to report damage that never landed. Area spells such as Fireball and the cone of Corruption Wave hit everyone in their shape, and a save spell asks each target for its own save.

Hollow creatures fight by their bestiary rules. They resist, ignore or take extra damage by type, and poison does nothing to any of them. Every Tier 1-2 Hollow creature has an encounter the DM can start. Adult mawlings hunt in packs. The Hollowed Knight gets back up at 1 HP, attacks with two corrupted blades, commands its mawlings, and a critical hit from it can leave a hero Hollowed. The Veilrender regenerates unless radiant light or a Veil Ward stops it, corrodes everything living that stands in its field, and feeds on any spell that is not radiant. The Ashmark's Corrupted Front, northwest of the Greyvale wilds, is where the Veilrender waits.

New characters start with their archetype's standard attribute spread. Levelling up raises attributes along the archetype's recommended path, and the player can ask the DM to move those points until their next long rest. Rogues land Sneak Attack once a turn when they have advantage or an ally beside the target. Melee attackers close the distance before they swing.

Zhael's Fate's Thread can now reroll the new saves too: the Knight's critical-hit save, Unholy Fortitude, save spells, and the Veilrender's field. A Worthy Foe pays its Stamina only when it truly falls, not when Unholy Fortitude stands it back up.

Release steps: none.

## 0.51.2

Scheduled super tests now check develop in a dedicated clone on the test host, with their own Docker project and port offset. Each run tears its Docker stack down when it ends, pass or fail, so an idle super stack no longer holds host ports between runs.

Release steps:

- After merge, stop any running old super job on each former host. In `$HOME/.xp/super/divineruin`, run `bash scripts/teardown-worktree.sh`. Then run `git worktree remove "$HOME/.xp/super/divineruin"` from the host repository that registered it. Both commands are unpaid and write no production data. Leave a dirty worktree in place for inspection.
- After merge, run `bash scripts/super-test-install.sh` from the checkout on the mini. This is unpaid and writes no production data. The runner defaults to `$HOME/.xp/super/divineruin-super` and port offset 9000.

## 0.51.1

The XP workflow's sprint-wide reviewer (angle-reviewer) now runs on Claude Opus 5.5. The Haiku security triage still decides whether the security angle runs.

Release steps: none.

## 0.51.0

Four more god abilities now work in play. Kaelen's Battle Cry gives every ally in the fight +1d4 to attack rolls for two rounds. Kaelen's Judgment names a Worthy Foe: every attack on it has advantage for the fight, and defeating it restores half the follower's Stamina. Orenthel's Beacon gives each Hollow creature disadvantage on its first attack against the follower in a fight. Orenthel's Restoration Surge removes Poisoned, Blinded, Frightened or stage-1 Hollowed from an ally, at no Focus cost. Stamina restored earlier in a combat round is no longer lost when a later ability's cost is paid.

Release steps: none.

## 0.50.5

Fixes a creation test left expecting the old 12/17 starting HP for a Kaelen warrior.

Release steps: none.

## 0.50.4

A new Kaelen follower now starts at full HP, including Warrior's Endurance (17/17 instead of 12/17).

Release steps: none.

## 0.50.3

Proof's agent test sandboxes now reuse the checkout's agent virtualenv when it already matches the tree's lock, instead of building a cold one per sandbox; a tree with a different lock still gets its own fresh venv, and the shared one is never modified. A full sprint run on the Intel Mac dropped from 63 to 19 minutes. Two test races that the faster run exposed are fixed: the Choir refusal guard no longer counts the startup `session_init` as a gameplay effect, and the Leave summary spec pauses the browser clock at the browser's own time.

Release steps: run `uv sync --project apps/agent --frozen` in each checkout so its venv matches the lock and can be shared.

## 0.50.2

The XP workflow's fixer and slate-reviewer now run on GPT-6.2 Sol, as a trial.

Release steps: none.

Fixes a broken comment line in the XP workflow config.

Release steps: none.

## 0.50.1

The XP workflow's code-writing agent (executor) now defaults to GPT-6.2 Sol.

Release steps: none.

## 0.50.0

Zhael's followers can bend fate. Fate's Thread lets a follower force a reroll after any check, attack, saving throw or death save they or an ally makes, then choose which result stands; the outcome waits until they decide. Lucky turns a follower's own natural 1 into a 20, or a 20 into a 1. Initiative, shoves and grapples, reaction contests, crafting experiments, Echo rolls and free-form dice are outside fate's reach.

Mortaen's followers sense the dying: Death's Awareness names the creatures and party members nearby at a quarter health or less. Nythera's followers keep their bearings: Horizon Sense reports the hours traveled since their last long rest and the nearest place they have never visited, counted in travel legs.

Veythar's followers roll saves against the Hollowed condition with advantage (Scholar's Ward), and Kaelen's followers have 5 more maximum HP (Warrior's Endurance).

Release steps: none.

## 0.49.3

Housekeeping: the shared patron validator test fixture now carries Veythar's current Natural cantrip synergy text, matching the game content. No gameplay change.

Release steps: none.

## 0.49.2

Thyra's Natural synergy for Druids, Beastcallers and Wardens now works away from the wild. Outside natural terrain, Nature's Pulse gives them +2 on Perception and Survival checks. In natural terrain it still gives advantage, and the two never stack.

Release steps: none.

## 0.49.1

Fixed: an Unbound player whose patron was stored as empty, rather than "none", made the twenty-minute deed judgment fail, which stopped that session's background loop. Such players are now judged as Unbound and earn autonomy normally. A patron id that names no god still fails loudly.

Release steps: none.

## 0.49.0

The Unbound Path now has its own progression. An Unbound player builds autonomy by acting alone:
- winning a fight with no ally present (+4);
- succeeding on a check alone (+1);
- choosing to push their own Resonance with Raw Channeling (+2).

Every twenty minutes of play the DM judges these deeds, each counted once, and tells the player when they reach a new tier. Tiers are milestones and are never lost.

- **Self-Reliant** (from the start): choose one saving throw to become proficient in. It applies at once, even mid-fight.
- **Self-Forged** (40 autonomy): Divine Immunity. Once per long rest, the player can shrug off a divine ability, narrated by the DM.
- **Sovereign** (75 autonomy): Veil Mastery. Once per session, a Hollow Echo becomes "Nothing stirs".

Rule change: Veil Mastery used to be every Unbound player's starting gift. Now it is the Sovereign reward, as the design intends.

Asking the DM about your patron as an Unbound player now reports your autonomy, your tier and which rewards are ready.

Release steps: none.

## 0.48.2

The agent test tooling moves to pytest 9.2.0 and pytest-bdd 9.0.1. One pytest run that mixes acceptance and regular test files no longer loses the acceptance fixtures. Nothing players see changes.

Release steps: none. After pulling, run `uv sync --project apps/agent --frozen` in each local checkout.

## 0.48.1

Move the patron query into a dedicated module to make future patron updates easier to maintain.

Release steps: none.

## 0.48.0

Every archetype now has a synergy with every patron: 180 pairings, each Natural, Divine or Unexpected. Natural pairings fit the god's domain and give the largest mechanical bonus. Divine pairings give a moderate one. Unexpected pairings give a small, unusual edge, often something only that character notices. A player can ask the DM about their synergy, and the DM can look it up.

Twelve synergy effects now work in play:
- Kaelen's Iron Resolve triggers below 40% health, instead of 25%, for Warriors, Guardians and Skirmishers.
- Aelora's Artificers get +2 Bond with two allies near.
- Syrath's followers cast hidden for one less Resonance.
- Nythera's Seekers and Spies get +3 to Investigation and Perception at a place they haven't stayed before, including when searching for the Choir's sound.
- Nythera's Druids and Beastcallers get +1 to Animal Handling.

Synergies that change combat rolls, or that depend on what a check is for, are described by the DM but don't change the numbers yet.

Unbound players get +1 on every skill check when no companion or other player is with them.

Some design-doc synergy numbers were rebalanced so Natural is always the largest bonus. Valdris's Paladin bonus rises to +2. Several Unexpected and Divine bonuses drop to +1, and Thyra's Unexpected critical bonus drops to +1d4.

Release steps: none.

## 0.47.2

Native backend acceptance on iOS owns its API server, Metro and temporary sign-in enrollment, cleaning up after each run.

Release steps: none.

## 0.47.1

A test now covers the HUD inventory showing tainted and clean stacks of the same material as separate rows, each with its own quantity, in the phone-sized web build. Nothing players see changes.

Release steps: none.

## 0.47.0

Patron tier abilities are in play. A follower at Acknowledged, Devoted or Exalted favor can now ask the DM to use the seven abilities the DM resolves by narration: Veythar's Lorekeeper's Library, Syrath's Whisper Network and Veilwatcher's Eye, Mortaen's Speak with Dead, Nythera's Charted Course, Valdris's Discern Lies and Zhael's Prophecy Fragment. Valdris's Layer 1 gift, Weight of Truth, works the same way. Each use is spent and comes back on its authored rest or, for once-per-session abilities, at the next session. Abilities lock when favor drops below their tier and come back, with the same spent state, when it climbs again. The other 23 tier abilities are listed as not yet in play.

Rule change: a long rest now also restores abilities and gifts that recharge on a short rest. This includes Veythar's Lorekeeper's Insight and Syrath's Shadow Veil, which before came back only on a short rest.

The character sheet lists the follower's patron abilities as ready, spent or locked, and the favor bar stays current. A player who joins someone else's session now gets their own sheet and favor bar right away, and a reconnect refreshes them. Session start data is sent only to its own player.

Under the hood, spell_casting.py is split into smaller modules with no behavior change.

Release steps:
- Apply migration 065_patron_revision.sql (adds players.patron_revision and its update trigger) with the normal migrate step before deploying the agent and server. Free; it writes the production schema.

## 0.46.0

In multiplayer, every player now hears their own god. When a guest's favor crosses a tier, the guest's patron whispers to them by name, and a guest whose favor drops hears that god's displeasure once a session, as the host always has. When two players cross at once, both whispers play in turn. A player who leaves before their whisper plays hears nothing, and their whisper is not counted as delivered.

Release steps: none.

## 0.45.2

The test runner is pinned to proof v0.34.1. Before the fix, staged runs (every free patch's acceptance and every commit hook) read every input file through git for every task, so setup on a staged sprint run took 25 minutes or more. Setup now takes about 24 seconds. There is no player-facing change.

Release steps: none.

## 0.45.1

Split spell casting into smaller modules while preserving casting behavior.

Release steps: none.

## 0.45.0

Crafting now counts toward your patron's favor. When a craft finishes, even with a flaw, the crafter records a crafted-item deed. Aelora, the Hearthkeeper, values that deed, so her followers gain favor at their next twenty-minute judgment in play. A failed craft records nothing.

Release steps: none.

## 0.44.0

Your patron now notices what you do in play. Winning a fight with every enemy down, fleeing, talking a fight down, slipping past on a stealth check and uncovering lore on a knowledge check are recorded as deeds. Every twenty minutes of play, your patron judges them. A deed your god values raises favor, a deed against its values lowers it, and another god's deed is ignored. Each kind of deed counts once per twenty minutes, so repeating it earns nothing more, and a deed the DM has already rewarded is not paid again. Deeds left unjudged when a session ends are judged early in the next one. When favor moves, the DM hears about it and your favor bar updates.

Release steps: none.

## 0.43.0 — 2026-11-17

- The Greyvale arc plays to its end. Finding the journal fragment puts it in the inventory, even when the item was found before its stage came up.
- The ruins have a fight tuned for a level-2 player: a pair of young mawlings, a new tier-1 Hollow creature. Winning it opens the way on.
- The Veil fragment from session 1 opens the sealed inner door. Any party member holding it lets the party through, so a warrior is no longer locked out by an Arcana check.
- Walking into the inner chamber reveals the sealed artifact, with no roll to miss.
- Keeping the artifact secret or showing the companion is a decision the DM records once. Its effects apply in the same transaction and are remembered. Millhaven's defence choice uses the same path, and an option effect that does not parse is refused.
- Bringing the find to Emris closes the arc. The closing beat is spoken, and the player's own patron whispers; an Unbound player hears none. Effects that nothing consumed were removed.
- Veythar followers can reroll a failed knowledge check once, and Syrath followers can vanish for a round in combat. Each gift returns after a short rest.

## 0.42.1 — 2026-11-17

- Proof generation no longer fails in a checkout that holds a Git-ignored virtualenv (such as `scripts/audio/.venv-sa3`). In a Git checkout the import graph lists only tracked and unignored files; Proof's sandbox keeps scanning its tracked tree.

## 0.42.0 — 2026-11-16

- An edit anywhere reruns at most a handful of expensive tests. Across every tracked file outside the lockfiles, manifests, toolchain versions and acceptance-stack scripts, the files whose edit reruns more than 20 acceptance or e2e tasks fell from 829 to 11, and the mean per file fell from 19.5 to 4.7. `python3 scripts/proof_key_breadth.py` reads it in about 20 seconds without running a test, and `--limit <glob> <n>` fails naming any file over a limit. It replaces `scripts/proof_selection_probe.py`.
- Test harness modules, conftests and provider helpers key one representative test per family. A feature file, fixture or WAV keys the tests that name it.
- An agent module keys its direct importers when there are at most 10, otherwise one representative per reaching family; below the threshold every reaching test is keyed, its own family included.
- Content keys the tests whose behavior loads it, including a test's own SQL reads of a seeded table, or representatives. Migrations and the seed script stay within 20.
- Acceptance tests that launch subprocesses key what they actually launch (Proof-resolved TypeScript closures and named scripts) instead of whole directories, and media keys the tests that read it. An unclassified subprocess launch or a named reader that reaches no test fails generation.

## 0.41.0 — 2026-11-16

- Sign-in is invite-only. An email must be on the allowlist (`bun run allow <email>`, `--remove` to revoke) to receive or use a code; anyone else is told the playtest is invite-only, and no account is created. The script prints which database it wrote to.
- One DM per player. Starting a session while another is live closes the old room first, so its DM saves the summary; nobody can join or invite into a room they don't own. A DM that fails to join returns an error with a retry instead of an empty room.
- Re-entering never speaks a stale recap. A new session waits up to 15 s for the previous one's summary; if it failed or never arrived, the DM greets the player without a recap. A dispatch superseded while waiting steps aside quietly.
- Leave shows the session summary. A solo player's Leave ends the session and the summary screen appears; in a party, the leaver departs with their own summary and a guest becomes host if needed. Leave during creation or onboarding returns home at once. If no summary arrives within 15 s, the app goes home anyway.
- A session is capped at 60 minutes, with a steer toward a resting point at 55. After 5 minutes of player silence, companion chatter and hints stop and the DM checks in once; at 10 minutes the session ends with its summary saved.
- Rate limits live in Valkey and hold across server instances. Signed-in requests count per player; others count per client IP, read from `X-Forwarded-For` behind the HTTPS proxy when `TRUSTED_PROXY_HOPS` is set. A broken limit store fails the request rather than letting it through.
- The native iOS check picks a general iOS runtime and a phone with a Home gesture, not Xcode 27.2's foldable-only runtime.

## 0.40.0 — 2026-11-16

- PR CI runs only the two lint jobs. Tests are proven locally by Proof: a free patch's land runs `scripts/free-acceptance.sh`, which runs Proof's `land` set and then its `sprint` set on the trial-merged tree with the sprint hook's environment.
- A fresh, cache-free `super` run of every declared task runs on this Mac at 02:00 on Tuesday, Thursday and Saturday (`scripts/super-test.sh`, installed by `scripts/super-test-install.sh`). It tests `origin/main` in its own worktree and raises a macOS notification on any red.
- Edits select fewer tests. Docs key no task. A widely imported agent module keys about two representative acceptance tests per family instead of every importer, and a content file keys the tests that declare they read it (`scripts/proof-families.json`). The seed script and migrations also key the tests that name them. Across five probe edits the changed task keys fell from 468 to 117 (`scripts/proof_selection_probe.py`).
- The unused CI service-database mode is gone from the DB lifecycle helpers.

## 0.39.0 — 2026-11-16

- The game runs as containers. `deploy/compose.yml` runs the server, the DM agent and the async worker, plus a one-shot migrate-and-seed job, from three images (`deploy/*.Dockerfile`). The images run as a non-root user and carry no `.env`, tests or mobile sources. `scripts/deploy-up.sh` is the operator's entry point, and `scripts/deploy-smoke.sh` checks the built images locally before a deploy. Nothing in this release creates a cloud resource.
- `GET /api/health` returns 200 when Postgres and Valkey both answer, and 503 naming whichever did not, within a bounded deadline.
- Every deploy migrates and seeds before any serving container is replaced. A failed migration or malformed content stops the deploy with the old containers untouched. Production seeding skips the `player_1` fixture, refuses if fixture rows already exist, validates rows with both the Python and TypeScript catalog parsers before committing, and clears the content caches so the new content is served without restarting the server.
- Narration audio and portraits live under one generated-media directory, set by one variable that all three processes read and backed by one named volume. They survive a container restart and are served by the server whichever container wrote them. The bundled prologue and tracked images still load on a fresh volume.
- A production server, agent or worker refuses to start half-configured and names every missing variable. The mock email transport is refused in production, so `RESEND_API_KEY` is required. `deploy/env.production.example` lists what each service needs, and `.env.example` is complete.
- An unhandled error in the server, agent or worker leaves one JSON line on stderr with the service, time, message and stack, and no tokens, emails or player speech. Compose keeps bounded, rotated logs per service.
- The iOS app can be built for TestFlight against a named server with an EAS profile.

## 0.38.1 — 2026-11-16

- The fast Python lane seeds its dev database after migrating it, so a change to `content/*.json` is tested against matching data at story land instead of the previous seed. The fixture players in `content/players.json` are reset on each run.
- `scripts/teardown-worktree.sh --sweep` works on a machine that also runs unrelated Docker Compose projects. It skips a project with no divineruin ownership labels and still refuses on partial, mixed or malformed ownership.

## 0.38.0 — 2026-11-16

- Session one is a complete episode. A new player answers two questions, meets a companion, fights once, is handed a mystery and a reason to go north, and finds a message from their god waiting afterward.
- Character creation asks for a calling and a name. The first-share roster is four archetypes (warrior, mage, rogue, cleric), three races (human, elari, vaelti) and four patrons (Kaelen, Veythar, Syrath, Aelora). Race defaults to human and the patron follows the archetype; a player who names a race or patron from the roster gets it. The full catalogs are untouched, so the roster widens by editing one list.
- Onboarding is three beats in the market square and ends when the companion has been met. The DM can no longer move the player during onboarding, so play always begins in the square. The companions' `onboarding_suggestion` field is removed from the content and from the Python and TypeScript loaders.
- The wounded rider now arrives for every new player, once, when play begins. He is carrying a wrapped stone shard out of the Greyvale; in the new guild infirmary the sound thins around it and one shadeling condenses. The scene could not fire before: it required a player with no companion, and it listened for a location change that the onboarding handoff never makes.
- When that fight ends, by victory, defeat, flight or de-escalation, the engine gives the player the Veil Fragment and starts "The Greyvale Anomaly". The DM no longer has to decide to start the quest. It happens once, inside the combat-end transaction, and two sessions ending the same fight cannot grant it twice.
- The first fight is one shadeling. Across 20 fixed seeds a level-1 warrior, mage, rogue and cleric with their companion win 20, 19, 19 and 20 fights. Session one pays 25 XP, so the player reaches Millhaven at level 1.
- A patron whisper is generated for the catch-up feed after the first episode, even at zero favor, and only once. This spends one background narration and one voice render per new player. The favor-25 whisper trigger is unchanged.
- Companion hints during the rider scene reach a silent player before any quest is active.
- Fixed: a reconnect could fail its cleanup because a speech handle was scheduled as a task (#625), and proactive speech during a combat handoff could stop all later background hints (#626).
- Three unread entries are removed from `content/events.json` (`market_disruption`, `normalcy_market_task`, `companion_introduction`).
- `docs/milestones/13_first_share.md` lists every step to a friends playtest and `docs/milestones/audit/first-share.md` records the evidence behind them.

## 0.37.0 — 2026-11-15

- The Millhaven leg of the Greyvale arc no longer depends on the DM deciding to advance the quest. Arriving in Millhaven, by walking or by travel, completes "The Road North"; winning the Hollow patrol fight completes "First Blood", whether combat ends through the DM's tool or automatically. Rewards are paid once and roll back with the combat end if anything fails.
- The DM's prompt states what finishes each active quest stage: the encounter to start for a fight, the facts and sources for an investigation, and the exact `update_quest` call for stages the engine does not advance. The unread stage `hints` arrays are removed from `content/quests.json` and the shared TypeScript quest entity; scene-beat companion hints are unchanged.
- The Millhaven patrol is retuned for a level-1 character with a companion: one shadeling and one minion shadeling, no mawling. Across 20 fixed seeds a warrior, mage, rogue and cleric win 20, 17, 17 and 20 fights using only basic attacks. The mawling waits for the ruins.
- Every authored location can be walked to from the Accord market square and every exit has a way back. Five exits were missing, including the ones into Emris's study and Yanna's farmhouse and the road north out of the square. A content check fails if either property breaks.
- Players can rest. The DM's new `rest` tool restores Stamina fully and Focus to half on a short rest, and HP, Stamina and Focus on a long rest, which also records the settlement as the player's anchor. Either rest resets Resonance. It refuses in combat and where the location is not safe, and restores each co-located party member from their own pools.
- A lost fight no longer crashes resurrection with a missing player id.
- New characters are created with their archetype's Focus and Stamina pools. Creation had written neither, so every spell or ability with a cost was refused; migration 063 backfills existing characters without touching pools already spent.
- A long rest restores HP only up to the ceiling left by permanent death penalties.
- The per-player character snapshot sent after a rest goes only to that player, not to everyone in the room.

## 0.36.1 — 2026-11-06

- CI's Python lanes install ffmpeg from a pinned, sha256-checked static build (BtbN month-end 2026-10-31, LGPL 8.1) that is cached between runs, instead of through apt. The Azure apt mirror had stalled that step to the 20-minute job timeout twice in one day. The step is capped at 5 minutes.

## 0.36.0 — 2026-11-06

- Every patron now has its Layer 2 Resonance modifier and its three favor tiers (Acknowledged, Devoted, Exalted) in `content/gods.json`. The Python loader and a new shared TypeScript god entity validate them against one fixture corpus and fail loudly on a bad profile.
- A caster's patron changes their magic. Kaelen's combat spells generate 1 less Resonance. Thyra's generate less on natural ground. Syrath's generate 2 less while hidden. Orenthel's healing generates none. Valdris's are halved against a creature that wronged the party. Mortaen's generate none on a target at 0 HP. Nythera's generate 1 less in a place the caster has never been. No reduction goes below 0. Veythar's arcane casters roll 2 Flickering bonus dice instead of 1. Aelora's spells ignore Veil Ward penalties. At Resonance 9+, a Zhael follower hears two Hollow Echo results and picks one aloud.
- Hiding and grievances are real state. A successful Stealth check hides the player until they cast, attack or fail a Stealth check the DM calls when a watcher might notice. Combat records who struck first, and the DM can mark a broken promise or an injustice with `update_npc_disposition`.
- Thyra's Nature's Pulse is live: advantage on Perception and Survival in natural terrain for every check, discovery, gathering, travel and Choir-search roll. The DM is also cued to narrate ecosystem health without a check.
- A favor loss now whispers only when it drops the player's tier; smaller losses stay silent. Neglect decay is still narrated at session start and on join.
- The Unbound Path works. The DM can tell an Unbound player their exact Resonance. Once per encounter they can push it up by 3 through `activate`, and once per session Veil Mastery turns a Hollow Echo into "Nothing stirs".
- Phase 8 M8.1: 3 open acceptance criteria (was 9). The alignment heartbeat is deferred to its own sprint.

## 0.35.0 — 2026-11-06

- Harvesting follows the bestiary's skill table. Every gated drop names one material kind, and each kind needs exactly one skill and tier (pelts and meat Survival: Trained; glands, venom and rare gems Survival: Expert; construct parts Crafting: Trained; Hollow residue Crafting: Expert; magical components Arcana: Trained; Named fragments and Veil shards Arcana: Expert). A catalog test fails on any drop whose gate disagrees with its kind. cave_gemstone moves to Survival: Expert, named_fragment to Arcana: Expert, and woven_void_fragment to tier 2. Migration 062 turns salvageable_weapon into equipment.
- Every loot drop either appears in a recipe or is marked `crafting_use: "trade"` for later sell values; no drop is both.
- Dispel Corruption purifies a whole tainted stack. The caster names the owner and the item, Focus is spent as for any cast, and the units move to the clean stack in one transaction. Corruption-saturated stone refuses before Focus is spent.
- Artificers can purify tainted units as a timed activity: `begin_activity(kind="purification")` takes the units into escrow at once, and after three skill-practice cycles the worker returns them clean, exactly once even if resolution replays.
- Every creature names its habitat in a required `terrains` list, in Python and TypeScript. Hollow creatures list every terrain for now.
- `build_encounter` composes encounters from the creature catalog by tier, region and terrain. The budget scales with party size and each companion's own HP factor (Sable 0.50, the others 0.75). A mixed-level party uses its mean level. Expected damage per round follows each player's level, so fights fit their difficulty's round window: standard 3–5, tough 4–6, boss 5–7. A request that cannot fit raises a named error. Known gap: player spell and ability damage is not yet applied by the combat engine (debt 6d3b1d6a), so generated fights run longer than certified until it is.
- The DM can start a generated encounter with `enter_mode(mode="combat")` and a difficulty instead of an encounter id, and can look creatures up with `query_info(kind="creature")`. GPT-6 Luna accepted all five changed tool sets in strict mode.
- Phase 7 M7.4 is complete: 0 open acceptance criteria (was 8).

## 0.34.0 — 2026-11-04

- Every location now appears on the HUD map. Seven locations had no map node (Training Hall, Grimjaw's Forge, Grimjaw's Quarters, the Old-Growth Grove, Keldaran Southern Pass, the Tidal Shore and the Reed Marsh), so the map panel silently left them and their routes off. A test now fails when a location has no node, and the location-authoring guide lists it.
- Combat loot honours skill gates. `generate_loot` replaces `derive_role_loot`. A drop whose `requires` the party cannot meet never appears; it is not a failed roll. The gate uses the best tier per skill among the players who fought, so one player's Crafting and another's Arcana can unlock a drop together. A drop authored at chance 1 always drops, even from a Minion, and dice quantities still roll.
- Hollow loot is tainted. Migration 061 keys `player_inventory` by `(player_id, item_id, tainted)`, so tainted and clean units of an item are separate stacks. Drops from a `hollow_residue` loot table land tainted, and other drops land clean. A craft whose recipe does not allow tainted materials never spends tainted units; one that does spends them first. The Python and HTTP inventory snapshots and the mobile inventory panel keep the two stacks apart. Native HUD verification is deferred: Xcode 26.3 cannot build Expo 57 on the Intel Mac.
- The `agent-db` proof provider applies pending migrations to the checkout's dev database, so a story that adds a migration no longer fails land.
- Phase 7 M7.4: 8 open acceptance criteria (was 11).

## 0.33.0 — 2026-11-03

- Playwright runs as proof tasks in the sprint set: `e2e:chromium`, `e2e:web`, `e2e:web-lighthouse` and `e2e:home-character`, which is the representative for `packages/shared` edits. A web-only edit skips the mobile app tests and a mobile-only edit skips the web tests; editing a spec runs only its task. The e2e tasks share one lane because they bind fixed ports. Each keeps Playwright's 4 workers and runs beside acceptance at every core.
- The sprint hook calls only `proof run --set sprint`. A fresh run of all 100 tasks (636 acceptance cases, 88 Playwright tests) took 354 s, about the time acceptance alone took before, against 347 s plus a separate 133 s Playwright run. A red e2e task keeps its log, screenshot, video and trace.
- The four acceptance tests proof could not trace (dynamic imports) no longer run on every change: they key on the agent sources, including the `*_agent.py` modules the verb registry discovers.
- Proof v0.33.2. The milestone "Run only the tests an edit could break" reaches distance 0.

## 0.32.0 — 2026-11-03

- The hooks run proof's selection, not whole lanes. Commit runs staged lint, `proof lint`, then only the commit-set tasks the staged files can break; a repeat commit finds them PROVEN, and a Markdown-only commit runs none. Story land runs the commit and land sets on the merged tree, reusing what the branch proved: a repeat land took 3 s instead of 171 s. Sprint close runs the selected acceptance tasks next to Playwright. `bun run test:all`, `test:python` and `test:acceptance` stay as manual full lanes, and PR CI still runs everything.
- Proof v0.33.0 runs every core; no hook passes `--jobs`. The DB-backed Bun tasks clone a seeded template from one provider Postgres and Valkey.
- The two slowest acceptance files run as several tasks (choir capstone in 3, terrain commands in 3), so a fresh full acceptance run took 347 s, down from 456 s. The generator refuses splits that would leave a test in no part.
- The milestone Measure also counts the hooks that call proof.

## 0.31.2 — 2026-11-03

- `proof` (v0.32.0) also declares the Python tests: `agent-pytest` (the unit lane, in `land`) and one `agent-acceptance:<file>` task per deterministic acceptance file (in `sprint`), generated by `scripts/generate-proof-declarations.py`. An edit reruns the tests that import the changed file directly. A shared module reruns at most three representative tests that import it, and lint and the unit lane cover the rest. An edit to migrations, the seed or the provider reruns everything.
- Proof runs tasks on every core by default; nothing passes `--jobs`. The full acceptance set (92 tasks, 636 cases) took about 6.5 min at 16 jobs on a loaded host, against 618 s for the old serial lane and 1315 s for one-at-a-time proof tasks. The slowest file, `test_choir_capstone` at about 4 min, sets the floor.
- One proof run starts one Postgres (seeded template, cloned per task) and one Valkey (a database per task), and reuses the checkout's LiveKit. Plain `pytest` keeps its own containers.
- The provider refuses to start when the seed imports a module missing from `proof.yaml`'s `seeded-data`, so the shared template cannot change without rerunning every task.

## 0.31.1 — 2026-11-02

- `proof` (v0.27.0) declares the ten Bun test targets: the six packages plus the four DB and Redis server tests as their own tasks. `bunx proof run --set commit` runs only the tasks whose test imports or declared reads changed, and `proof plan` shows the rest PROVEN. Hooks keep their current tiers for now.
- The shared portrait checks test that the files exist instead of asking Git, so they pass in a sandbox without a repository.

## 0.31.0 — 2026-10-13

- Each check runs once, in the cheapest tier that catches it, with measured costs in `.xp/system.md`. Push now only scans outgoing commits for secrets (about 0.1 s, no services). Story land keeps the fast lane, and sprint close runs acceptance and Playwright. PR CI owns full lint and all suites, so free patches lose no coverage; Python and acceptance run as parallel jobs, and acceptance refuses to skip when Docker is missing.
- Acceptance cases that need a fresh database share one Postgres server, each with its own unseeded database: Postgres now starts 3 times per full run instead of 11.
- The nightly test tier is gone; constraints 2 and 13 name commit, story land, push, sprint close and PR CI.
- Meta-tests left the regular runs (tests of hooks, gates, dev tools and the doc indexer). Test code is now 1.87x source, under the 2x bar. Floors that prove a product guard inspected something stay.
- `REMAINING.md` matches the phase docs (331/538) and the content and code it describes.

## 0.30.0 — 2026-10-11

- Elite and Boss Mawlings attack Claw, Dissolution Maw, Claw. The per-role sequence is authored on the catalog row, and both validators reject unknown role keys and unresolvable attack references. Standard Mawlings keep Claw then Dissolution Maw.
- A melee hit from within 5 ft on a Fallen character adds two death-save failures. Ranged hits, save damage and the Dissolution Field tick still add one. A queued strike continues onto a target who fell earlier in the same phase; only damage reaches a Fallen ally, so a hostile mark aimed at one is wasted.
- Story land runs the fast lane (`bun run test:all`) on the merged tree before the merge commits, and keeps the full output in `flake-artifacts/last-pre-merge-commit.log`. Acceptance stays at sprint close.
- `probe_strict_limits.py --provider openai-luna --agent <name>` sends one strict-compile request for one agent with retries off. The combat agent's 9 tools were accepted strict.
- Split `combat_turn.py` into the tool shells and `combat_resolve_phase.py`, and move the down-target rules into `combat_down.py`, which breaks an import cycle through `combat_ability`.
- Source walks in the strict-budget and line-cap tests read tracked files only, ending an intermittent fast-lane failure under parallel runs. Meta-tests of test helpers were deleted; constraint 3 now keeps tests of tests, hooks and tools out of regular runs, and new constraint 13 makes wall clock a quality budget.

## 0.29.0 — 2026-10-11

- Every location carries a physical terrain from one closed ten-value list (Decisions 129–132), mirrored in Python and TypeScript. Seeding and server startup refuse a missing or unknown terrain, or one that does not fit the location's region type. The travel-difficulty field formerly named `terrain` is now `navigation`.
- Primal magic draws on the land: a cast generates its catalog Resonance scaled by the terrain's base (healthy wilds are the baseline), so ancient forest is gentler than a city. Per-spell terrain overrides and the stale "normal" default are gone.
- Korath's earth-anchored −1 primal Resonance applies only on earth or stone, not coast or wetland. The Druid's Veil Ward is refused off natural terrain and costs 3 Focus instead of 5 in ancient forest.
- Combat resolves its terrain once at the start and keeps it with the fight; casts and wards mid-combat never look the location up again. A combat at a location without terrain refuses to start.
- Four new wilderness locations give every terrain a real place: the Old-Growth Grove (Thornveld), Keldaran Southern Pass, the Tidal Shore and the Reed Marsh (Sunward Coast). `world_data_simulation.md` gains an "Authoring a Location" guide.
- Free test lanes can no longer bill a paid provider: an unapproved request to Anthropic, OpenAI, Deepgram or Inworld is refused and fails the test, even when the calling code swallows the error.
- The agent dev-command boot check allows a loaded four-core machine time to start.

## 0.28.0 — 2026-10-08

- Mawlings declare their authored Claw then Dissolution Maw multiattack as one declaration with per-strike targets. Each strike keeps its own held reaction window across pauses and reloads; an unavailable strike drains unresolved, with no retargeting. Minion Mawlings keep a single attack.
- Dissolution Maw applies its CON DC 13 held-item durability rider to a DM-selected, equipped player item, chosen from target-scoped inventory facts that include guests. Role DC modifiers apply, and companions are excluded. Both validators reject riders on save- or condition-resolved attacks.
- A living ally grappled by a living, able Mawling takes 1d6 necrotic Dissolution Field damage at its turn start, even when stunned, Fallen or omitted from declarations. Damage to a Fallen character now adds one automatic death-save failure.
- Reaction spends checkpoint in the same transaction as their resource debit, so a reload cannot re-spend them. The checkpoint save refuses to run without the combat-state lock.
- Split XP roles across model families: codex plans and executes, and Claude reviews plans and diffs.

## 0.27.0 — 2026-10-04

- Adopt the v1 development constraints: test production behavior once at the outermost useful boundary, retire duplicate unit coverage, and remove documentation wording checks and test meta-checks.
- Keep pushes service-free with local lint and Bun tests. Run the full suite at sprint close; free patches use focused acceptance and normal PR CI.
- Reduce tracked test lines from 177,625 to 160,505 and the test/source ratio from 2.2106× to 1.9991×. Preserve unique behavior checks while removing redundant tests, setup, and commentary.
- Make the live material-inventory acceptance check independent of Bun's compact diagnostic output.
