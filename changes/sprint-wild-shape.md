Bump: minor

Druids, beastcallers and wardens can now really take a beast's shape in a fight. From level 5 they can become a grey wolf, a wild boar or a steppe bison, and from level 10 a dire bear. The beast has its own HP and AC, and it fights with its own bite, gore or claws, opportunity strikes included. Damage comes off the beast first, and anything left over reaches the character when the form drops. A shaped character can't cast spells until level 10 (cantrips only) or level 20 (everything). They can end the form by saying so, and it ends on its own when the fight is over. Followers of Thyra take the shape with 5 temporary HP.

Release steps:
- Reseed content (`bun run seed` against the target database) before the agent starts after deploy. Agent startup now requires Wild Shape's form catalog in the spell rows. It writes the target database, is not paid, and runs before the new agent starts.
