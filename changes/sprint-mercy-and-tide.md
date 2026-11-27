Bump: minor

Marshals can call Rally in combat. Every other ally within 30 ft who can hear the call gains temporary HP equal to the marshal's Charisma modifier plus level. A larger pool already held is kept. Players keep Rally's temporary HP until it is spent or they take a long rest, and companions keep it for the fight. An Orenthel marshal's Rally at Dawn adds 1 more temporary HP to each recipient. Rally cannot be called outside combat, and is refused before any Focus is spent.

Renewing Spark rewrites the Orenthel mage synergy. When an Orenthel mage casts Shield, Fly, Invisibility or Haste on themself or a willing ally, the recipient gains 1 temporary HP. This works in combat and out, including a spell cast directly during combat.

Landfall Orders: when combat starts somewhere a Nythera marshal has never been, the marshal and every ally who hears the opening call gain +1 initiative. A silenced marshal gives no call. The initiative receipt and the DM's combat summary now list every initiative award per player. A Valdris marshal's Lawful Command and Landfall Orders stack when both apply.

Two new coastal encounters, a fight on a moving ship deck and a dock boarding, carry a vessel fact the engine reads. On the deck, a Nythera warrior's melee attacks gain +1 (Deck Footing). In the boarding, a Nythera guardian within 5 ft of an ally gains +1 AC (Gangway Guard).

Release steps:

- After merge, run `bun run seed` from the repository root against the local stack. This reseeds abilities, gods, the engine catalog and encounter templates, is unpaid, and writes only to the local stack.
- Before deploying the release, run `SEED_PRODUCTION=1 uv run --project scripts --frozen python scripts/seed_content.py` from the release checkout with the production database environment. This writes authored content to production and makes no paid provider calls.
