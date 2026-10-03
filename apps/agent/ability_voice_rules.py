"""Closed delivery policies for the authored ability corpus."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_data import CombatState

from communication_voice_rules import CommunicationKind, DeliveryRefused, can_hear, require_delivery, require_source


class DeliveryPolicy(StrEnum):
    BOTH = "both"
    NEITHER = "neither"
    SOURCE = "source"
    PREPARATION = "preparation"
    HEARING = "hearing"
    SPELL = "spell"


BOTH = frozenset(
    {
        "warrior_rallying_shout",
        "warrior_taunt",
        "warrior_war_cry",
        "guardian_rallying_defense",
        "guardian_taunt",
        "guardian_challenging_shout",
        "guardian_fortify",
        "spy_extract_information",
        "spy_plausible_deniability",
        "spy_double_agent",
        "spy_whisper_network",
        "bard_cutting_words",
        "bard_inspire",
        "bard_mass_inspire",
        "bard_dissonant_whisper",
        "bard_countercharm",
        "bard_song_of_rest",
        "bard_cutting_retort",
        "bard_mocking_flourish",
        "diplomat_de_escalate",
        "diplomat_cutting_words",
        "diplomat_inspire",
        "diplomat_objection",
        "diplomat_countercharm",
        "diplomat_mediators_presence",
        "diplomat_intimidating_authority",
        "diplomat_rumor_mill",
        "diplomat_alliance_broker",
        "diplomat_treaty",
        "diplomat_incite",
        "diplomat_sanctuary_of_words",
        "diplomat_undermine",
        "marshal_direct_strike",
        "marshal_reposition",
        "marshal_rally",
        "marshal_coordinated_assault",
        "marshal_interceding_order",
        "marshal_countermand",
        "marshal_overwatch",
        "marshal_exploit_opening",
        "marshal_war_cry",
        "marshal_field_medic_order",
        "marshal_grand_stratagem",
        "marshal_sacrifice_play",
        "marshal_inspire_defiance",
        "marshal_tactical_withdrawal",
    }
)

NEITHER = frozenset(
    {
        "warrior_devastating_strike",
        "warrior_shield_bash",
        "warrior_second_wind",
        "warrior_brace_for_impact",
        "warrior_opportunity_strike",
        "warrior_cleaving_blow",
        "warrior_precision_strike",
        "warrior_reckless_assault",
        "warrior_unstoppable_charge",
        "warrior_whirlwind",
        "warrior_iron_stance",
        "guardian_protective_strike",
        "guardian_shield_wall",
        "guardian_stand_your_ground",
        "guardian_intercept",
        "guardian_retaliating_shield",
        "guardian_body_block",
        "guardian_unbreakable",
        "guardian_avengers_mark",
        "guardian_living_fortress",
        "skirmisher_hit_and_run",
        "skirmisher_flanking_strike",
        "skirmisher_disengage",
        "skirmisher_momentum",
        "skirmisher_sidestep",
        "skirmisher_riposte",
        "skirmisher_hamstring",
        "skirmisher_dual_strike",
        "skirmisher_throwing_mastery",
        "skirmisher_tumbling_assault",
        "skirmisher_spring_attack",
        "skirmisher_whirlwind",
        "skirmisher_predators_pursuit",
        "skirmisher_evasive_sprint",
        "rogue_cunning_action",
        "rogue_precise_strike",
        "rogue_uncanny_dodge",
        "rogue_slippery",
        "rogue_dirty_trick",
        "rogue_quick_fingers",
        "rogue_smoke_bomb",
        "rogue_crippling_strike",
        "rogue_shadow_step",
        "rogue_exploit_weakness",
        "rogue_vanish",
        "rogue_blade_flurry",
        "spy_backstab",
        "spy_quick_change",
        "spy_slippery",
        "spy_poison_craft",
        "spy_misdirection",
        "spy_lip_reading",
        "spy_garrote",
        "spy_vanish_in_plain_sight",
        "spy_sleeper_strike",
        "mage_shield_spell",
        "druid_bark_skin",
        "druid_wild_shape",
        "cleric_shield_of_faith",
        "artificer_deploy_construct",
        "artificer_infuse_item",
        "seeker_detect_magic",
        "seeker_identify",
        "beastcaller_command_companion",
        "warden_shillelagh",
        "warden_guardian_strike",
        "warden_bark_skin",
        "oracle_fates_nudge",
        "paladin_divine_smite",
        "paladin_lay_on_hands",
        "paladin_shield_of_faith",
        "paladin_shield_bash",
        "paladin_zealous_charge",
        "paladin_cleansing_strike",
        "paladin_sanctified_ground",
        "paladin_commanding_presence",
        "whisper_suggestion",
        "whisper_mind_spike",
        "whisper_fog_of_mind",
        "whisper_redirect_attention",
        "whisper_thought_shield",
        "whisper_implant_doubt",
    }
)

SOURCE = frozenset(
    {
        "mage_counterspell",
        "oracle_shield_of_faith",
    }
)

PREPARATION = frozenset(
    {
        "spy_honeyed_words",
        "bard_silver_tongue",
        "diplomat_compelling_argument",
    }
)

HEARING = frozenset(
    {
        "guardian_inspiring_presence",
    }
)

SPELLS = {
    "mage_arcane_bolt": "arcane_bolt",
    "druid_thorn_whip": "primal_thorn_whip",
    "druid_healing_touch": "primal_healing_touch",
    "cleric_sacred_flame": "divine_sacred_flame",
    "cleric_heal_wounds": "divine_heal_wounds",
    "artificer_arcane_bolt": "arcane_bolt",
    "seeker_arcane_bolt": "arcane_bolt",
    "beastcaller_thorn_whip": "primal_thorn_whip",
    "beastcaller_healing_touch": "primal_healing_touch",
    "oracle_sacred_flame": "divine_sacred_flame",
    "paladin_sacred_flame": "divine_sacred_flame",
}

POLICIES: dict[str, DeliveryPolicy] = {
    **{id: DeliveryPolicy.BOTH for id in BOTH},
    **{id: DeliveryPolicy.NEITHER for id in NEITHER},
    **{id: DeliveryPolicy.SOURCE for id in SOURCE},
    **{id: DeliveryPolicy.PREPARATION for id in PREPARATION},
    **{id: DeliveryPolicy.HEARING for id in HEARING},
    **{id: DeliveryPolicy.SPELL for id in SPELLS},
}
CONTESTED = frozenset({"marshal_countermand", "spy_plausible_deniability", "diplomat_objection"})


def policy(ability_id: str) -> DeliveryPolicy:
    try:
        return POLICIES[ability_id]
    except KeyError as exc:
        raise ValueError(f"Unclassified ability delivery {ability_id!r}") from exc


def reaction_recipient(ability_id: str, window: dict | None) -> str:
    policy(ability_id)
    if not isinstance(window, dict) or window.get("stage") not in ("pre_roll", "post_roll"):
        raise ValueError("Malformed reaction delivery window")
    key = "actor_id" if ability_id in CONTESTED else "target_id"
    recipient = window.get(key)
    if not isinstance(recipient, str) or not recipient:
        raise ValueError(f"Reaction delivery window requires {key}")
    return recipient


def require_ability_delivery(
    ability_id: str,
    state: CombatState | None,
    speaker_id: str,
    recipient_ids: list[str],
    *,
    rows: dict | None = None,
) -> None:
    requirement = policy(ability_id)
    if requirement is DeliveryPolicy.SPELL:
        import spells
        from combat_voice_rules import guard_spell

        guard_spell(
            state,
            speaker_id,
            spells.get_spell(SPELLS[ability_id]),
            target_ids=recipient_ids if len(recipient_ids) > 1 else None,
            target_id=recipient_ids[0] if len(recipient_ids) == 1 else None,
        )
    elif requirement is DeliveryPolicy.BOTH:
        require_delivery(CommunicationKind.SPOKEN, state, speaker_id, recipient_ids, rows=rows)
    elif requirement in (DeliveryPolicy.SOURCE, DeliveryPolicy.PREPARATION):
        require_source(state, speaker_id, rows=rows)
    elif requirement is DeliveryPolicy.HEARING:
        for recipient_id in recipient_ids:
            if not can_hear(state, recipient_id, rows=rows):
                raise DeliveryRefused(f"{recipient_id} cannot hear the ability")


def reaction_effect_eligible(state: CombatState, head: dict, spend: dict) -> bool:
    requirement = policy(spend["ability_id"])
    if requirement not in (DeliveryPolicy.BOTH, DeliveryPolicy.HEARING):
        return True
    recipient = head["actor_id"] if spend["ability_id"] in CONTESTED else head["declaration"].get("target_id")
    return can_hear(state, recipient)
