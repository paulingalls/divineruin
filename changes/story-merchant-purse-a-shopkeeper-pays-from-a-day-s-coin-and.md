Bump: minor

Shopkeepers buy from a daily purse and have a daily limit for each item. They can offer their remaining silver or a reduced price, and wait for the player to accept before taking the goods.

Release steps: Run `docker compose -f deploy/compose.yml run --build --rm migrate` on the deployment host, from the release checkout with the standard `DEPLOY_ENV_FILE` and deployment environment, before starting the new server and agent. This runs migration 071 and reseeds the economy pricing row in production. It makes no paid provider calls.
