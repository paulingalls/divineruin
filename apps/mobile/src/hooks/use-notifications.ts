import { useEffect, useRef } from "react";
import { useRouter } from "expo-router";
import { useStore } from "zustand";
import { addNotificationResponseReceivedListener } from "expo-notifications";
import { registerForPushNotifications, storePushToken } from "@/notifications/setup";
import { authStore } from "@/stores/auth-store";

export function useNotifications() {
  const router = useRouter();
  const authPhase = useStore(authStore, (s) => s.phase);
  const removeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (authPhase !== "authenticated") return;

    // Register and store token only when authenticated
    void (async () => {
      const token = await registerForPushNotifications();
      if (token) {
        await storePushToken(token);
      }
    })();

    // Handle notification tap — navigate to home screen
    const subscription = addNotificationResponseReceivedListener((_response) => {
      router.replace("/");
    });
    removeRef.current = () => subscription.remove();

    return () => {
      removeRef.current?.();
      removeRef.current = null;
    };
  }, [router, authPhase]);
}
