Bump: minor

Spells that inflict conditions now apply them in the engine instead of leaving them to narration. Hold Person paralyzes one humanoid, Power Word Stun stuns a foe at 75 HP or less (and fails quietly above it), Slow takes away an affected creature's quick actions, and Faerie Fire outlines creatures in its cube so attacks against them have advantage. Spark's shock stops its target's reactions until its next turn. Each condition that allows a save repeats it each turn, and two casters cannot share one hold.

Guiding Light marks one foe, giving the next attack against it advantage. Invisibility helps an ally sneak and makes them harder to hit until they attack or cast a hostile spell. Faerie Fire reveals the invisible and stops an outlined creature from vanishing again.

Bless adds one d4 to each attack and rolled saving throw while a caster sustains it for that ally. Overlapping casts keep it active until the ally's last sustaining caster stops. Beacon of Hope maximizes every healing the ally receives, Second Wind included. Warding and Protection from the Hollow now affect damage, saves and attacks as written.

A concentration spell now ends when its duration runs out. In combat it counts rounds. Outside combat, travel and rests advance the clock. Spells of a minute or less end when combat ends, a short rest ends spells of up to an hour, and a long rest ends them all. Previously saved Bless effects with no recorded caster need a recast.

Release steps:

- Before deploying, run `bun run migrate` against production. Migration 069 removes saved Bless effects with no recorded caster, and migration 070 adds a duration to active concentration records.
- Then run `SEED_PRODUCTION=1 bun run seed` to write the updated spell catalog, and restart the agent and worker so they load it.
