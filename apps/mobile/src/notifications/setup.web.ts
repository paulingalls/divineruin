export function registerForPushNotifications(): Promise<string | null> {
  return Promise.resolve(null);
}

export function storePushToken(_token: string): Promise<void> {
  return Promise.resolve();
}
