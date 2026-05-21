Feature: M1.5 training cycle — DM training agent end-to-end

  Drives the real TrainingAgent (Haiku, production gameplay model) against a real
  Postgres testcontainer via the LiveKit test framework. Training tools live in
  TrainingAgent (story-011), reached when the player enters the training hall.
  Runs only when ANTHROPIC_API_KEY is set (pre-sprint-close / test-creation
  schedule — see ADR 0003).

  Scenario: Player initiates a training cycle
    Given a player at the training hall with no active training
    When the player says "What can I learn here? I'm interested in combat fundamentals"
    And the player says "Yes, let's begin the Combat Fundamentals training now"
    Then the agent calls the "initiate_training_cycle" tool
    And the agent narrates that the training has begun

  Scenario: Player resolves the midpoint decision
    Given a player at the training hall awaiting a midpoint decision
    When the player says "I'll take the aggressive stance"
    Then the agent calls the "resolve_training_midpoint" tool
    And the agent narrates the training continuing

  Scenario: Player cannot start a second cycle while one is in progress
    Given a player at the training hall with a cycle already in progress
    When the player says "Let's begin the Combat Fundamentals training right now"
    Then the agent calls the "initiate_training_cycle" tool
    And the agent narrates that a cycle is already in progress
