Bump: minor

Aelora's clerics gain +1 Religion when blessing a shared meal. Her paladins gain +1 Persuasion when negotiating a community's shared duties. The DM can discover both bonuses through the patron query and see them on settled rolls.

Release steps:
Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host. The migrate job reseeds gods content in production Postgres before the script recreates the server, agent and worker from the release. The command makes no paid provider calls.
