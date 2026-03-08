// Learn more https://docs.expo.io/guides/customizing-metro
const { getDefaultConfig } = require('expo/metro-config');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);

// Fix: @livekit/react-native-webrtc imports "event-target-shim/index" but
// event-target-shim@6.0.2's "exports" field only declares "." (not "./index").
// Metro's package-exports resolver warns and falls back to file-based resolution.
// Rewrite the import to "event-target-shim" (the "." export) to eliminate the warning.
const originalResolveRequest = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName === 'event-target-shim/index') {
    return context.resolveRequest(context, 'event-target-shim', platform);
  }
  if (originalResolveRequest) {
    return originalResolveRequest(context, moduleName, platform);
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;
