Bump: patch

Seven Valdris archetypes gain +1 on skill checks when the DM names a matching situation. Rogues and spies also gain the bonus on social Deception for a just cause. The patron query shows each follower’s available context, and the check result names the clause it applied.

Release steps:
- After deploying the updated code and content, run `SEED_PRODUCTION=1 bun run seed` from the deployed repository root with the production database and cache configured. The command is unpaid and writes to production. Complete the seed before starting gameplay services with this release.
- If a gameplay agent is already running the deployed release, restart it after the seed to reload patron content and the check context enum. On the production Compose host, run `DEPLOY_ENV_FILE=/absolute/private/production.env DEPLOY_HTTP_PORT=3001 COMPOSE_PROJECT_NAME=divineruin docker compose -f deploy/compose.yml restart agent` from the deployed repository root with the actual deployment settings. The command is unpaid and restarts the production agent.
