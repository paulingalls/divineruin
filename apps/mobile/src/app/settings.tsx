import { Pressable, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Slider from "@react-native-community/slider";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { useVolume } from "@/hooks/use-volume";
import type { Bus } from "@/audio/volume";
import { authStore } from "@/stores/auth-store";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";

interface SliderRowProps {
  label: string;
  bus: Bus;
  disabled?: boolean;
}

function VolumeSlider({ label, bus, disabled }: SliderRowProps) {
  const [value, setValue] = useVolume(bus);
  const pct = Math.round(value * 100);

  return (
    <View style={styles.sliderRow}>
      <ThemedText style={[styles.sliderLabel, disabled && styles.disabledText]}>{label}</ThemedText>
      <Slider
        style={styles.slider}
        minimumValue={0}
        maximumValue={1}
        value={value}
        onValueChange={disabled ? undefined : setValue}
        minimumTrackTintColor={disabled ? BrandColors.slate : BrandColors.hollow}
        maximumTrackTintColor={BrandColors.charcoal}
        thumbTintColor={disabled ? BrandColors.slate : BrandColors.hollow}
        disabled={disabled}
      />
      <ThemedText style={[styles.sliderValue, disabled && styles.disabledText]}>
        {disabled ? "Soon" : `${pct}%`}
      </ThemedText>
    </View>
  );
}

export default function SettingsScreen() {
  const router = useRouter();
  const email = useStore(authStore, (s) => s.email);

  const handleSignOut = () => {
    void authStore.getState().logout();
    router.dismiss();
  };

  return (
    <View style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.header}>
          <ThemedText style={styles.title}>SETTINGS</ThemedText>
          <Pressable onPress={() => router.back()} style={styles.closeButton}>
            <ThemedText style={styles.closeText}>{"\u2715"}</ThemedText>
          </Pressable>
        </View>

        <View style={styles.section}>
          <ThemedText style={styles.sectionTitle}>AUDIO</ThemedText>

          <VolumeSlider label="VOICE" bus="voice" />
          <VolumeSlider label="MUSIC" bus="music" disabled />
          <VolumeSlider label="AMBIENCE" bus="ambience" />
          <VolumeSlider label="EFFECTS" bus="effects" />
          <VolumeSlider label="UI" bus="ui" />
        </View>

        <View style={[styles.section, { marginTop: Spacing.five }]}>
          <ThemedText style={styles.sectionTitle}>ACCOUNT</ThemedText>
          {email && <ThemedText style={styles.emailText}>{email}</ThemedText>}
          <Pressable onPress={handleSignOut} style={styles.signOutButton}>
            <ThemedText style={styles.signOutText}>SIGN OUT</ThemedText>
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: BrandColors.void,
  },
  safeArea: {
    flex: 1,
    padding: Spacing.four,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: Spacing.five,
  },
  title: {
    fontFamily: FontFamilies.system,
    fontSize: 18,
    color: BrandColors.parchment,
    textTransform: "uppercase",
    letterSpacing: 2,
  },
  closeButton: {
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
  },
  closeText: {
    fontSize: 18,
    color: BrandColors.ash,
  },
  section: {
    gap: Spacing.three,
  },
  sectionTitle: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 13,
    color: BrandColors.ash,
    textTransform: "uppercase",
    letterSpacing: 1,
    marginBottom: Spacing.one,
  },
  sliderRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
  },
  sliderLabel: {
    width: 80,
    fontFamily: FontFamilies.system,
    fontSize: 14,
    color: BrandColors.bone,
    textTransform: "uppercase",
  },
  slider: {
    flex: 1,
    height: 40,
  },
  sliderValue: {
    width: 48,
    fontFamily: FontFamilies.systemLight,
    fontSize: 13,
    color: BrandColors.ash,
    textAlign: "right",
  },
  disabledText: {
    color: BrandColors.slate,
  },
  emailText: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 14,
    color: BrandColors.bone,
  },
  signOutButton: {
    paddingVertical: Spacing.two,
  },
  signOutText: {
    fontFamily: FontFamilies.system,
    fontSize: 14,
    color: BrandColors.ember,
    letterSpacing: 1,
  },
});
