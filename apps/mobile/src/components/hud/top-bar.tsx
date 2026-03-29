import { useEffect, useRef, useCallback, type ReactNode } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { useStore } from "zustand";
import { MaterialCommunityIcons } from "@expo/vector-icons";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Spacing, Radius } from "@/constants/theme";
import { characterStore } from "@/stores/character-store";
import { sessionStore } from "@/stores/session-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore, type PanelTab } from "@/stores/panel-store";
import { API_BASE } from "@/utils/api";

export interface TopBarProps {
  mode: "home" | "session";
  /** Connection state string from LiveKit (session mode only) */
  connectionState?: string;
  trailing?: ReactNode;
}

const VOICE_DOT_GLOW = {
  shadowColor: BrandColors.hollow,
  shadowOffset: { width: 0, height: 0 },
  shadowOpacity: 0.8,
  shadowRadius: 4,
} as const;

function VoiceStateIndicator({ connectionState }: { connectionState: string }) {
  const color =
    connectionState === "connected"
      ? BrandColors.hollow
      : connectionState === "disconnected"
        ? BrandColors.ember
        : BrandColors.slate;

  return (
    <View style={styles.voiceGroup}>
      <View
        style={[
          styles.voiceDot,
          { backgroundColor: color },
          connectionState === "connected" ? VOICE_DOT_GLOW : undefined,
        ]}
      />
      {connectionState === "connected" && <ThemedText style={styles.liveLabel}>LIVE</ThemedText>}
    </View>
  );
}

function StatusEffectIcons() {
  const statusEffects = useStore(hudStore, (s) => s.statusEffects);

  if (statusEffects.length === 0) return null;

  return (
    <View style={styles.statusEffects}>
      {statusEffects.map((effect) => (
        <Animated.View
          key={effect.id}
          testID={`status-effect-${effect.id}`}
          entering={FadeIn.duration(200)}
          exiting={FadeOut.duration(200)}
          style={[
            styles.statusDot,
            {
              backgroundColor: effect.category === "buff" ? BrandColors.hollow : BrandColors.ember,
            },
          ]}
        />
      ))}
    </View>
  );
}

function QuestObjectiveStrip() {
  const activeObjective = useStore(hudStore, (s) => s.activeObjective);
  const visible = useStore(hudStore, (s) => s.questObjectiveVisible);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (activeObjective && visible) {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        hudStore.getState().setQuestObjectiveVisible(false);
      }, 10000);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [activeObjective, visible]);

  const dismiss = useCallback(() => {
    hudStore.getState().setQuestObjectiveVisible(false);
  }, []);

  if (!activeObjective || !visible) return null;

  return (
    <Pressable onPress={dismiss} style={styles.questStrip}>
      <ThemedText style={styles.questObjective} numberOfLines={1}>
        {"\u25B8"} {activeObjective.objective}
      </ThemedText>
    </Pressable>
  );
}

const PANEL_ICONS: {
  tab: PanelTab;
  icon: React.ComponentProps<typeof MaterialCommunityIcons>["name"];
}[] = [
  { tab: "character", icon: "shield-sword-outline" },
  { tab: "inventory", icon: "bag-personal-outline" },
  { tab: "quests", icon: "script-text-outline" },
  { tab: "map", icon: "compass-outline" },
];

function PanelAccessIcons() {
  const activeTab = useStore(panelStore, (s) => s.activeTab);
  const isOpen = useStore(panelStore, (s) => s.isOpen);

  return (
    <View style={styles.panelIcons}>
      {PANEL_ICONS.map(({ tab, icon }) => (
        <Pressable key={tab} hitSlop={8} onPress={() => panelStore.getState().openPanel(tab)}>
          <MaterialCommunityIcons
            name={icon}
            size={22}
            color={isOpen && activeTab === tab ? BrandColors.hollow : BrandColors.ash}
          />
        </Pressable>
      ))}
    </View>
  );
}

function CharacterIdentity({ trailing }: { trailing?: ReactNode }) {
  const character = useStore(characterStore, (s) => s.character);

  if (!character) return null;

  return (
    <View style={styles.identityRow}>
      <CachedImage
        uri={
          character.portraitUrl ? `${API_BASE}${character.portraitUrl.replace(/^"|"$/g, "")}` : null
        }
        style={styles.portrait}
        borderRadius={Radius.sm}
      />
      <ThemedText variant="label" numberOfLines={1} style={styles.characterName}>
        {character.name}
      </ThemedText>
      {trailing}
    </View>
  );
}

function SessionDetails() {
  const locationContext = useStore(sessionStore, (s) => s.locationContext);

  const locationLabel = locationContext
    ? `${locationContext.region ? locationContext.region.toUpperCase() + " \u00B7 " : ""}${locationContext.locationName.toUpperCase()}`
    : "";

  return (
    <>
      <View style={styles.row}>
        {locationLabel ? (
          <ThemedText style={styles.locationLabel} numberOfLines={1}>
            {locationLabel}
          </ThemedText>
        ) : (
          <View />
        )}
        <StatusEffectIcons />
      </View>
      <QuestObjectiveStrip />
    </>
  );
}

export function TopBar({ mode, connectionState, trailing }: TopBarProps) {
  const isSession = mode === "session";

  return (
    <View testID="top-bar" style={styles.container}>
      <CharacterIdentity trailing={trailing} />
      <View style={styles.row}>
        <PanelAccessIcons />
        {isSession && connectionState && <VoiceStateIndicator connectionState={connectionState} />}
      </View>
      {isSession && <SessionDetails />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: `${BrandColors.ink}D9`,
    borderBottomWidth: 1,
    borderBottomColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
    gap: Spacing.two,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  identityRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
  },
  portrait: {
    width: 36,
    height: 36,
  },
  characterName: {
    flex: 1,
    ...FontStyles.displayRegular,
    fontSize: 18,
    color: BrandColors.parchment,
  },
  panelIcons: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.three,
  },
  voiceGroup: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  voiceDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  liveLabel: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.hollow,
    letterSpacing: 1,
  },
  locationLabel: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.ash,
    letterSpacing: 2,
    textTransform: "uppercase",
    flexShrink: 1,
  },
  statusEffects: {
    flexDirection: "row",
    gap: 3,
  },
  statusDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
  },
  questStrip: {
    marginTop: -4,
  },
  questObjective: {
    ...FontStyles.bodyLight,
    fontSize: 13,
    color: `${BrandColors.bone}B3`,
  },
});
