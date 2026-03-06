import { useEffect, useMemo, useRef } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { panelStore } from "@/stores/panel-store";
import { characterStore } from "@/stores/character-store";
import { MAP_LAYOUT_BY_ID } from "@/data/map-layout";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";

const CONTAINER_SIZE = 300;
const COORD_MAX = 1100;

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;

function scaleCoord(val: number): number {
  return (val / COORD_MAX) * CONTAINER_SIZE;
}

function ConnectionLine({
  x1,
  y1,
  x2,
  y2,
  color,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
}) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);

  return (
    <View
      style={[
        styles.connectionLine,
        {
          left: x1,
          top: y1,
          width: length,
          backgroundColor: color,
          transform: [{ rotate: `${angle}deg` }],
        },
      ]}
    />
  );
}

function usePulsingOpacity(minOpacity = 0.4, duration = 1000) {
  const opacity = useSharedValue(1);
  useEffect(() => {
    opacity.value = withRepeat(withTiming(minOpacity, { duration }), -1, true);
  }, [opacity, minOpacity, duration]);
  return useAnimatedStyle(() => ({ opacity: opacity.value }));
}

function PulsingNode({ x, y }: { x: number; y: number }) {
  const animStyle = usePulsingOpacity(0.4, 1000);
  return (
    <Animated.View
      style={[styles.nodeBase, styles.currentNode, { left: x - 12, top: y - 12 }, animStyle]}
    />
  );
}

function QuestDiamond({ x, y }: { x: number; y: number }) {
  const animStyle = usePulsingOpacity(0.3, 1200);
  return (
    <Animated.View
      style={[
        styles.questDiamond,
        { left: x - 5, top: y - 18, transform: [{ rotate: "45deg" }] },
        animStyle,
      ]}
    />
  );
}

export function MapPanel() {
  const mapProgress = useStore(panelStore, (s) => s.mapProgress);
  const quests = useStore(panelStore, (s) => s.quests);
  const currentLocationId = useStore(characterStore, (s) => s.character?.locationId);

  const scale = useSharedValue(1);
  const savedScale = useRef(1);
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);
  const savedTranslateX = useRef(0);
  const savedTranslateY = useRef(0);

  // Derive the quest target location from the current stage of the first active quest
  const questTargetLocationId = useMemo(() => {
    for (const q of quests) {
      if (q.status !== "active") continue;
      if (q.currentStage < 0 || q.currentStage >= q.stages.length) continue;
      const stage = q.stages[q.currentStage];
      if (stage.targetLocationId) return stage.targetLocationId;
    }
    return null;
  }, [quests]);

  const questDiamondCoords = useMemo(() => {
    if (!questTargetLocationId) return null;
    const layout = MAP_LAYOUT_BY_ID.get(questTargetLocationId);
    if (!layout) return null;
    return { x: scaleCoord(layout.x), y: scaleCoord(layout.y) };
  }, [questTargetLocationId]);

  const visitedSet = useMemo(
    () => new Set(mapProgress.filter((n) => n.visited).map((n) => n.locationId)),
    [mapProgress],
  );

  const connections = useMemo(() => {
    const lines: { from: string; to: string }[] = [];
    const seen = new Set<string>();
    for (const node of mapProgress) {
      if (!node.visited) continue;
      for (const connId of node.connections) {
        const key = [node.locationId, connId].sort().join("-");
        if (seen.has(key)) continue;
        seen.add(key);
        lines.push({ from: node.locationId, to: connId });
      }
    }
    return lines;
  }, [mapProgress]);

  // Regions for labels
  const regionLabels = useMemo(() => {
    const regions = new Map<string, { x: number; y: number; count: number }>();
    for (const node of mapProgress) {
      if (!node.visited) continue;
      const layout = MAP_LAYOUT_BY_ID.get(node.locationId);
      if (!layout) continue;
      const existing = regions.get(layout.region);
      if (existing) {
        existing.x += layout.x;
        existing.y += layout.y;
        existing.count += 1;
      } else {
        regions.set(layout.region, { x: layout.x, y: layout.y, count: 1 });
      }
    }
    return Array.from(regions.entries()).map(([region, { x, y, count }]) => ({
      region,
      x: scaleCoord(x / count),
      y: scaleCoord(y / count) - 20,
    }));
  }, [mapProgress]);

  const pinchGesture = Gesture.Pinch()
    .onStart(() => {
      savedScale.current = scale.value;
    })
    .onUpdate((e) => {
      scale.value = Math.max(MIN_SCALE, Math.min(MAX_SCALE, savedScale.current * e.scale));
    });

  const panGesture = Gesture.Pan()
    .onStart(() => {
      savedTranslateX.current = translateX.value;
      savedTranslateY.current = translateY.value;
    })
    .onUpdate((e) => {
      translateX.value = savedTranslateX.current + e.translationX;
      translateY.value = savedTranslateY.current + e.translationY;
    });

  const doubleTapGesture = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd(() => {
      // Re-center on current location
      if (currentLocationId) {
        const layout = MAP_LAYOUT_BY_ID.get(currentLocationId);
        if (layout) {
          const cx = scaleCoord(layout.x);
          const cy = scaleCoord(layout.y);
          translateX.value = withTiming(CONTAINER_SIZE / 2 - cx, { duration: 300 });
          translateY.value = withTiming(CONTAINER_SIZE / 2 - cy, { duration: 300 });
          scale.value = withTiming(1.5, { duration: 300 });
        }
      }
    });

  const composedGesture = Gesture.Simultaneous(panGesture, pinchGesture, doubleTapGesture);

  const animatedContainerStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
    ],
  }));

  if (mapProgress.length === 0) {
    return (
      <View style={styles.empty}>
        <ThemedText style={styles.emptyText}>No map data yet</ThemedText>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <GestureDetector gesture={composedGesture}>
        <Animated.View style={[styles.mapCanvas, animatedContainerStyle]}>
          {/* Connection lines */}
          {connections.map(({ from, to }) => {
            const fromLayout = MAP_LAYOUT_BY_ID.get(from);
            const toLayout = MAP_LAYOUT_BY_ID.get(to);
            if (!fromLayout || !toLayout) return null;
            const bothVisited = visitedSet.has(from) && visitedSet.has(to);
            return (
              <ConnectionLine
                key={`${from}-${to}`}
                x1={scaleCoord(fromLayout.x)}
                y1={scaleCoord(fromLayout.y)}
                x2={scaleCoord(toLayout.x)}
                y2={scaleCoord(toLayout.y)}
                color={bothVisited ? BrandColors.charcoal : BrandColors.slate}
              />
            );
          })}

          {/* Region labels */}
          {regionLabels.map(({ region, x, y }) => (
            <ThemedText key={region} style={[styles.regionLabel, { left: x - 30, top: y }]}>
              {region}
            </ThemedText>
          ))}

          {/* Nodes */}
          {mapProgress.map((node) => {
            const layout = MAP_LAYOUT_BY_ID.get(node.locationId);
            if (!layout) return null;
            const x = scaleCoord(layout.x);
            const y = scaleCoord(layout.y);
            const isCurrent = node.locationId === currentLocationId;

            if (isCurrent) {
              return (
                <View key={node.locationId}>
                  <PulsingNode x={x} y={y} />
                  <ThemedText style={[styles.nodeLabel, { left: x - 30, top: y + 14 }]}>
                    {layout.label}
                  </ThemedText>
                </View>
              );
            }

            if (node.visited) {
              return (
                <View key={node.locationId}>
                  <View
                    style={[styles.nodeBase, styles.visitedNode, { left: x - 10, top: y - 10 }]}
                  />
                  <ThemedText style={[styles.nodeLabel, { left: x - 30, top: y + 12 }]}>
                    {layout.label}
                  </ThemedText>
                </View>
              );
            }

            // Unvisited but connected
            return (
              <View key={node.locationId}>
                <View
                  style={[styles.nodeBase, styles.unvisitedNode, { left: x - 8, top: y - 8 }]}
                />
              </View>
            );
          })}

          {/* Quest objective diamond marker */}
          {questDiamondCoords && <QuestDiamond x={questDiamondCoords.x} y={questDiamondCoords.y} />}
        </Animated.View>
      </GestureDetector>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    overflow: "hidden",
    backgroundColor: BrandColors.void,
  },
  mapCanvas: {
    width: CONTAINER_SIZE,
    height: CONTAINER_SIZE,
    position: "relative",
    alignSelf: "center",
    marginTop: Spacing.three,
  },
  empty: { flex: 1, justifyContent: "center", alignItems: "center" },
  emptyText: { color: BrandColors.ash, fontFamily: FontFamilies.system, fontSize: 12 },
  connectionLine: {
    position: "absolute",
    height: 1,
    transformOrigin: "left center",
  },
  nodeBase: {
    position: "absolute",
    borderRadius: 999,
  },
  currentNode: {
    width: 24,
    height: 24,
    backgroundColor: BrandColors.hollow,
  },
  visitedNode: {
    width: 20,
    height: 20,
    backgroundColor: BrandColors.charcoal,
    borderWidth: 1,
    borderColor: BrandColors.bone,
  },
  unvisitedNode: {
    width: 16,
    height: 16,
    borderWidth: 1,
    borderColor: BrandColors.slate,
    borderStyle: "dashed",
  },
  nodeLabel: {
    position: "absolute",
    width: 60,
    textAlign: "center",
    fontFamily: FontFamilies.systemLight,
    fontSize: 7,
    color: BrandColors.bone,
  },
  regionLabel: {
    position: "absolute",
    fontFamily: FontFamilies.display,
    fontSize: 14,
    color: `${BrandColors.ash}80`, // 50% opacity
  },
  questDiamond: {
    position: "absolute",
    width: 10,
    height: 10,
    backgroundColor: BrandColors.hollow,
  },
});
