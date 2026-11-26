Bump: minor

Syrath’s clerics gain +1 Religion when interpreting concealed devotional symbols. Syrath’s paladins gain +1 History when identifying oaths whose patron’s name was erased. Mortaen’s diplomats gain +1 Persuasion when negotiating the return of a body for burial, on both skill and social checks. Zhael’s artificers gain +1 to any skill check to repair a clock or timing mechanism. Zhael’s seekers gain +1 Investigation when comparing accounts of the same foretold event.

Release steps:

- During deploy, run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production host with the deployment’s established project and port inputs. The migrate job reseeds the gods catalog before the script recreates the server, agent and worker. This writes to production and makes no paid provider calls.
