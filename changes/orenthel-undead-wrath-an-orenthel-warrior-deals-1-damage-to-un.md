Bump: patch

Orenthel warriors gain Dawnward Strike. Their hits deal 1 extra damage to Hollow and undead foes while another standing party ally in the fight is below half health.

Release steps:
- After deploy, run `SEED_PRODUCTION=1 uv run --project scripts python scripts/seed_content.py` from the repository root with the release environment's `DATABASE_URL` and `REDIS_URL`. This command is unpaid and writes production data.
