Feature: M29 combat reactions — the real DM at the Beat-3 window

  Drives the real CombatAgent (Haiku, production gameplay model: caching="ephemeral",
  _strict_tool_schema=False, max_tool_steps=5) against a real Postgres testcontainer.
  Two things no schema walk can give: a real Haiku turn filling declare_phase's
  discriminated union, and the restored Beat-3 interrupt loop end to end — the DM
  narrates a held enemy blow, the player shouts a reaction in conversational time,
  and the reaction changes the damage before it is written.
  Runs only when ANTHROPIC_API_KEY is set (pre-sprint-close schedule — see ADR 0003).

  Scenario: A real Haiku turn fills the declaration union
    Given a rogue in combat against a mawling
    When the player says "I cut at the mawling with my longsword!"
    Then the agent calls the "declare_phase" tool
    And every declaration it sent is a well-formed variant of the declaration union
    And no turn was truncated at the tool-step ceiling

  Scenario: A reaction at the post-roll window halves the blow before it is written
    Given a rogue in combat against a mawling
    When the player says "I cut at the mawling with my longsword!"
    And the DM brings the mawling's blow forward until the strike is rolled
    And the player says "I twist with it — Uncanny Dodge!"
    Then the agent calls "activate" with the id "rogue_uncanny_dodge"
    And the reaction packet reports the damage halved
    And the halved figure is what reached hp_current
    And no turn was truncated at the tool-step ceiling

  Scenario: The truncation guard reds when the ceiling is lowered
    Given a rogue in combat against a mawling
    And the session's tool-step ceiling is lowered to 1
    When the player says "I cut at the mawling with my longsword!"
    Then the turn was truncated at the tool-step ceiling
