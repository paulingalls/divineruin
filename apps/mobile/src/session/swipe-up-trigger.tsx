import { useMemo } from "react";
import { StyleSheet, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { panelStore } from "@/stores/panel-store";

const SWIPE_UP_THRESHOLD = -50;

export function SwipeUpTrigger() {
  const swipeGesture = useMemo(
    () =>
      Gesture.Pan()
        .runOnJS(true)
        .onEnd((event) => {
          if (event.translationY < SWIPE_UP_THRESHOLD) {
            panelStore.getState().openPanel();
          }
        }),
    [],
  );

  return (
    <GestureDetector gesture={swipeGesture}>
      <View testID="session-hud-swipe-zone" style={styles.zone} />
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  zone: { height: 24, width: "100%" },
});
