Bump: minor

Aelora's clerics gain +1 Religion when blessing a shared meal. Her paladins gain +1 Persuasion when negotiating a community's shared duties. The DM can discover both bonuses through the patron query and see them on settled rolls.

Aelora’s oracles gain +1 Insight when interpreting a household omen, stacking with Hearthkeeper’s Bond when an ally is present. Aelora’s rogues gain +1 Persuasion on commerce checks, including negotiations with merchants. Thyra’s paladins gain +1 Religion when honoring a sacred grove, and her oracles gain +1 Nature when interpreting a seasonal omen.

Nythera’s wardens gain +1 Survival to find shelter on unfamiliar coasts. Her diplomats gain +1 Persuasion to seek peaceful passage through unfamiliar ports, and her artificers gain +1 on any check to repair a vessel during a journey.

Orenthel’s artificers gain +1 on any check to repair equipment for a damaged sanctuary. His wardens gain +1 Nature to restore a blighted grove, and his diplomats gain +1 Persuasion to negotiate care for wounded enemies.

The DM passes a `synergy_context` tag on a skill or social check when the narrated moment matches a clause the player holds, and finds the player's tags through the patron query. A tag the player does not hold grants nothing and is reported as not applying.

Release steps:

- Run `DEPLOY_ENV_FILE=/absolute/private/production.env bash scripts/deploy-up.sh` from the release checkout on the production deployment host. The migrate job reseeds production gods content before the server, agent and worker are recreated. This writes to production and makes no paid provider calls.
