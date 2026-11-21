Bump: minor

The Architect fights with its own architecture. Walls rise and block every line between combatants. The floor opens into pits, the ceiling drops, and the Architect can seal a hero inside a stone chamber (Entomb). It raises a cathedral that turns the room into its domain, and summons constructs. Between turns it takes legendary actions, and it can shrug off a costly save three times a fight. It is tuned against a full level-20 party of four, which beats it in about 12 of 20 fights, typically in 11 rounds.

Warriors and rogues can use their core kit in a fight: Second Wind, Rallying Shout, Devastating Strike, Shield Bash, and Cunning Action to Dash or Hide. Disengage waits for opportunity attacks.

Players can equip the weapons and armour they win, outside combat. Starting gear goes back into the pack instead of vanishing. Characters with elective techniques choose one at level 4 and level 8. Most martial techniques are owned but not yet usable in a fight.

Release steps: after deploy, reseed content on each environment so the four new starting-gear items (mace_common, lute_common, robes_common, shield_wooden) and the Architect's tuned stats are loaded (`bun run seed` from the repo root on a host with that environment's DATABASE_URL; free; writes content rows only).
