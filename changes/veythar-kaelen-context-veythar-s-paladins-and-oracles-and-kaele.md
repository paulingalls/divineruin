Bump: minor

Veythar’s paladins gain +1 Religion when interpreting an ancient oath. His oracles gain +1 Arcana when interpreting a remembered vision. Kaelen’s clerics gain +1 Religion when conducting a fallen soldier’s funeral rites. His oracles gain +1 History when interpreting a martial omen.

Release steps:

- Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host. The migrate job reseeds the gods catalog before the server, agent and worker restart. This writes to production and makes no paid provider calls.
