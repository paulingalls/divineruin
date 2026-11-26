Bump: minor

Nythera’s wardens gain +1 Survival to find shelter on unfamiliar coasts. Her diplomats gain +1 Persuasion to seek peaceful passage through unfamiliar ports, and her artificers gain +1 on any check to repair a vessel during a journey.

Orenthel’s artificers gain +1 on any check to repair equipment for a damaged sanctuary. His wardens gain +1 Nature to restore a blighted grove, and his diplomats gain +1 Persuasion to negotiate care for wounded enemies.

Release steps:

- Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host as part of deploying the release. The migrate job reseeds production content before the server, agent, and worker are recreated. This writes to production and makes no paid provider calls.
