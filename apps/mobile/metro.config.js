// Learn more https://docs.expo.io/guides/customizing-metro
const path = require('path');
const { getDefaultConfig } = require('expo/metro-config');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);

// Override Expo's auto-discovered watchFolders to drop apps/server (mobile
// never imports from it; only packages/shared and packages/design-tokens).
// Keep root node_modules in watchFolders because Metro queries watchman to
// enumerate the haste/module map; removing it breaks resolution despite
// Node-style resolution walking parents. NOTE: this list is explicit, not
// auto-discovered — a new workspace (e.g. apps/audio) that mobile starts
// importing from must be added here.
const repoRoot = path.resolve(__dirname, '../..');
config.watchFolders = [
  __dirname,
  path.join(repoRoot, 'packages/shared'),
  path.join(repoRoot, 'packages/design-tokens'),
  path.join(repoRoot, 'node_modules'),
];

// Exclude .expo/ from file watching — devices.json is rewritten every ~2s
// by Expo dev tools, causing Metro to trigger continuous reloads.
config.resolver.blockList = [
  ...(Array.isArray(config.resolver.blockList)
    ? config.resolver.blockList
    : config.resolver.blockList
      ? [config.resolver.blockList]
      : []),
  /\/\.expo\//,
];

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
