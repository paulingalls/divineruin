Bump: minor

Zhael paladins gain +1 on saving throws while keeping a timed combat oath. The DM can announce when the oath is fulfilled or lapses as combat resolves.

Release steps:

- Before deploying the release, run `SEED_PRODUCTION=1 uv run --project scripts --frozen python scripts/seed_content.py` from the release checkout with the production database environment. This writes authored content to production and makes no paid provider calls.
