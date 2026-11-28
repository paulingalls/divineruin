Bump: minor

Reaction spells from the spell library now work in combat. A caster who has learned Shield or Barkskin can cast it the moment an attack comes in, as long as their class doesn't already have its own version of the spell. Shield of Faith lets a divine caster turn a hit on an ally within 30 feet into a miss after the roll, and the ally keeps +2 armour class until the caster's next turn. Shield of Faith stacks with Barkskin, but two casters' Shield of Faith on one ally does not stack. Nature's Grasp lets a druid on natural ground root an enemy that moves into reach: it stops moving and its remaining attacks that turn have disadvantage. Counterspell lets a mage, or anyone who has learned it, stop an enemy's spell before it lands. The cult leader's Hold Person, Shadow Bolt and Dark Pulse can now be countered, with a check against DC 10 plus the spell's Focus cost.

A guest who leaves mid-fight now leaves the fight. Enemy attacks aimed at them end with a receipt that they left, the rest of the round carries on, and their saved health and conditions are kept. Before, damage to a departed guest could stop the fight from advancing.

Unravel Fate now refuses to rewind a round that someone joined partway through, and says why. The gift stays unspent. Before, the rewind could refund a caster's Focus while the joiner kept the healing or ward it paid for.

Release steps:

- Run `SEED_PRODUCTION=1 bun run seed` to write the updated spell and creature catalogs, then restart the agent and worker so they load them.
