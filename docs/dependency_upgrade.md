# Dependency upgrade

Registry snapshot: 2026-09-19  
Toolchain: CPython 3.14.7; uv 0.10.6; Bun 1.4.2
Execution evidence: historical record accepted at 795cec97832a7fe2d7567b36d0343e476e236b76 on 2026-09-19T14:14:59Z.

## Python environments

### apps/agent

| Group | Dependency | Requested | Resolved / installed | Latest stable | Holdback |
|---|---|---|---|---|---|
| runtime | livekit-agents | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | livekit-plugins-anthropic | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | livekit-plugins-deepgram | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | livekit-plugins-inworld | `~=1.8.2` | 1.8.2 / 1.8.2 | 1.8.2 | — |
| runtime | asyncpg | `>=0.31.0` | 0.31.0 / 0.31.0 | 0.31.0 | — |
| runtime | redis | `>=8.1.0` | 8.1.0 / 8.1.0 | 8.1.0 | — |
| runtime | anthropic | `>=0.125.0,<1` | 0.125.0 / 0.125.0 | 1.7.0 | livekit-plugins-anthropic==1.8.2 requires anthropic<1,>=0.41: Anthropic 1.7.0 is outside the plugin's published constraint; the project mirrors the same <1 cap. |
| runtime | httpx | `>=0.28.1` | 0.28.1 / 0.28.1 | 0.28.1 | — |
| dev | docker | `>=7.2.0` | 7.2.0 / 7.2.0 | 7.2.0 | — |
| dev | pillow | `>=12.3.0` | 12.3.0 / 12.3.0 | 12.3.0 | — |
| dev | pyright | `>=1.1.414` | 1.1.414 / 1.1.414 | 1.1.414 | — |
| dev | pytest | `>=9.1.1` | 9.1.1 / 9.1.1 | 9.1.1 | — |
| dev | pytest-asyncio | `>=1.4.0` | 1.4.0 / 1.4.0 | 1.4.0 | — |
| dev | pytest-bdd | `>=8.1.0` | 8.1.0 / 8.1.0 | 8.1.0 | — |
| dev | pytest-cov | `>=7.1.0` | 7.1.0 / 7.1.0 | 7.1.0 | — |
| dev | pytest-xdist | `>=3.8.0` | 3.8.0 / 3.8.0 | 3.8.0 | — |
| dev | ruff | `>=0.16.8` | 0.16.8 / 0.16.8 | 0.16.8 | — |
| dev | testcontainers | `>=4.15.0` | 4.15.0 / 4.15.0 | 4.15.0 | — |

### scripts

| Group | Dependency | Requested | Resolved / installed | Latest stable | Holdback |
|---|---|---|---|---|---|
| runtime | asyncpg | `>=0.31.0` | 0.31.0 / 0.31.0 | 0.31.0 | — |

## Bun workspace

Release age policy: 604800 seconds.

| Project | Group | Dependency | Requested | Locked / installed | Candidate | Registry latest | Decision |
|---|---|---|---|---|---|---|---|
| . | devDependencies | @eslint/js | `^10.0.1` | 10.0.1 / 10.0.1 | 10.0.1 | 10.0.1 | Current |
| . | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| . | devDependencies | eslint | `^10.10.0` | 10.10.0 / 10.10.0 | 10.10.0 | 10.11.0 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| . | devDependencies | eslint-config-prettier | `^10.1.8` | 10.1.8 / 10.1.8 | 10.1.8 | 10.1.8 | Current |
| . | devDependencies | eslint-plugin-react-hooks | `^7.1.1` | 7.1.1 / 7.1.1 | 7.1.1 | 7.1.1 | Current |
| . | devDependencies | eslint-plugin-react-refresh | `^0.5.6` | 0.5.6 / 0.5.6 | 0.5.6 | 0.5.7 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| . | devDependencies | prettier | `^3.9.6` | 3.9.6 / 3.9.6 | 3.9.6 | 3.9.8 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| . | devDependencies | typescript-eslint | `^8.70.0` | 8.70.0 / 8.70.0 | 8.70.0 | 8.70.0 | Current |
| . | devDependencies | typescript | `6.0.3` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |
| . | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |
| apps/mobile | dependencies | @config-plugins/react-native-webrtc | `15.0.2` | 15.0.2 / 15.0.2 | 15.0.2 | 15.0.2 | Current |
| apps/mobile | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | workspace:packages/design-tokens | workspace:packages/design-tokens | Current |
| apps/mobile | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | workspace:packages/shared | workspace:packages/shared | Current |
| apps/mobile | dependencies | @expo-google-fonts/cormorant-garamond | `^0.4.1` | 0.4.1 / 0.4.1 | 0.4.1 | 0.4.1 | Current |
| apps/mobile | dependencies | @expo-google-fonts/crimson-pro | `^0.4.2` | 0.4.2 / 0.4.2 | 0.4.2 | 0.4.2 | Current |
| apps/mobile | dependencies | @expo-google-fonts/ibm-plex-mono | `^0.4.1` | 0.4.1 / 0.4.1 | 0.4.1 | 0.4.1 | Current |
| apps/mobile | dependencies | @expo/vector-icons | `^15.0.2` | 15.1.1 / 15.1.1 | 15.1.1 | 15.1.1 | Current |
| apps/mobile | dependencies | @livekit/components-core | `^0.12.15` | 0.12.15 / 0.12.15 | 0.12.15 | 0.12.15 | Current |
| apps/mobile | dependencies | @livekit/components-react | `^2.9.24` | 2.9.24 / 2.9.24 | 2.9.24 | 2.9.24 | Current |
| apps/mobile | dependencies | @livekit/react-native | `2.12.0` | 2.12.0 / 2.12.0 | 2.12.0 | 3.0.0 | Held by @livekit/react-native-expo-plugin@1.0.2: The Expo plugin declares @livekit/react-native ^2.1.0; 2.12.0 is the newest compatible release and requires WebRTC ^144.1.2. |
| apps/mobile | dependencies | @livekit/react-native-expo-plugin | `^1.0.2` | 1.0.2 / 1.0.2 | 1.0.2 | 1.0.2 | Current |
| apps/mobile | dependencies | @livekit/react-native-webrtc | `144.1.2` | 144.1.2 / 144.1.2 | 144.1.2 | 144.2.0 | Held by @livekit/react-native@2.12.0: LiveKit React Native 2.12.0 declares WebRTC ^144.1.2; 144.1.2 retains the WebRTC-SDK framework required by that release. |
| apps/mobile | dependencies | @react-native-async-storage/async-storage | `2.2.0` | 2.2.0 / 2.2.0 | 2.2.0 | 3.1.1 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects @react-native-async-storage/async-storage 2.2.0. |
| apps/mobile | dependencies | @react-native-community/slider | `5.2.0` | 5.2.0 / 5.2.0 | 5.2.0 | 5.2.1 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects @react-native-community/slider 5.2.0. |
| apps/mobile | dependencies | expo | `57.0.24` | 57.0.24 / 57.0.24 | 57.0.24 | 57.0.24 | Current |
| apps/mobile | dependencies | expo-asset | `57.0.18` | 57.0.18 / 57.0.18 | 57.0.18 | 57.0.18 | Current |
| apps/mobile | dependencies | expo-audio | `57.0.5` | 57.0.5 / 57.0.5 | 57.0.5 | 57.0.5 | Current |
| apps/mobile | dependencies | expo-crypto | `57.0.3` | 57.0.3 / 57.0.3 | 57.0.3 | 57.0.3 | Current |
| apps/mobile | dependencies | expo-dev-client | `57.0.19` | 57.0.19 / 57.0.19 | 57.0.19 | 57.0.19 | Current |
| apps/mobile | dependencies | expo-device | `57.0.2` | 57.0.2 / 57.0.2 | 57.0.2 | 57.0.2 | Current |
| apps/mobile | dependencies | expo-disable-pods-indexing | `github:paulingalls/expo-disable-pods-indexing` | github:paulingalls/expo-disable-pods-indexing#fdd8959 / github:paulingalls/expo-disable-pods-indexing#fdd8959 | github:paulingalls/expo-disable-pods-indexing#fdd8959 | github:paulingalls/expo-disable-pods-indexing#fdd8959 | Current |
| apps/mobile | dependencies | expo-font | `57.0.4` | 57.0.4 / 57.0.4 | 57.0.4 | 57.0.4 | Current |
| apps/mobile | dependencies | expo-glass-effect | `57.0.3` | 57.0.3 / 57.0.3 | 57.0.3 | 57.0.3 | Current |
| apps/mobile | dependencies | expo-haptics | `57.0.3` | 57.0.3 / 57.0.3 | 57.0.3 | 57.0.3 | Current |
| apps/mobile | dependencies | expo-image | `57.0.5` | 57.0.5 / 57.0.5 | 57.0.5 | 57.0.5 | Current |
| apps/mobile | dependencies | expo-linear-gradient | `57.0.2` | 57.0.2 / 57.0.2 | 57.0.2 | 57.0.2 | Current |
| apps/mobile | dependencies | expo-linking | `57.0.10` | 57.0.10 / 57.0.10 | 57.0.10 | 57.0.10 | Current |
| apps/mobile | dependencies | expo-notifications | `57.0.20` | 57.0.20 / 57.0.20 | 57.0.20 | 57.0.20 | Current |
| apps/mobile | dependencies | expo-router | `57.0.22` | 57.0.22 / 57.0.22 | 57.0.22 | 57.0.22 | Current |
| apps/mobile | dependencies | expo-secure-store | `57.0.4` | 57.0.4 / 57.0.4 | 57.0.4 | 57.0.4 | Current |
| apps/mobile | dependencies | expo-splash-screen | `57.0.9` | 57.0.9 / 57.0.9 | 57.0.9 | 57.0.9 | Current |
| apps/mobile | dependencies | expo-status-bar | `57.0.1` | 57.0.1 / 57.0.1 | 57.0.1 | 57.0.1 | Current |
| apps/mobile | dependencies | expo-symbols | `57.0.3` | 57.0.3 / 57.0.3 | 57.0.3 | 57.0.3 | Current |
| apps/mobile | dependencies | expo-system-ui | `57.0.4` | 57.0.4 / 57.0.4 | 57.0.4 | 57.0.4 | Current |
| apps/mobile | dependencies | expo-web-browser | `57.0.3` | 57.0.3 / 57.0.3 | 57.0.3 | 57.0.3 | Current |
| apps/mobile | dependencies | livekit-client | `^2.19.0` | 2.22.3 / 2.22.3 | 2.22.3 | 2.22.3 | Current |
| apps/mobile | dependencies | react | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by react-native@0.86.3 and the shared web runtime: React 19.2.6 is the SDK 57-supported React 19.2 cohort and stays identical across mobile and web; typechecks, tests, exports, and the native build pass. |
| apps/mobile | dependencies | react-dom | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by react-native@0.86.3 and the shared web runtime: React 19.2.6 is the SDK 57-supported React 19.2 cohort and stays identical across mobile and web; typechecks, tests, exports, and the native build pass. |
| apps/mobile | dependencies | react-native | `0.86.3` | 0.86.3 / 0.86.3 | 0.86.3 | 0.87.1 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects react-native 0.86.3. |
| apps/mobile | dependencies | react-native-gesture-handler | `2.32.0` | 2.32.0 / 2.32.0 | 2.32.0 | 3.3.0 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects react-native-gesture-handler 2.32.0. |
| apps/mobile | dependencies | react-native-reanimated | `4.5.1` | 4.5.1 / 4.5.1 | 4.5.1 | 4.7.0 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects react-native-reanimated 4.5.1. |
| apps/mobile | dependencies | react-native-safe-area-context | `5.7.0` | 5.7.0 / 5.7.0 | 5.7.0 | 5.10.0 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects react-native-safe-area-context 5.7.0. |
| apps/mobile | dependencies | react-native-screens | `4.26.0` | 4.26.0 / 4.26.0 | 4.26.0 | 4.28.0 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects react-native-screens 4.26.0. |
| apps/mobile | dependencies | react-native-url-polyfill | `4.0.0` | 4.0.0 / 4.0.0 | 4.0.0 | 4.0.0 | Current |
| apps/mobile | dependencies | react-native-web | `~0.21.0` | 0.21.2 / 0.21.2 | 0.21.2 | 0.21.2 | Current |
| apps/mobile | dependencies | react-native-worklets | `0.10.1` | 0.10.1 / 0.10.1 | 0.10.1 | 0.12.2 | Held by expo@57.0.24: Expo SDK 57 bundledNativeModules.json selects react-native-worklets 0.10.1. |
| apps/mobile | dependencies | zustand | `^5.0.15` | 5.0.15 / 5.0.15 | 5.0.15 | 5.0.15 | Current |
| apps/mobile | devDependencies | @types/react | `~19.2.2` | 19.2.14 / 19.2.14 | 19.2.14 | 19.3.0 | Held by react@19.2.6 shared cohort: React type packages stay on the React 19.2 line shared by mobile and web. |
| apps/mobile | devDependencies | @types/react-dom | `~19.2.1` | 19.2.3 / 19.2.3 | 19.2.3 | 19.3.0 | Held by react@19.2.6 shared cohort: React type packages stay on the React 19.2 line shared by mobile and web. |
| apps/mobile | devDependencies | expo-mcp | `~0.2.1` | 0.2.4 / 0.2.4 | 0.2.4 | 0.2.4 | Current |
| apps/mobile | devDependencies | typescript | `6.0.3` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | Held by expo@57.0.24: TypeScript 6.0.3 is the verified workspace compiler for the SDK 57 cohort. |
| apps/server | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | workspace:packages/shared | workspace:packages/shared | Current |
| apps/server | dependencies | @google/genai | `^2.22.0` | 2.22.0 / 2.22.0 | 2.22.0 | 2.23.0 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| apps/server | dependencies | @livekit/protocol | `^1.51.0` | 1.51.0 / 1.51.0 | 1.51.0 | 1.52.0 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| apps/server | dependencies | jose | `^6.2.12` | 6.2.12 / 6.2.12 | 6.2.12 | 6.2.12 | Current |
| apps/server | dependencies | livekit-server-sdk | `^2.19.0` | 2.19.0 / 2.19.0 | 2.19.0 | 2.19.0 | Current |
| apps/server | dependencies | sharp | `^0.35.4` | 0.35.4 / 0.35.4 | 0.35.4 | 0.35.4 | Current |
| apps/server | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| apps/web | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | workspace:packages/design-tokens | workspace:packages/design-tokens | Current |
| apps/web | dependencies | react | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by react-native@0.86.3 and the shared web runtime: React 19.2.6 is the SDK 57-supported React 19.2 cohort and stays identical across mobile and web; typechecks, tests, exports, and the native build pass. |
| apps/web | dependencies | react-dom | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by react-native@0.86.3 and the shared web runtime: React 19.2.6 is the SDK 57-supported React 19.2 cohort and stays identical across mobile and web; typechecks, tests, exports, and the native build pass. |
| apps/web | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| apps/web | devDependencies | @types/react | `~19.2.2` | 19.2.14 / 19.2.14 | 19.2.14 | 19.3.0 | Held by react@19.2.6 shared cohort: React type packages stay on the React 19.2 line shared by mobile and web. |
| apps/web | devDependencies | @types/react-dom | `~19.2.1` | 19.2.3 / 19.2.3 | 19.2.3 | 19.3.0 | Held by react@19.2.6 shared cohort: React type packages stay on the React 19.2 line shared by mobile and web. |
| packages/design-tokens | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| packages/design-tokens | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |
| packages/shared | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| packages/shared | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |

## Independent browser toolchain

| Group | Dependency | Requested | Locked / installed | Candidate | Registry latest | Decision |
|---|---|---|---|---|---|---|
| devDependencies | @axe-core/playwright | `^4.13.0` | 4.13.0 / 4.13.0 | 4.13.0 | 4.13.0 | Current |
| devDependencies | @eslint/js | `^10.0.1` | 10.0.1 / 10.0.1 | 10.0.1 | 10.0.1 | Current |
| devDependencies | @playwright/test | `^1.63.0` | 1.63.0 / 1.63.0 | 1.63.0 | 1.63.0 | Current |
| devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| devDependencies | @types/pg | `^8.23.1` | 8.23.1 / 8.23.1 | 8.23.1 | 8.23.1 | Current |
| devDependencies | eslint | `^10.11.0` | 10.11.0 / 10.11.0 | 10.11.0 | 10.11.0 | Current |
| devDependencies | eslint-config-prettier | `^10.1.8` | 10.1.8 / 10.1.8 | 10.1.8 | 10.1.8 | Current |
| devDependencies | lighthouse | `^13.5.0` | 13.5.0 / 13.5.0 | 13.5.0 | 13.5.0 | Current |
| devDependencies | pg | `^8.23.0` | 8.23.0 / 8.23.0 | 8.23.0 | 8.23.0 | Current |
| devDependencies | playwright-lighthouse | `^4.0.0` | 4.0.0 / 4.0.0 | 4.0.0 | 4.0.0 | Current |
| devDependencies | typescript | `^6.0.3` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | typescript-eslint 8.70.0 declares TypeScript >=4.8.4 <6.1.0; 7.0.2 is outside that peer range. |
| devDependencies | typescript-eslint | `^8.70.0` | 8.70.0 / 8.70.0 | 8.70.0 | 8.70.0 | Current |

| Release-age exception | Published | Command | Evidence |
|---|---|---|---|
| eslint@10.11.0 | 2026-09-18T20:15:36.485Z | `bun add --cwd e2e --dev --minimum-release-age=0 eslint@^10.11.0` | ESLint 10.11.0 passes the e2e TypeScript and ESLint lane with @eslint/js 10.0.1 and typescript-eslint 8.70.0. |
| lighthouse@13.5.0 | 2026-09-18T14:13:55.261Z | `bun add --cwd e2e --dev --minimum-release-age=0 lighthouse@^13.5.0` | Lighthouse 13.5.0 satisfies playwright-lighthouse 4.0.0's >=10 peer range and passes the production audit thresholds. |

### Mobile SDK 57 baseline

- Expo 57.0.24; React Native 0.86.3; Hermes V1 (SDK 57 default).
- Platform minimums: Android 7+ (compile/target SDK 36/36); iOS 16.4+; Xcode 26.4+.
- Config plugins: @livekit/react-native-expo-plugin, @config-plugins/react-native-webrtc, expo-router, expo-splash-screen, expo-disable-pods-indexing, expo-audio, expo-secure-store, expo-asset, expo-image.
- Patch files: none.

| Git dependency | Requested | Locked commit |
|---|---|---|
| expo-disable-pods-indexing | `github:paulingalls/expo-disable-pods-indexing` | `fdd8959` |

| Release-age exception | Published | Command | Evidence |
|---|---|---|---|
| expo@57.0.24 | 2026-09-18T08:07:12.211Z | `bun install --minimum-release-age=0` | Normal-policy bun expo install --fix rejected this exact SDK 57 release; a subsequent normal-policy check passed. |
| expo-asset@57.0.18 | 2026-09-18T08:10:13.973Z | `bun install --minimum-release-age=0` | Normal-policy bun expo install --fix rejected this exact SDK 57 release; a subsequent normal-policy check passed. |
| expo-notifications@57.0.20 | 2026-09-18T08:09:56.492Z | `bun install --minimum-release-age=0` | Normal-policy bun expo install --fix rejected this exact SDK 57 release; a subsequent normal-policy check passed. |
| expo-router@57.0.22 | 2026-09-18T08:09:25.131Z | `bun install --minimum-release-age=0` | Normal-policy bun expo install --fix rejected this exact SDK 57 release; a subsequent normal-policy check passed. |

Compatibility exceptions:
- none

| Platform | Prebuild | Build | Device/install | Acceptance |
|---|---|---|---|---|
| iOS | passed | passed | passed on iOS 26.5 on story-208-sdk57 (`DC457949-200B-479A-95FD-611E33210F12`) | launch: passed; auth: passed |
| Android | passed | missing: no Android device was attached, so no native Android build is claimed | missing: adb devices returned no attached device | export: passed |

### Native LiveKit transport

- Status: passed on `DC457949-200B-479A-95FD-611E33210F12` with @livekit/react-native 2.12.0 / @livekit/react-native-webrtc 144.1.2.
- Python to iOS audio: named Python publisher subscription with RTC inbound packets_received > 0 and bytes_received > 0.
- iOS microphone to Python: named iOS microphone subscription with Python AudioStream frame count > 0.
- Game event and HUD: production SESSION_INIT packet rendered Upgrade Test Hero at Upgrade Test Room.
- Fault guards: received-audio, session-init-hud.
- Evidence: per-run machine-readable JSON and simulator PNG under ignored test-results/native-transport; driver: maestro; Expo MCP: unavailable_in_tool_catalog.

### Root resolution overrides

| Override | Requested | Reason |
|---|---|---|
| dnssd-advertise | `1.1.4` | Permanent native-development reproducibility pin for Expo CLI Bonjour discovery; Expo CLI 57.0.26 declares dnssd-advertise ^1.1.4. |

### Infrastructure holds

- `postgres:16-alpine` (PostgreSQL container): held outside this card. A database major migration requires separate application and data migration work.
- `valkey/valkey:8-alpine` (Valkey container): held outside this card. Container major upgrades are infrastructure work outside this library and browser-toolchain upgrade.

## Historical validation outcomes

| Lane | Recorded outcome | Evidence |
|---|---|---|
| bun install --frozen-lockfile | passed | Bun 1.4.2 accepted the root frozen lock without changes. |
| bun install --cwd e2e --frozen-lockfile | passed | Bun 1.4.2 accepted the independent e2e frozen lock without changes. |
| uv sync --project apps/agent --frozen | passed | uv 0.10.6 installed the agent lock under CPython 3.14.7. |
| uv sync --project scripts --frozen | passed | uv 0.10.6 installed the scripts lock under CPython 3.14.7. |
| dependency report --scope all | passed | All nine manifests, four locks, installed trees, CI, and rendered Markdown validated. |
| dependency report tests | passed | Fault suite passed, including named YAML steps and missing e2e inputs. |
| worktree bootstrap tests | passed | Tool pins, frozen installs, Chromium, seed ordering, and Docker ownership faults passed. |
| required e2e environment tests | passed | Six subprocess tests passed, including independent auth/config guard removals. |
| bun run lint | passed | TypeScript, ESLint, Prettier, Ruff, Pyright, and Python format checks passed. |
| bun run lint:e2e | passed | Independent frozen install, TypeScript, and ESLint passed. |
| bun run test:python | passed | 7000 non-acceptance Python tests passed. |
| bun run test:server | passed | Server unit and database/Redis integration lanes passed. |
| Bun scripts/shared/design-tokens tests | passed | All three explicitly selected Bun test corpora passed. |
| Bun mobile tests | passed | 508 mobile tests passed. |
| Bun web tests | passed | 204 web tests passed. |
| full Playwright suite | passed | Full upgraded browser suite passed after the final app/server graph. |
| mobile verify:upgrade | passed | Expo doctor passed 21/21 checks and iOS, Android, and web exports completed. |
| mobile verify:native-build | passed | Clean iOS build succeeded; launch and auth flows passed 2/2 on the owned simulator. |
| mobile verify:native-transport | passed | Owned-simulator audio, microphone, event/HUD, and fault runs passed. |
| bun run test:acceptance:nollm | passed | 270 acceptance tests passed; 9 real-LLM tests were deselected. |
| Playwright web project | passed | 40 production marketing tests passed. |
| Playwright web-lighthouse project | passed | 4 tests passed; performance, SEO, and accessibility each scored 100. |
| Playwright chromium project | passed | 40 authenticated mobile-web tests passed. |
| clean-worktree bootstrap | passed | Detached 89d5efff proof installed four frozen locks and Chromium, migrated and seeded isolated ports 56032/56979, and passed report, seed, environment, and aggregate checks; owned containers and worktree cleaned. |
| Android device check | missing | adb devices returned no attached device. |
| real-LLM acceptance | required at sprint close | Credentialed cost-bearing lane was not run by the story executor. |

The committed agent/scripts `uv.lock` files and root/e2e `bun.lock` files are the exact transitive dependency records.
