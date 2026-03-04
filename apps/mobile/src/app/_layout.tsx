import { ThemeProvider, type Theme } from "@react-navigation/native";
import { registerGlobals } from "@livekit/react-native";
import { useFonts } from "expo-font";
import * as SplashScreen from "expo-splash-screen";
import { Stack } from "expo-router";
import React, { useEffect } from "react";

import { AnimatedSplashOverlay } from "@/components/animated-icon";
import { BrandColors } from "@/constants/theme";

import {
  CormorantGaramond_300Light,
  CormorantGaramond_400Regular,
  CormorantGaramond_600SemiBold,
  CormorantGaramond_300Light_Italic,
  CormorantGaramond_400Regular_Italic,
} from "@expo-google-fonts/cormorant-garamond";

import {
  CrimsonPro_300Light,
  CrimsonPro_400Regular,
  CrimsonPro_600SemiBold,
  CrimsonPro_300Light_Italic,
  CrimsonPro_400Regular_Italic,
} from "@expo-google-fonts/crimson-pro";

import { IBMPlexMono_300Light, IBMPlexMono_400Regular } from "@expo-google-fonts/ibm-plex-mono";

registerGlobals();
SplashScreen.preventAutoHideAsync();

const DivineRuinTheme: Theme = {
  dark: true,
  colors: {
    primary: BrandColors.hollow,
    background: BrandColors.void,
    card: BrandColors.ink,
    text: BrandColors.bone,
    border: BrandColors.charcoal,
    notification: BrandColors.hollow,
  },
  fonts: {
    regular: { fontFamily: "CrimsonPro_400Regular", fontWeight: "400" },
    medium: { fontFamily: "CrimsonPro_400Regular", fontWeight: "400" },
    bold: { fontFamily: "CrimsonPro_600SemiBold", fontWeight: "600" },
    heavy: { fontFamily: "CormorantGaramond_600SemiBold", fontWeight: "600" },
  },
};

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    CormorantGaramond_300Light,
    CormorantGaramond_400Regular,
    CormorantGaramond_600SemiBold,
    CormorantGaramond_300Light_Italic,
    CormorantGaramond_400Regular_Italic,
    CrimsonPro_300Light,
    CrimsonPro_400Regular,
    CrimsonPro_600SemiBold,
    CrimsonPro_300Light_Italic,
    CrimsonPro_400Regular_Italic,
    IBMPlexMono_300Light,
    IBMPlexMono_400Regular,
  });

  useEffect(() => {
    if (fontsLoaded || fontError) {
      SplashScreen.hideAsync();
    }
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) {
    return null;
  }

  return (
    <ThemeProvider value={DivineRuinTheme}>
      <AnimatedSplashOverlay />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="session" />
      </Stack>
    </ThemeProvider>
  );
}
