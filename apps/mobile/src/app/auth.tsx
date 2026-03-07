import { useState } from "react";
import {
  Pressable,
  StyleSheet,
  TextInput,
  View,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ThemedText } from "@/components/themed-text";
import { ThemedView } from "@/components/themed-view";
import { TitleBar } from "@/components/title-bar";
import { authStore } from "@/stores/auth-store";
import { API_BASE } from "@/utils/api";
import { BrandColors, FontFamilies, Spacing, Radius, MaxContentWidth } from "@/constants/theme";

type Phase = "email" | "code";

const CLIENT_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL_LENGTH = 254;

export default function AuthScreen() {
  const [phase, setPhase] = useState<Phase>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSendCode = async () => {
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) return;

    if (trimmed.length > MAX_EMAIL_LENGTH || !CLIENT_EMAIL_RE.test(trimmed)) {
      setError("Please enter a valid email address");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/request-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { error?: string };
        throw new Error(body.error ?? "Failed to send code");
      }
      authStore.getState().setEmail(trimmed);
      setPhase("code");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyCode = async () => {
    const trimmed = code.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/verify-code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase(), code: trimmed }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { error?: string };
        throw new Error(body.error ?? "Invalid code");
      }
      const data = (await res.json()) as {
        token: string;
        account_id: string;
        player_id: string;
      };
      await authStore.getState().setAuthenticated(data.token, data.account_id, data.player_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  };

  const handleBackToEmail = () => {
    setPhase("email");
    setCode("");
    setError(null);
  };

  return (
    <ThemedView style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView
          style={styles.content}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          <TitleBar />
          <View style={styles.titleSpacer} />

          <View style={styles.form}>
            {phase === "email" ? (
              <>
                <ThemedText style={styles.label}>ENTER YOUR EMAIL</ThemedText>
                <TextInput
                  style={styles.input}
                  value={email}
                  onChangeText={setEmail}
                  placeholder="adventurer@example.com"
                  placeholderTextColor={BrandColors.slate}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                  autoComplete="email"
                  editable={!loading}
                />
                <Pressable
                  style={[styles.button, loading && styles.buttonDisabled]}
                  onPress={() => void handleSendCode()}
                  disabled={loading}
                >
                  {loading ? (
                    <ActivityIndicator color={BrandColors.void} />
                  ) : (
                    <ThemedText style={styles.buttonText}>SEND CODE</ThemedText>
                  )}
                </Pressable>
              </>
            ) : (
              <>
                <ThemedText style={styles.label}>ENTER VERIFICATION CODE</ThemedText>
                <ThemedText style={styles.sublabel}>
                  Sent to {email.trim().toLowerCase()}
                </ThemedText>
                <TextInput
                  style={styles.input}
                  value={code}
                  onChangeText={setCode}
                  placeholder="000000"
                  placeholderTextColor={BrandColors.slate}
                  keyboardType="number-pad"
                  maxLength={6}
                  autoComplete="one-time-code"
                  editable={!loading}
                />
                <Pressable
                  style={[styles.button, loading && styles.buttonDisabled]}
                  onPress={() => void handleVerifyCode()}
                  disabled={loading}
                >
                  {loading ? (
                    <ActivityIndicator color={BrandColors.void} />
                  ) : (
                    <ThemedText style={styles.buttonText}>VERIFY</ThemedText>
                  )}
                </Pressable>
                <Pressable onPress={handleBackToEmail} style={styles.linkButton}>
                  <ThemedText style={styles.linkText}>Use different email</ThemedText>
                </Pressable>
              </>
            )}

            {error && <ThemedText style={styles.errorText}>{error}</ThemedText>}
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    flexDirection: "row",
    justifyContent: "center",
  },
  safeArea: {
    flex: 1,
    maxWidth: MaxContentWidth,
  },
  content: {
    flex: 1,
    paddingHorizontal: Spacing.four,
    justifyContent: "center",
    gap: Spacing.three,
  },
  titleSpacer: {
    height: Spacing.five,
  },
  form: {
    gap: Spacing.three,
  },
  label: {
    fontFamily: FontFamilies.system,
    fontSize: 13,
    color: BrandColors.ash,
    letterSpacing: 1,
  },
  sublabel: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 13,
    color: BrandColors.slate,
    marginTop: -Spacing.two,
  },
  input: {
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.three,
    color: BrandColors.parchment,
    fontFamily: FontFamilies.system,
    fontSize: 16,
  },
  button: {
    backgroundColor: BrandColors.hollowMuted,
    paddingVertical: Spacing.three,
    borderRadius: Radius.md,
    alignItems: "center",
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    fontFamily: FontFamilies.system,
    fontSize: 14,
    color: BrandColors.void,
    letterSpacing: 2,
  },
  linkButton: {
    alignItems: "center",
    paddingVertical: Spacing.two,
  },
  linkText: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 13,
    color: BrandColors.hollowMuted,
  },
  errorText: {
    fontFamily: FontFamilies.system,
    fontSize: 13,
    color: BrandColors.ember,
    textAlign: "center",
  },
});
