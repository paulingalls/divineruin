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

  Scenario Outline: Active stages deliver their scene guidance
    Given an active Greyvale warm session at stage <stage>
    Then its scene hint reaches the silent player
    Examples:
      | stage |
      | 0     |
      | 1     |
      | 2     |

  Scenario: Every authored finish line reaches the DM
    Given a warm session walking the complete quest corpus
    Then every stage renders its finish line and the surfaced combat starts

  Scenario: Unknown authored conditions fail loudly
    Given a warm session walking the complete quest corpus
    Then an unknown condition fails the warm refresh loudly

  Scenario Outline: Winning the named fight completes First Blood once
    Given a First Blood fight ending through <route>
    When the fight ends
    Then First Blood rewards and the dungeon objective reach the DM once
    Examples:
      | route         |
      | end_combat    |
      | resolve_phase |

  Scenario Outline: Other combat endings leave First Blood active
    Given a First Blood exclusion <case>
    When the fight ends
    Then First Blood stays unpaid
    Examples:
      | case          |
      | wrong         |
      | defeat        |
      | fled          |
      | deescalated   |
      | standing      |
      | dead          |
      | progressed    |

  Scenario Outline: Authored exits support a round trip
    Given a walker at <source>
    When they take <outbound> to <destination>
    Then <return_key> returns them to <source> with <outbound> leading to <destination>
    Examples:
      | source               | outbound  | destination         | return_key |
      | accord_dockside      | southeast | emris_study         | out        |
      | accord_guild_hall    | up        | torin_quarters      | out        |
      | accord_forge         | up        | grimjaw_quarters    | out        |
      | millhaven            | west      | yanna_farmhouse     | out        |
      | accord_market_square | northeast | greyvale_south_road | south      |

  Scenario Outline: Rest restores only the present party at a safe inn
    Given a wounded resting party at <location>
    When the host requests a <kind> rest
    Then the resting party and identified client snapshots agree for <kind>

    Examples:
      | location                   | kind  |
      | millhaven_inn              | short |
      | millhaven_inn              | long  |
      | accord_hearthstone_tavern   | long  |

  Scenario Outline: Rest refuses without changing anyone
    Given a wounded resting party at millhaven_inn
    When the host requests rest with <obstacle>
    Then rest refuses without writes or client updates

    Examples:
      | obstacle       |
      | combat         |
      | null_danger    |
      | remote_actor   |
      | street         |
      | danger         |
      | tier           |
      | no_parent      |
      | two_parents    |
      | malformed_pool |
      | missing_hp     |

  Scenario: A lone player rests at the inn
    Given a wounded resting party at millhaven_inn
    And the resting player is alone
    When the host requests a long rest
    Then the resting party and identified client snapshots agree for long

  Scenario: Two doors to the same settlement identify one anchor
    Given a wounded resting party at millhaven_inn
    And two doors connect the inn to the same settlement
    When the host requests a long rest
    Then the resting party and identified client snapshots agree for long

  Scenario: Finding the journal puts it in hand and finishes the search
    Given a journal search at the ruins
    When the player searches the research station
    Then the journal and its quest rewards arrive once

  Scenario Outline: Entering a previously searched item stage
    Given an earlier journal discovery with <holding>
    When the quest enters the journal stage
    Then its final stage is <stage>

    Examples:
      | holding   | stage |
      | retained  | 4     |
      | removed   | 3     |
      | unflagged | 3     |

  Scenario: Item stages require all items from one party member
    Given a private search requiring two items
    Then one find cannot finish it and the second finishes it once

  Scenario: Entering satisfied item stages chains to the next objective
    Given a journal search at the ruins
    Then starting an already satisfied item quest pays each stage once
