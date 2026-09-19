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

module.exports = config;
