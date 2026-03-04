import { NativeTabs } from "expo-router/unstable-native-tabs";
import React from "react";

import { BrandColors } from "@/constants/theme";

export default function TabLayout() {
  return (
    <NativeTabs
      backgroundColor={BrandColors.void}
      indicatorColor={BrandColors.ink}
      labelStyle={{ selected: { color: BrandColors.parchment } }}
    >
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Label>Home</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon
          src={require("@/assets/images/tabIcons/home.png")}
          renderingMode="template"
        />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
