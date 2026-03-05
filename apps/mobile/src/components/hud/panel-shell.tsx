import { useCallback, useEffect } from "react";
import { Pressable, StyleSheet, useWindowDimensions, View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withTiming,
  runOnJS,
} from "react-native-reanimated";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { useStore } from "zustand";

import { panelStore, type PanelTab } from "@/stores/panel-store";
import { playSfx } from "@/audio/sfx-player";
import { hapticPanelOpen } from "@/audio/haptics";
import { BrandColors, FontFamilies, Spacing, Radius, AnimationPresets } from "@/constants/theme";
import { ThemedText } from "@/components/themed-text";

import { CharacterSheetPanel } from "./panels/character-sheet-panel";
import { InventoryPanel } from "./panels/inventory-panel";
import { QuestLogPanel } from "./panels/quest-log-panel";
import { MapPanel } from "./panels/map-panel";

const DISMISS_THRESHOLD = 100;
const VELOCITY_THRESHOLD = 500;

const TABS: { key: PanelTab; label: string }[] = [
  { key: "character", label: "CHARACTER" },
  { key: "inventory", label: "INVENTORY" },
  { key: "quests", label: "QUESTS" },
  { key: "map", label: "MAP" },
];

function PanelTabBar() {
  const activeTab = useStore(panelStore, (s) => s.activeTab);

  return (
    <View style={styles.tabBar}>
      {TABS.map((tab) => (
        <Pressable
          key={tab.key}
          style={styles.tabItem}
          onPress={() => panelStore.getState().setActiveTab(tab.key)}
        >
          <ThemedText
            style={[
              styles.tabLabel,
              activeTab === tab.key ? styles.tabLabelActive : styles.tabLabelInactive,
            ]}
          >
            {tab.label}
          </ThemedText>
        </Pressable>
      ))}
    </View>
  );
}

function PanelContent() {
  const activeTab = useStore(panelStore, (s) => s.activeTab);

  switch (activeTab) {
    case "character":
      return <CharacterSheetPanel />;
    case "inventory":
      return <InventoryPanel />;
    case "quests":
      return <QuestLogPanel />;
    case "map":
      return <MapPanel />;
  }
}

export function PanelShell() {
  const isOpen = useStore(panelStore, (s) => s.isOpen);
  const { height: screenHeight } = useWindowDimensions();
  const sheetMaxHeight = screenHeight * 0.75;
  const translateY = useSharedValue(sheetMaxHeight);
  const scrimOpacity = useSharedValue(0);

  const close = useCallback(() => {
    panelStore.getState().closePanel();
    playSfx("menu_close");
  }, []);

  useEffect(() => {
    if (isOpen) {
      translateY.value = withSpring(0, AnimationPresets.overlaySpring);
      scrimOpacity.value = withTiming(1, { duration: 200 });
      hapticPanelOpen();
      playSfx("menu_open");
    } else {
      translateY.value = withSpring(sheetMaxHeight, AnimationPresets.overlaySpring);
      scrimOpacity.value = withTiming(0, { duration: 150 });
    }
  }, [isOpen, sheetMaxHeight, translateY, scrimOpacity]);

  const panGesture = Gesture.Pan()
    .onUpdate((e) => {
      if (e.translationY > 0) {
        translateY.value = e.translationY;
      }
    })
    .onEnd((e) => {
      if (e.translationY > DISMISS_THRESHOLD || e.velocityY > VELOCITY_THRESHOLD) {
        translateY.value = withSpring(sheetMaxHeight, AnimationPresets.overlaySpring);
        scrimOpacity.value = withTiming(0, { duration: 150 });
        runOnJS(close)();
      } else {
        translateY.value = withSpring(0, AnimationPresets.overlaySpring);
      }
    });

  const sheetStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: translateY.value }],
  }));

  const scrimStyle = useAnimatedStyle(() => ({
    opacity: scrimOpacity.value * 0.6,
  }));

  if (!isOpen) return null;

  return (
    <View style={styles.overlay}>
      <Pressable style={StyleSheet.absoluteFill} onPress={close}>
        <Animated.View style={[styles.scrim, scrimStyle]} />
      </Pressable>

      <GestureDetector gesture={panGesture}>
        <Animated.View style={[styles.sheet, { maxHeight: sheetMaxHeight }, sheetStyle]}>
          <View style={styles.handleRow}>
            <View style={styles.handle} />
            <Pressable style={styles.closeButton} onPress={close} hitSlop={12}>
              <ThemedText style={styles.closeText}>{"\u2715"}</ThemedText>
            </Pressable>
          </View>

          <PanelTabBar />

          <View style={styles.contentArea}>
            <PanelContent />
          </View>
        </Animated.View>
      </GestureDetector>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: "flex-end",
    zIndex: 100,
  },
  scrim: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BrandColors.void,
  },
  sheet: {
    backgroundColor: BrandColors.ink,
    borderTopWidth: 1,
    borderTopColor: BrandColors.charcoal,
    borderTopLeftRadius: Radius.lg,
    borderTopRightRadius: Radius.lg,
    overflow: "hidden",
  },
  handleRow: {
    alignItems: "center",
    paddingTop: Spacing.two,
    paddingBottom: Spacing.one,
    paddingHorizontal: Spacing.three,
    position: "relative",
  },
  handle: {
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: BrandColors.slate,
  },
  closeButton: {
    position: "absolute",
    right: Spacing.three,
    top: Spacing.two,
  },
  closeText: {
    fontSize: 16,
    color: BrandColors.ash,
  },
  tabBar: {
    flexDirection: "row",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: BrandColors.charcoal,
    paddingHorizontal: Spacing.two,
  },
  tabItem: {
    flex: 1,
    alignItems: "center",
    paddingVertical: Spacing.two,
  },
  tabLabel: {
    fontFamily: FontFamilies.system,
    fontSize: 10,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  tabLabelActive: {
    color: BrandColors.hollow,
  },
  tabLabelInactive: {
    color: BrandColors.ash,
  },
  contentArea: {
    flex: 1,
    minHeight: 200,
  },
});
