import { useEffect } from "react";
import { StyleSheet } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { ThemedView } from "@/components/themed-view";
import { authStore } from "@/stores/auth-store";
import { pendingInviteStore } from "@/stores/pending-invite-store";
import { BrandColors, Spacing } from "@/constants/theme";

// Deep-link target for divineruin://join?code=<code> (see utils/invite-link.ts
// buildInviteUrl). expo-router maps the URL here by file convention and hands us
// `code` via useLocalSearchParams. Registered in BOTH auth stacks (_layout.tsx)
// so a cold-start (unauthenticated) invite resolves here too.
export default function JoinScreen() {
  const router = useRouter();
  const { code } = useLocalSearchParams<{ code?: string }>();
  const phase = useStore(authStore, (s) => s.phase);

  useEffect(() => {
    if (phase === "loading") return; // wait for stored-token load to resolve
    if (!code) {
      router.replace("/"); // malformed link — nothing to join
      return;
    }
    if (phase === "authenticated") {
      router.replace({ pathname: "/session", params: { code } });
    } else {
      // Cold start: stash the code through sign-in; index.tsx redeems it post-auth.
      pendingInviteStore.getState().setPendingCode(code);
      router.replace("/auth");
    }
  }, [phase, code, router]);

  return (
    <ThemedView style={styles.container}>
      <ThemedText style={styles.text}>Joining…</ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: Spacing.four,
  },
  text: {
    color: BrandColors.bone,
  },
});
