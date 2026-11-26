Bump: patch

Veythar’s rogues and spies gain +1 Investigation when searching for hidden information, including when they investigate a Still illusion or reroll a discovery with Lorekeeper’s Insight.

Release steps:

- During deploy, run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production host with the deployment’s established project and port inputs. The migrate job reseeds the gods catalog before the script recreates the server, agent and worker. This writes to production and makes no paid provider calls.
