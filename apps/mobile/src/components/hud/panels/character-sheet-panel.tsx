import { ScrollView, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { characterStore } from "@/stores/character-store";
import { panelStore } from "@/stores/panel-store";
import { BrandColors, FontStyles, Spacing } from "@/constants/theme";

const ATTR_ABBREV: Record<string, string> = {
  strength: "STR",
  dexterity: "DEX",
  constitution: "CON",
  intelligence: "INT",
  wisdom: "WIS",
  charisma: "CHA",
};

const ATTR_ORDER = [
  "strength",
  "dexterity",
  "constitution",
  "intelligence",
  "wisdom",
  "charisma",
] as const;

const SKILL_MAP: Record<string, { stat: string; group: string }> = {
  athletics: { stat: "strength", group: "Physical" },
  acrobatics: { stat: "dexterity", group: "Physical" },
  stealth: { stat: "dexterity", group: "Physical" },
  sleight_of_hand: { stat: "dexterity", group: "Physical" },
  arcana: { stat: "intelligence", group: "Mental" },
  history: { stat: "intelligence", group: "Mental" },
  investigation: { stat: "intelligence", group: "Mental" },
  nature: { stat: "intelligence", group: "Mental" },
  religion: { stat: "intelligence", group: "Mental" },
  animal_handling: { stat: "wisdom", group: "Mental" },
  insight: { stat: "wisdom", group: "Mental" },
  medicine: { stat: "wisdom", group: "Mental" },
  perception: { stat: "wisdom", group: "Mental" },
  survival: { stat: "wisdom", group: "Mental" },
  deception: { stat: "charisma", group: "Social" },
  intimidation: { stat: "charisma", group: "Social" },
  performance: { stat: "charisma", group: "Social" },
  persuasion: { stat: "charisma", group: "Social" },
};

const SKILL_GROUPS = (["Physical", "Mental", "Social"] as const).map((group) => ({
  group,
  skills: Object.entries(SKILL_MAP).filter(([, s]) => s.group === group),
}));

function calcModifier(value: number): number {
  return Math.floor((value - 10) / 2);
}

function formatModifier(mod: number): string {
  if (mod > 0) return `+${mod}`;
  if (mod < 0) return `${mod}`;
  return "0";
}

function modColor(mod: number): string {
  if (mod > 0) return BrandColors.hollow;
  if (mod < 0) return BrandColors.ember;
  return BrandColors.ash;
}

export function CharacterSheetPanel() {
  const character = useStore(characterStore, (s) => s.character);
  const detail = useStore(panelStore, (s) => s.characterDetail);

  if (!character) {
    return (
      <View style={styles.empty}>
        <ThemedText style={styles.emptyText}>No character data</ThemedText>
      </View>
    );
  }

  const hpRatio = character.hpMax > 0 ? character.hpCurrent / character.hpMax : 0;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* Portrait */}
      <View style={styles.portraitRow}>
        <CachedImage uri={character.portraitUrl} style={styles.portraitImage} borderRadius={40} />
      </View>
      {/* Header */}
      <ThemedText style={styles.name}>{character.name}</ThemedText>
      <ThemedText style={styles.classLevel}>
        LEVEL {character.level} {"\u00B7"} {character.className.toUpperCase()}
        {character.race ? ` \u00B7 ${character.race.toUpperCase()}` : ""}
      </ThemedText>
      {character.deity && character.deity !== "none" ? (
        <ThemedText style={styles.deityText}>
          Patron: {character.deity.charAt(0).toUpperCase() + character.deity.slice(1)}
        </ThemedText>
      ) : null}

      {/* HP */}
      <View style={styles.hpSection}>
        <View style={styles.hpNumbers}>
          <ThemedText style={styles.hpCurrent}>{character.hpCurrent}</ThemedText>
          <ThemedText style={styles.hpMax}> / {character.hpMax}</ThemedText>
        </View>
        <View style={styles.hpTrack}>
          <View
            style={[
              styles.hpFill,
              {
                width: `${hpRatio * 100}%` as unknown as number,
                backgroundColor: hpRatio < 0.3 ? BrandColors.ember : BrandColors.parchment,
              },
            ]}
          />
        </View>
      </View>

      {detail && (
        <>
          {/* AC */}
          <View style={styles.acRow}>
            <ThemedText style={styles.acLabel}>AC</ThemedText>
            <ThemedText style={styles.acValue}>{detail.ac}</ThemedText>
          </View>

          {/* Stats grid */}
          <View style={styles.statsGrid}>
            {ATTR_ORDER.map((attr) => {
              const value = detail.attributes[attr];
              const mod = calcModifier(value);
              return (
                <View key={attr} style={styles.statCell}>
                  <ThemedText style={styles.statAbbrev}>{ATTR_ABBREV[attr]}</ThemedText>
                  <ThemedText style={styles.statValue}>{value}</ThemedText>
                  <ThemedText style={[styles.statMod, { color: modColor(mod) }]}>
                    {formatModifier(mod)}
                  </ThemedText>
                </View>
              );
            })}
          </View>

          {/* Skills by group */}
          {SKILL_GROUPS.map(({ group, skills }) => (
            <View key={group} style={styles.skillGroup}>
              <ThemedText style={styles.skillGroupLabel}>{group.toUpperCase()}</ThemedText>
              {skills.map(([skillName, { stat }]) => {
                const statVal = detail.attributes[stat as keyof typeof detail.attributes];
                const mod = calcModifier(statVal);
                const isProficient = detail.proficiencies.includes(skillName);
                const displayName = skillName.replace(/_/g, " ");
                return (
                  <View key={skillName} style={styles.skillRow}>
                    <View style={styles.skillLeft}>
                      {isProficient && <View style={styles.profDot} />}
                      <ThemedText style={styles.skillName}>{displayName}</ThemedText>
                    </View>
                    <ThemedText style={[styles.skillMod, { color: modColor(mod) }]}>
                      {formatModifier(mod)}
                    </ThemedText>
                  </View>
                );
              })}
            </View>
          ))}

          {/* Equipment */}
          <View style={styles.section}>
            <ThemedText style={styles.sectionLabel}>EQUIPMENT</ThemedText>
            {detail.equipment.main_hand && (
              <ThemedText style={styles.equipItem}>
                {typeof detail.equipment.main_hand.name === "string"
                  ? detail.equipment.main_hand.name
                  : "Unknown"}
              </ThemedText>
            )}
            {detail.equipment.armor && (
              <ThemedText style={styles.equipItem}>
                {typeof detail.equipment.armor.name === "string"
                  ? detail.equipment.armor.name
                  : "Unknown"}
              </ThemedText>
            )}
            {detail.equipment.shield && (
              <ThemedText style={styles.equipItem}>
                {typeof detail.equipment.shield.name === "string"
                  ? detail.equipment.shield.name
                  : "Unknown"}
              </ThemedText>
            )}
          </View>

          {/* Gold */}
          <View style={styles.goldRow}>
            <ThemedText style={styles.goldLabel}>GOLD</ThemedText>
            <ThemedText style={styles.goldValue}>{detail.gold}</ThemedText>
          </View>

          {/* Divine Favor */}
          {detail.divineFavor && (
            <View style={styles.section}>
              <ThemedText style={styles.sectionLabel}>DIVINE FAVOR</ThemedText>
              <ThemedText style={styles.equipItem}>
                {detail.divineFavor.patron} — {detail.divineFavor.level}/{detail.divineFavor.max}
              </ThemedText>
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { padding: Spacing.three, paddingBottom: Spacing.five, alignItems: "stretch" },
  portraitRow: { alignItems: "center", marginBottom: Spacing.two },
  portraitImage: { width: 80, height: 80 },
  empty: { flex: 1, justifyContent: "center", alignItems: "center" },
  emptyText: { color: BrandColors.ash, ...FontStyles.system, fontSize: 12 },
  name: {
    ...FontStyles.display,
    fontSize: 22,
    color: BrandColors.parchment,
  },
  classLevel: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.ash,
    letterSpacing: 2,
    marginTop: 2,
  },
  deityText: {
    ...FontStyles.bodyLight,
    fontSize: 12,
    color: BrandColors.divine,
    marginTop: 2,
  },
  hpSection: { marginTop: Spacing.three },
  hpNumbers: { flexDirection: "row", alignItems: "baseline" },
  hpCurrent: { ...FontStyles.system, fontSize: 32, color: BrandColors.parchment },
  hpMax: { ...FontStyles.system, fontSize: 18, color: BrandColors.ash },
  hpTrack: {
    height: 4,
    backgroundColor: BrandColors.charcoal,
    borderRadius: 2,
    overflow: "hidden",
    marginTop: 4,
  },
  hpFill: { height: 4, borderRadius: 2 },
  acRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
    marginTop: Spacing.three,
  },
  acLabel: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.ash,
    letterSpacing: 2,
  },
  acValue: { ...FontStyles.system, fontSize: 18, color: BrandColors.parchment },
  statsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: Spacing.three,
    gap: Spacing.two,
  },
  statCell: {
    width: "30%",
    alignItems: "center",
    paddingVertical: Spacing.two,
  },
  statAbbrev: { ...FontStyles.systemLight, fontSize: 9, color: BrandColors.ash },
  statValue: { ...FontStyles.system, fontSize: 24, color: BrandColors.parchment },
  statMod: { ...FontStyles.system, fontSize: 11 },
  skillGroup: { marginTop: Spacing.three },
  skillGroupLabel: {
    ...FontStyles.system,
    fontSize: 9,
    color: BrandColors.ash,
    letterSpacing: 2,
    marginBottom: 4,
  },
  skillRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 3,
  },
  skillLeft: { flexDirection: "row", alignItems: "center", gap: 6 },
  profDot: {
    width: 5,
    height: 5,
    borderRadius: 2.5,
    backgroundColor: BrandColors.hollow,
  },
  skillName: { ...FontStyles.body, fontSize: 14, color: BrandColors.bone },
  skillMod: { ...FontStyles.system, fontSize: 12 },
  section: { marginTop: Spacing.three },
  sectionLabel: {
    ...FontStyles.system,
    fontSize: 9,
    color: BrandColors.ash,
    letterSpacing: 2,
    marginBottom: 4,
  },
  equipItem: {
    ...FontStyles.body,
    fontSize: 13,
    color: BrandColors.bone,
    marginBottom: 2,
  },
  goldRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
    marginTop: Spacing.three,
  },
  goldLabel: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.ash,
    letterSpacing: 2,
  },
  goldValue: { ...FontStyles.system, fontSize: 18, color: BrandColors.divine },
});
