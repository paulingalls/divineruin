Bump: minor

Shops now hold real stock. Walk into a shop and the shopkeeper names three or four things worth a look, rarest first; ask for anything else by name ("got any rope?", "a short sword?") and they'll tell you if it's on the shelf. Ask the price, say yes, and the item is yours: the shop's shelf and purse and your gold and pack change together, and you hear it land in your pack.

What a shop carries depends on where it is. A city smith stocks more than a village one, a military town is heavy on arms, a struggling hamlet has little, and a capital has the most. Shelves refill at Aethos dawn, the same way every time for the same day. Rare pieces turn up only some weeks, and once sold they stay gone until the next week. Smiths now sell masterwork weapons, which hit one point harder; one rotates onto the shelf each week. Prices follow how the shopkeeper feels about you, and frontier shops charge more.

Release steps:
- Before the agent starts after deploy, apply migration `scripts/migrations/072_sink_event_log.sql` and then reseed content (`SEED_PRODUCTION=1 uv run --frozen --project scripts python scripts/seed_content.py`, from the deployed release checkout) against the production database. Both write production; neither is paid. The migration adds the purchase sink log. The reseed loads the tiered pools, the stock matrix and the masterwork weapons, retires the three old pool rows, and clears any merchant shelf holding an item its pool no longer stocks.
