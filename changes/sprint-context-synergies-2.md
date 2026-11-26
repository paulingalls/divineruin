Bump: minor

Syrath’s clerics gain +1 Religion when interpreting concealed devotional symbols. Syrath’s paladins gain +1 History when identifying oaths whose patron’s name was erased. Mortaen’s diplomats gain +1 Persuasion when negotiating the return of a body for burial, on both skill and social checks. Zhael’s artificers gain +1 to any skill check to repair a clock or timing mechanism. Zhael’s seekers gain +1 Investigation when comparing accounts of the same foretold event.

Veythar’s rogues and spies gain +1 Investigation when searching for hidden information, including when they investigate a Still illusion or reroll a discovery with Lorekeeper’s Insight.

Veythar’s paladins gain +1 Religion when interpreting an ancient oath. His oracles gain +1 Arcana when interpreting a remembered vision. Kaelen’s clerics gain +1 Religion when conducting a fallen soldier’s funeral rites. His oracles gain +1 History when interpreting a martial omen.

Release steps:

- Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host. The migrate job reseeds production gods content before the server, agent and worker are recreated, and the restart refreshes the check schema's tag list. This writes to production and makes no paid provider calls.
