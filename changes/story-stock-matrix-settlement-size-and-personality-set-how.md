Bump: minor

Settlement size and personality set merchant purse allocations and the stock policy for daily restock. Both seed validators check the authored stock modifiers against the inventory pools.

Release steps: Reseed the production content catalog with `SEED_PRODUCTION=1 uv run --frozen --project scripts python scripts/seed_content.py` from the deployed release checkout before starting its updated services. This writes the production database and uses no paid providers.
