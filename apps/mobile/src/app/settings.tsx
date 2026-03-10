import { useCallback, useState } from "react";
import { ActivityIndicator, Platform, Pressable, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Slider from "@react-native-community/slider";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { useVolume } from "@/hooks/use-volume";
import type { Bus } from "@/audio/volume";
import { getEffectiveVolume } from "@/audio/volume";
import { playSfx } from "@/audio/sfx-player";
import { createAudioPlayer, type AudioPlayer } from "expo-audio";
import { lookupSoundscape } from "@/audio/soundscape-registry";
import { authStore } from "@/stores/auth-store";
import { characterStore } from "@/stores/character-store";
import { API_BASE, authHeaders } from "@/utils/api";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";

let previewPlayer: AudioPlayer | null = null;
let previewTimer: ReturnType<typeof setTimeout> | null = null;

function previewBus(bus: Bus): void {
  if (previewPlayer) {
    previewPlayer.remove();
    previewPlayer = null;
  }
  if (previewTimer) {
    clearTimeout(previewTimer);
    previewTimer = null;
  }

  if (bus === "ambience") {
    const entry = lookupSoundscape("tavern_busy");
    if (!entry) return;
    previewPlayer = createAudioPlayer(entry.asset);
    previewPlayer.volume = getEffectiveVolume("ambience");
    previewPlayer.play();
    previewTimer = setTimeout(() => {
      previewPlayer?.remove();
      previewPlayer = null;
      previewTimer = null;
    }, 1000);
  } else if (bus === "effects") {
    playSfx("sword_clash");
  } else if (bus === "ui") {
    playSfx("notification");
  }
}

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
      <Pressable onPress={disabled ? undefined : () => previewBus(bus)}>
        <ThemedText style={[styles.sliderLabel, disabled && styles.disabledText]}>
          {label}
        </ThemedText>
      </Pressable>
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
  const character = useStore(characterStore, (s) => s.character);
  const [regenerating, setRegenerating] = useState(false);

  const handleSignOut = () => {
    void authStore.getState().logout();
    if (Platform.OS === "web") {
      router.replace("/");
    } else {
      router.dismiss();
    }
  };

  const handleRegenerate = useCallback(async () => {
    if (!character || regenerating) return;
    setRegenerating(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/character/${character.playerId}/regenerate-portrait`,
        { method: "POST", headers: authHeaders() },
      );
      if (res.ok) {
        const data = (await res.json()) as { portrait_url: string };
        if (data.portrait_url) {
          characterStore.getState().updatePortraitUrl(data.portrait_url);
        }
      }
    } catch {
      // Silently fail — portrait stays as-is
    } finally {
      setRegenerating(false);
    }
  }, [character, regenerating]);

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
          <VolumeSlider label="MUSIC" bus="music" />
          <VolumeSlider label="AMBIENCE" bus="ambience" />
          <VolumeSlider label="EFFECTS" bus="effects" />
          <VolumeSlider label="UI" bus="ui" />
        </View>

        {character && (
          <View style={[styles.section, { marginTop: Spacing.five }]}>
            <ThemedText style={styles.sectionTitle}>CHARACTER</ThemedText>
            <View style={styles.portraitRow}>
              <CachedImage
                uri={character.portraitUrl}
                style={styles.portraitImage}
                borderRadius={28}
              />
              <Pressable
                onPress={() => void handleRegenerate()}
                disabled={regenerating}
                style={styles.regenButton}
              >
                {regenerating ? (
                  <ActivityIndicator size="small" color={BrandColors.hollow} />
                ) : (
                  <ThemedText style={styles.regenText}>REGENERATE PORTRAIT</ThemedText>
                )}
              </Pressable>
            </View>
          </View>
        )}

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
  portraitRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.three,
  },
  portraitImage: {
    width: 56,
    height: 56,
  },
  regenButton: {
    paddingVertical: Spacing.two,
    paddingHorizontal: Spacing.three,
  },
  regenText: {
    fontFamily: FontFamilies.system,
    fontSize: 12,
    color: BrandColors.hollow,
    letterSpacing: 1,
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
