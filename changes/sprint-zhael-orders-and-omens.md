Bump: minor

Marshals can now give orders in a fight. Direct Strike, Reposition, Coordinated Assault, Field Medic Order and Sacrifice Play can be declared in combat. The engine checks each order's targets and charges its cost, and the DM narrates what the order does.

A Zhael marshal's order steadies the ally it names (Moment to Rally). Once per encounter, the first ally a Zhael marshal orders, by Interceding Order or any of the five commands, gains +1 on their next saving throw of any kind, death saves included. An unused +1 fades when the fight ends.

Zhael bards and diplomats hear the threads before they speak (Foretold Words). Once per NPC each session, they learn the exact DC of their next social check against that NPC, and that DC holds even if the NPC's mood shifts before they try.

Release steps:
- Apply migration 066_zhael_foretold_words.sql (adds the zhael_foretold_words table) with the normal migrate step, before deploying the agent and server. It is free and writes the production schema.
