import { useState } from "react";
import {
  Pressable,
  StyleSheet,
  TextInput,
  View,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  useWindowDimensions,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";

import { ThemedText } from "@/components/themed-text";
import { ThemedView } from "@/components/themed-view";
import { TitleBar } from "@/components/title-bar";
import { authStore } from "@/stores/auth-store";
import { API_BASE } from "@/utils/api";
import { BrandColors, FontStyles, Spacing, Radius, MaxContentWidth } from "@/constants/theme";

type Phase = "email" | "code";

const CLIENT_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL_LENGTH = 254;

export default function AuthScreen() {
  const [phase, setPhase] = useState<Phase>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { width, height } = useWindowDimensions();

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
    <ThemedView style={styles.root}>
      <LinearGradient
        colors={[BrandColors.charcoal, BrandColors.void]}
        style={{ position: "absolute", top: 0, left: 0, width, height }}
      />
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView
          style={styles.content}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          <View style={styles.topSpacer} />
          <TitleBar />
          <ThemedText style={styles.tagline}>Listen to the dark</ThemedText>
          <View style={styles.titleSpacer} />

          <View style={styles.form}>
            {phase === "email" ? (
              <>
                <ThemedText style={styles.label}>Enter your email</ThemedText>
                <TextInput
                  style={styles.input}
                  value={email}
                  onChangeText={setEmail}
                  placeholder="adventurer@example.com"
                  placeholderTextColor={BrandColors.ash}
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
                <ThemedText style={styles.label}>Enter verification code</ThemedText>
                <ThemedText style={styles.sublabel}>
                  Sent to {email.trim().toLowerCase()}
                </ThemedText>
                <TextInput
                  style={styles.input}
                  value={code}
                  onChangeText={setCode}
                  placeholder="000000"
                  placeholderTextColor={BrandColors.ash}
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
          <View style={styles.bottomSpacer} />
        </KeyboardAvoidingView>
      </SafeAreaView>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
    alignSelf: "center",
    width: "100%",
    maxWidth: MaxContentWidth,
  },
  content: {
    flex: 1,
    paddingHorizontal: Spacing.four,
  },
  topSpacer: {
    flex: 1,
  },
  tagline: {
    ...FontStyles.displayItalic,
    fontSize: 21,
    color: BrandColors.ash,
    textAlign: "center",
    marginTop: Spacing.two,
  },
  titleSpacer: {
    flex: 2,
  },
  bottomSpacer: {
    flex: 3,
  },
  form: {
    gap: Spacing.three,
  },
  label: {
    ...FontStyles.displayItalic,
    fontSize: 27,
    color: BrandColors.bone,
  },
  sublabel: {
    ...FontStyles.systemLight,
    fontSize: 13,
    color: BrandColors.slate,
    marginTop: -Spacing.two,
  },
  input: {
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderColor: BrandColors.hollowFaint,
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.three,
    color: BrandColors.parchment,
    ...FontStyles.system,
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
    ...FontStyles.system,
    fontSize: 16,
    color: BrandColors.void,
    letterSpacing: 2,
  },
  linkButton: {
    alignItems: "center",
    paddingVertical: Spacing.two,
  },
  linkText: {
    ...FontStyles.systemLight,
    fontSize: 13,
    color: BrandColors.hollowMuted,
  },
  errorText: {
    ...FontStyles.system,
    fontSize: 13,
    color: BrandColors.ember,
    textAlign: "center",
  },
});
