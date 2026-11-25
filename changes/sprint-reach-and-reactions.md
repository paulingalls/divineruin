Bump: minor

Moving in a fight now matters. Walk out of an enemy's reach and it gets a free swing at you as you go. A rogue can avoid that with Cunning Action's Disengage, for 2 stamina. A warrior with Opportunity Strike gets the same chance when an enemy walks away. Either way, the mover stops at the edge of reach and the blow lands there. If it survives, it carries on where it was going.

Winged creatures (the Hollowmoth, the Steppe Razorwing and the Thunderbird) now fly when they close in. A low ceiling forces them onto the ground. Razorwings and Thunderbirds don't provoke when they fly away. A rogue or spy's Slippery now escapes the Architect's Entomb as well as a grapple. A Bandit Captain's Rally heals only the bandits within 30 ft of it. To keep the Architect beatable with opportunity attacks in play, its Construct Slam hits for one point less.

Release steps:
- `bun run seed`, against the deployed database after deploy, to load the changed creature catalog (Rally range, fly speeds, Flyby, Architect Slam damage). It writes production data; it is not paid.
