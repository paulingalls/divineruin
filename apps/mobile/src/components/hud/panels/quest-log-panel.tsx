import { useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { panelStore, type QuestView } from "@/stores/panel-store";
import { BrandColors, FontStyles, Spacing } from "@/constants/theme";

function QuestRow({ quest }: { quest: QuestView }) {
  const [expanded, setExpanded] = useState(false);
  const [hintIndex, setHintIndex] = useState(0);
  const [hintVisible, setHintVisible] = useState(false);

  const currentStage = quest.stages[quest.currentStage];
  const hasHints = quest.hints.length > 0;

  return (
    <View style={styles.questRow}>
      <Pressable onPress={() => setExpanded(!expanded)} style={styles.questHeader}>
        <View style={styles.questHeaderLeft}>
          <ThemedText style={styles.questName}>{quest.questName}</ThemedText>
          <ThemedText style={styles.currentStageName}>{currentStage.name}</ThemedText>
        </View>
        <ThemedText style={styles.chevron}>{expanded ? "\u25B4" : "\u25BE"}</ThemedText>
      </Pressable>

      {expanded && (
        <View style={styles.questExpanded}>
          <ThemedText style={styles.objective}>{currentStage.objective}</ThemedText>

          {quest.stages.map((stage, i) => (
            <View key={stage.id} style={styles.stageRow}>
              {stage.completed ? (
                <ThemedText style={styles.checkmark}>{"\u2713"}</ThemedText>
              ) : i === quest.currentStage ? (
                <ThemedText style={styles.currentDot}>{"\u25B8"}</ThemedText>
              ) : (
                <ThemedText style={styles.futureDot}>{"\u25CB"}</ThemedText>
              )}
              <ThemedText
                style={[
                  styles.stageName,
                  stage.completed && styles.stageCompleted,
                  i === quest.currentStage && styles.stageCurrent,
                ]}
              >
                {stage.name}
              </ThemedText>
            </View>
          ))}

          {hasHints && (
            <Pressable
              onPress={() => {
                if (hintVisible && hintIndex < quest.hints.length - 1) {
                  setHintIndex(hintIndex + 1);
                } else {
                  setHintVisible(!hintVisible);
                  setHintIndex(0);
                }
              }}
              style={styles.hintButton}
            >
              <ThemedText style={styles.hintButtonText}>
                {hintVisible
                  ? hintIndex < quest.hints.length - 1
                    ? "Next Hint"
                    : "Hide Hints"
                  : "Show Hint"}
              </ThemedText>
            </Pressable>
          )}
          {hintVisible && hasHints && (
            <ThemedText style={styles.hintText}>{quest.hints[hintIndex]}</ThemedText>
          )}
        </View>
      )}
    </View>
  );
}

export function QuestLogPanel() {
  const quests = useStore(panelStore, (s) => s.quests);
  const [showCompleted, setShowCompleted] = useState(false);

  const active = useMemo(() => quests.filter((q) => q.status === "active"), [quests]);
  const completed = useMemo(() => quests.filter((q) => q.status === "completed"), [quests]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <ThemedText style={styles.sectionLabel}>ACTIVE</ThemedText>
      {active.length === 0 ? (
        <ThemedText style={styles.emptyText}>No active quests</ThemedText>
      ) : (
        active.map((q) => <QuestRow key={q.questId} quest={q} />)
      )}

      {completed.length > 0 && (
        <>
          <Pressable
            onPress={() => setShowCompleted(!showCompleted)}
            style={styles.completedHeader}
          >
            <ThemedText style={styles.sectionLabel}>COMPLETED ({completed.length})</ThemedText>
            <ThemedText style={styles.chevron}>{showCompleted ? "\u25B4" : "\u25BE"}</ThemedText>
          </Pressable>
          {showCompleted &&
            completed.map((q) => (
              <View key={q.questId} style={styles.completedRow}>
                <ThemedText style={styles.completedName}>{q.questName}</ThemedText>
              </View>
            ))}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { padding: Spacing.three, paddingBottom: Spacing.five },
  sectionLabel: {
    ...FontStyles.system,
    fontSize: 9,
    color: BrandColors.ash,
    letterSpacing: 2,
    marginBottom: Spacing.two,
  },
  emptyText: {
    ...FontStyles.system,
    fontSize: 12,
    color: BrandColors.ash,
    paddingBottom: Spacing.three,
  },
  questRow: {
    marginBottom: Spacing.two,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: BrandColors.charcoal,
    paddingBottom: Spacing.two,
  },
  questHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  questHeaderLeft: { flex: 1 },
  questName: {
    ...FontStyles.body,
    fontSize: 15,
    color: BrandColors.parchment,
  },
  currentStageName: {
    ...FontStyles.systemLight,
    fontSize: 11,
    color: BrandColors.ash,
    marginTop: 2,
  },
  chevron: { color: BrandColors.ash, fontSize: 12 },
  questExpanded: { marginTop: Spacing.two, paddingLeft: Spacing.two },
  objective: {
    ...FontStyles.displayItalic,
    fontSize: 14,
    color: BrandColors.bone,
    marginBottom: Spacing.two,
  },
  stageRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 2,
  },
  checkmark: { color: BrandColors.hollow, fontSize: 12, width: 14, textAlign: "center" },
  currentDot: { color: BrandColors.hollowFaint, fontSize: 12, width: 14, textAlign: "center" },
  futureDot: { color: BrandColors.slate, fontSize: 10, width: 14, textAlign: "center" },
  stageName: {
    ...FontStyles.bodyLight,
    fontSize: 13,
    color: BrandColors.ash,
  },
  stageCompleted: { color: BrandColors.ash },
  stageCurrent: { color: BrandColors.bone },
  hintButton: { marginTop: Spacing.two },
  hintButtonText: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.hollowMuted,
  },
  hintText: {
    ...FontStyles.displayItalic,
    fontSize: 13,
    color: BrandColors.ash,
    marginTop: 4,
  },
  completedHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: Spacing.four,
  },
  completedRow: { paddingVertical: 4, paddingLeft: Spacing.two },
  completedName: {
    ...FontStyles.bodyLight,
    fontSize: 13,
    color: BrandColors.slate,
  },
});
