Bump: minor

Valdris paladins who keep the Oath of Justice gain +2 on combat attacks and saves involving recorded wrongdoers. The Dungeon Master can also apply the bonus to skill, social and discovery checks outside combat when justice is at stake.

Release steps:

- Before deploying the release, run `SEED_PRODUCTION=1 uv run --project scripts --frozen python scripts/seed_content.py` from the release checkout with the production database environment. This writes authored content to production and makes no paid provider calls.
