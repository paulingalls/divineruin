Bump: minor

Valdris paladins who keep the Oath of Justice gain +2 on combat attacks and saves involving recorded wrongdoers. The Dungeon Master can also apply the bonus to skill, social and discovery checks outside combat when justice is at stake.

Concentration saves now follow the natural 1 and natural 20 rule for every caster: a natural 1 breaks concentration even when the total meets the DC, and a natural 20 holds it. Discovery checks now accept the patron query's context tags, so Valdris and Zhael investigation clauses apply on discovery as they already did on skill checks.

Release steps:

- Before deploying the release, run `SEED_PRODUCTION=1 uv run --project scripts --frozen python scripts/seed_content.py` from the release checkout with the production database environment. This writes authored content to production and makes no paid provider calls.
