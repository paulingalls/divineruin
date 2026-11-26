Bump: minor

Aelora’s oracles gain +1 Insight when interpreting a household omen, stacking with Hearthkeeper’s Bond when an ally is present. Aelora’s rogues gain +1 Persuasion on commerce checks, including negotiations with merchants. Thyra’s paladins gain +1 Religion when honoring a sacred grove, and her oracles gain +1 Nature when interpreting a seasonal omen.

Release steps:

- Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host as part of deploying the release. The migrate job reseeds production content before the server, agent, and worker are recreated. This writes to production and makes no paid provider calls.
