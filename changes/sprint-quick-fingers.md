Bump: minor

Enemies now carry their rolled loot from the start of a fight and keep it across saves; victory awards what defeated enemies still carry. Rogues who learn Quick Fingers can steal, plant or swap a real item just before a melee strike. A failed attempt leaves the foe wary until the round ends, so a second attempt fails and its first attack on that rogue has advantage. Unravel Fate refuses a rewind that would split a Quick Fingers transfer between a fighter's inventory and an enemy's pocket.

Release steps:

- After deploy, run `SEED_PRODUCTION=1 bun run seed` from the deployed checkout with its production environment configured. This writes production content and uses no paid providers.
