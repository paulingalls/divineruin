Bump: minor

Paladins of Valdris and Zhael can swear an oath aloud, and the engine holds them to it. A Valdris paladin swears the Oath of Justice. Striking first, striking a surrendered enemy or striking a yielded ally breaks it, and a broken oath locks Valdris's three tier abilities for the rest of that gameplay session, for hosts and guests alike. While the oath is kept, the paladin gains +2 on combat attacks and saves involving recorded wrongdoers, and on skill, social and discovery checks outside combat when the Dungeon Master says justice is at stake. A Zhael paladin swears a timed oath in combat, to defeat a foe or to keep an ally standing by a named round. Until the deadline the paladin gains +1 on every saving throw, death saves included. The DM announces when the oath is fulfilled or lapses.

Concentration saves now follow the natural 1 and natural 20 rule for every caster: a natural 1 breaks concentration even when the total meets the DC, and a natural 20 holds it. Discovery checks now accept the patron query's context tags, so investigation clauses apply on discovery as they already did on skill checks.

Release steps:

- Before deploying the release, run `SEED_PRODUCTION=1 uv run --project scripts --frozen python scripts/seed_content.py` from the release checkout with the production database environment. This writes authored content to production and makes no paid provider calls.
