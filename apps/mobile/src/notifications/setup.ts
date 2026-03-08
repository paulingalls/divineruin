import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import Constants from "expo-constants";
import { API_BASE, authHeaders } from "@/utils/api";

Notifications.setNotificationHandler({
  handleNotification: () =>
    Promise.resolve({
      shouldShowAlert: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
});

export async function registerForPushNotifications(): Promise<string | null> {
  if (!Device.isDevice) {
    console.log("[notifications] Push notifications require a physical device");
    return null;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (String(existingStatus) !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (String(finalStatus) !== "granted") {
    console.log("[notifications] Permission not granted");
    return null;
  }

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "Default",
      importance: Notifications.AndroidImportance.DEFAULT,
    });
  }

  const extra = Constants.expoConfig?.extra as Record<string, Record<string, string>> | undefined;
  const projectId = extra?.eas.projectId;
  if (!projectId) {
    console.warn(
      "[notifications] No EAS projectId found — run 'eas init' to configure push notifications",
    );
    return null;
  }

  const tokenData = await Notifications.getExpoPushTokenAsync({ projectId });
  return tokenData.data;
}

export async function storePushToken(token: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/push-token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify({
        token,
        platform: Platform.OS,
      }),
    });
  } catch {
    console.warn("[notifications] Failed to store push token");
  }
}
