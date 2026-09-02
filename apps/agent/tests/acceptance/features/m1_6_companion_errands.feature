Feature: M1.6 companion errands — dispatch + worker resolution end-to-end

  Drives the real DispatchAgent (Haiku, production gameplay model) against a real
  Postgres testcontainer via the LiveKit test framework. Errands are reached in the
  dispatch scene through the begin_activity/resolve_activity verbs (M26 fold); errand
  templates come from the shared content/DB source (story-011). The worker resolution scenario
  exercises the real LLM narration path (TTS audio prerender is no-op'd — a paid
  external delivery step outside the errand seam). Runs only when ANTHROPIC_API_KEY
  is set (pre-sprint-close / test-creation schedule — see ADR 0003).

  Scenario: DM dispatches a companion on a scouting errand
    Given a player in the dispatch scene with companion Kael and a free companion slot
    When the player says "Send Kael to scout Millhaven for me"
    Then the agent calls the "begin_activity" tool
    And an in-progress companion errand row exists for the player

  Scenario: The worker resolves a due companion errand
    Given a dispatched companion errand that is due to resolve
    When the async worker resolves due activities
    Then the errand's stored outcome carries narration and decision options
