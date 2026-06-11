export type {
  Location,
  LocationExit,
  LocationCondition,
  HiddenElement,
  SettlementSize,
  SettlementPersonality,
} from "./location";

export type { Npc, NpcKnowledge, NpcQuestKnowledge, NpcSchedule } from "./npc";

export type { Item, ItemEffect, ItemArtTemplate, ItemAttunement } from "./item";

export type { Recipe, MaterialReq, QualityBand } from "./recipe";

export type {
  Quest,
  QuestStage,
  QuestBranch,
  QuestCompletionCondition,
  QuestReward,
  QuestStageComplete,
  QuestFailureCondition,
} from "./quest";

export type { GameEvent, EventTrigger, EventEffects, EventEscalation } from "./event";

export type { Faction, ReputationTier } from "./faction";

export type {
  Archetype,
  ArchetypeHp,
  ArchetypeResource,
  PoolFormula,
  StartingSkills,
  HpCategory,
  ResourcePattern,
  MagicSource,
} from "./archetype";

export type { Ability, Cost, AbilityType } from "./ability";
export type { MentorVariant } from "./mentor_variant";
export type {
  RoleArchetype,
  RoleType,
  Disposition,
  Attributes,
  CombatAction,
  CombatStats,
  CombatVariant,
  ServiceCost,
  ArchetypeService,
} from "./role_archetype";
export type {
  Companion,
  TacticalPreference,
  RelationshipTier,
  AttackType,
  ScalingRules,
  AcThreshold,
  AttributeScalingStep,
  CompanionAttack,
  CompanionPassive,
  CompanionActive,
  CompanionReaction,
  ProgressionMilestone,
  RelationshipUnlocks,
} from "./companion";
export type { Spell, SpellSource, SpellTier } from "./spell";
export type {
  Milestone,
  MilestoneTier,
  MilestoneKind,
  SpecializationOption,
  Grant,
} from "./milestone";
