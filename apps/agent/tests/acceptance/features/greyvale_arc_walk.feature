Feature: Engine driven Greyvale arrivals
  Scenario Outline: Arriving completes the road exactly once
    Given a road quest holder using <tool>
    When they arrive in Millhaven
    Then the road reward and next objective reach the DM
    And later arrivals leave rewards and unrelated stages unchanged
    Examples:
      | tool        |
      | move_player |
      | travel      |

  Scenario: Only the condition location completes a location stage
    Given private quests with different completion conditions
    When they arrive in Millhaven
    Then only the matching location condition advances
    And the target alone does not complete a location stage
