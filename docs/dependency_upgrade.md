# Dependency upgrade

Registry snapshot: 2026-09-18  
Toolchain: CPython 3.14.7; uv 0.10.6; Bun 1.4.2

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
| apps/mobile | dependencies | @config-plugins/react-native-webrtc | `15.0.2` | 15.0.2 / 15.0.2 | 15.0.2 | 15.0.2 | Held by story 207/208: Config plugin 15 is the first release whose installed peer contract accepts Expo 56. |
| apps/mobile | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | workspace:packages/design-tokens | workspace:packages/design-tokens | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | workspace:packages/shared | workspace:packages/shared | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo-google-fonts/cormorant-garamond | `^0.4.1` | 0.4.1 / 0.4.1 | 0.4.1 | 0.4.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo-google-fonts/crimson-pro | `^0.4.2` | 0.4.2 / 0.4.2 | 0.4.2 | 0.4.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo-google-fonts/ibm-plex-mono | `^0.4.1` | 0.4.1 / 0.4.1 | 0.4.1 | 0.4.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo/vector-icons | `^15.0.2` | 15.1.1 / 15.1.1 | 15.1.1 | 15.1.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/components-core | `^0.12.13` | 0.12.13 / 0.12.13 | 0.12.13 | 0.12.15 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/components-react | `^2.9.20` | 2.9.20 / 2.9.20 | 2.9.20 | 2.9.24 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/react-native | `2.12.0` | 2.12.0 / 2.12.0 | 2.12.0 | 3.0.0 | Held by story 207/208: The seven-day policy selects LiveKit React Native 2.12.0; its installed peers require WebRTC ^144.1.2 and livekit-client ^2.19.0. |
| apps/mobile | dependencies | @livekit/react-native-expo-plugin | `^1.0.2` | 1.0.2 / 1.0.2 | 1.0.2 | 1.0.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/react-native-webrtc | `144.2.0` | 144.2.0 / 144.2.0 | 144.2.0 | 144.2.0 | Held by story 207/208: LiveKit React Native 2.12 accepts this single installed WebRTC resolution. |
| apps/mobile | dependencies | @react-native-async-storage/async-storage | `2.2.0` | 2.2.0 / 2.2.0 | 2.2.0 | 3.1.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @react-native-community/slider | `5.2.0` | 5.2.0 / 5.2.0 | 5.2.0 | 5.2.1 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo | `56.0.22` | 56.0.22 / 56.0.22 | 56.0.22 | 57.0.24 | Held by story 207/208: Expo SDK 56 CLI required expo@~56.0.22 on 2026-09-18; expo@56.0.22 was published 2026-09-17T22:09:28.356Z and Bun's seven-day release-age policy rejected it, so story 207 used the authorized command-scoped exception for that exact version. Story 208 owns SDK 57. |
| apps/mobile | dependencies | expo-asset | `56.0.24` | 56.0.24 / 56.0.24 | 56.0.24 | 57.0.18 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-audio | `56.0.13` | 56.0.13 / 56.0.13 | 56.0.13 | 57.0.5 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-build-properties | `56.0.27` | 56.0.27 / 56.0.27 | 56.0.27 | 57.0.21 | Held by story 207/208: Expo SDK 56 uses this config plugin to opt out of the documented Hermes V1 memory regression. Legacy Hermes requires React Native source builds on iOS and Android; story 208 owns removal with SDK 57. |
| apps/mobile | dependencies | expo-constants | `56.0.26` | 56.0.26 / 56.0.26 | 56.0.26 | 57.0.19 | Held by story 207/208: Expo SDK 56 CLI required expo-constants@~56.0.26 on 2026-09-18; expo-constants@56.0.26 was published 2026-09-17T22:10:15.391Z and Bun's seven-day release-age policy rejected it, so story 207 used the authorized command-scoped exception for that exact version. Story 208 owns SDK 57. |
| apps/mobile | dependencies | expo-crypto | `56.0.5` | 56.0.5 / 56.0.5 | 56.0.5 | 57.0.3 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-dev-client | `56.0.27` | 56.0.27 / 56.0.27 | 56.0.27 | 57.0.19 | Held by story 207/208: Expo SDK 56 CLI required expo-dev-client@~56.0.27 on 2026-09-18; expo-dev-client@56.0.27 was published 2026-09-17T22:09:38.863Z and Bun's seven-day release-age policy rejected it, so story 207 used the authorized command-scoped exception for that exact version. Story 208 owns SDK 57. |
| apps/mobile | dependencies | expo-device | `56.0.4` | 56.0.4 / 56.0.4 | 56.0.4 | 57.0.2 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-disable-pods-indexing | `github:paulingalls/expo-disable-pods-indexing` | github:paulingalls/expo-disable-pods-indexing#fdd8959 / github:paulingalls/expo-disable-pods-indexing#fdd8959 | github:paulingalls/expo-disable-pods-indexing#fdd8959 | github:paulingalls/expo-disable-pods-indexing#fdd8959 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-font | `56.0.7` | 56.0.7 / 56.0.7 | 56.0.7 | 57.0.4 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-glass-effect | `56.0.4` | 56.0.4 / 56.0.4 | 56.0.4 | 57.0.3 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-haptics | `56.0.3` | 56.0.3 / 56.0.3 | 56.0.3 | 57.0.3 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-image | `56.0.13` | 56.0.13 / 56.0.13 | 56.0.13 | 57.0.5 | Held by story 207/208: Expo SDK 56 CLI required expo-image@~56.0.13 on 2026-09-18; expo-image@56.0.13 was published 2026-09-17T22:11:43.001Z and Bun's seven-day release-age policy rejected it, so story 207 used the authorized command-scoped exception for that exact version. Story 208 owns SDK 57. |
| apps/mobile | dependencies | expo-linear-gradient | `56.0.4` | 56.0.4 / 56.0.4 | 56.0.4 | 57.0.2 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-linking | `56.0.18` | 56.0.18 / 56.0.18 | 56.0.18 | 57.0.10 | Held by story 207/208: Expo SDK 56 CLI required expo-linking@~56.0.18 on 2026-09-18; expo-linking@56.0.18 was published 2026-09-17T22:08:50.571Z and Bun's seven-day release-age policy rejected it, so story 207 used the authorized command-scoped exception for that exact version. Story 208 owns SDK 57. |
| apps/mobile | dependencies | expo-notifications | `56.0.25` | 56.0.25 / 56.0.25 | 56.0.25 | 57.0.20 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-router | `56.2.21` | 56.2.21 / 56.2.21 | 56.2.21 | 57.0.22 | Held by story 207/208: Expo SDK 56 CLI required expo-router@~56.2.21 on 2026-09-18; expo-router@56.2.21 was published 2026-09-17T22:09:04.327Z and Bun's seven-day release-age policy rejected it, so story 207 used the authorized command-scoped exception for that exact version. Story 208 owns SDK 57. |
| apps/mobile | dependencies | expo-secure-store | `56.0.4` | 56.0.4 / 56.0.4 | 56.0.4 | 57.0.4 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-splash-screen | `56.0.15` | 56.0.15 / 56.0.15 | 56.0.15 | 57.0.9 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-status-bar | `56.0.4` | 56.0.4 / 56.0.4 | 56.0.4 | 57.0.1 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-symbols | `56.0.7` | 56.0.7 / 56.0.7 | 56.0.7 | 57.0.3 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-system-ui | `56.0.5` | 56.0.5 / 56.0.5 | 56.0.5 | 57.0.4 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | expo-web-browser | `56.0.6` | 56.0.6 / 56.0.6 | 56.0.6 | 57.0.3 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | livekit-client | `^2.19.0` | 2.22.3 / 2.22.3 | 2.22.3 | 2.22.3 | Held by story 207/208: LiveKit React Native 2.12 requires livekit-client ^2.19.0. |
| apps/mobile | dependencies | react | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: React 19.2.6 stays aligned across mobile and web. React Native 0.85.3 accepts ^19.2.3 and React DOM 19.2.6 accepts ^19.2.6; mobile and web runtime suites, builds, and exports pass, so Expo validation excludes only react and react-dom. |
| apps/mobile | dependencies | react-dom | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: React 19.2.6 stays aligned across mobile and web. React Native 0.85.3 accepts ^19.2.3 and React DOM 19.2.6 accepts ^19.2.6; mobile and web runtime suites, builds, and exports pass, so Expo validation excludes only react and react-dom. |
| apps/mobile | dependencies | react-native | `0.85.3` | 0.85.3 / 0.85.3 | 0.85.3 | 0.87.1 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | react-native-gesture-handler | `2.31.1` | 2.31.1 / 2.31.1 | 2.31.1 | 3.3.0 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | react-native-reanimated | `4.3.1` | 4.3.1 / 4.3.1 | 4.3.1 | 4.7.0 | Held by story 207/208: Expo SDK 56 requires this version. SDK 56 has a known Hermes V1 memory regression affecting Reanimated and Worklets, so the app uses the supported legacy Hermes opt-out; story 208 owns the SDK 57 resolution. |
| apps/mobile | dependencies | react-native-safe-area-context | `5.7.0` | 5.7.0 / 5.7.0 | 5.7.0 | 5.10.0 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | react-native-screens | `4.26.0` | 4.26.0 / 4.26.0 | 4.26.0 | 4.28.0 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | dependencies | react-native-url-polyfill | `^3.0.0` | 3.0.0 / 3.0.0 | 3.0.0 | 4.0.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-web | `~0.21.0` | 0.21.2 / 0.21.2 | 0.21.2 | 0.21.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-worklets | `0.8.3` | 0.8.3 / 0.8.3 | 0.8.3 | 0.12.2 | Held by story 207/208: Expo SDK 56 requires this version. SDK 56 has a known Hermes V1 memory regression affecting Reanimated and Worklets, so the app uses the supported legacy Hermes opt-out; story 208 owns the SDK 57 resolution. |
| apps/mobile | dependencies | zustand | `^5.0.12` | 5.0.12 / 5.0.12 | 5.0.12 | 5.0.15 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | devDependencies | @types/react | `~19.2.2` | 19.2.14 / 19.2.14 | 19.2.14 | 19.3.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | devDependencies | @types/react-dom | `~19.2.1` | 19.2.3 / 19.2.3 | 19.2.3 | 19.3.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | devDependencies | typescript | `6.0.3` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | Held by story 207/208: Expo SDK 56 CLI selected this compatible mobile dependency; story 208 owns the SDK 57 cohort. |
| apps/mobile | devDependencies | expo-mcp | `~0.2.1` | 0.2.4 / 0.2.4 | 0.2.4 | 0.2.4 | Held by story 207/208: Installed with `bun expo install expo-mcp --dev` for the Expo local MCP server. Run `bun expo whoami`, then `bun run start:mcp`; reconnect or restart the MCP client after the Expo server starts or stops. |
| apps/server | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | workspace:packages/shared | workspace:packages/shared | Current |
| apps/server | dependencies | @google/genai | `^2.22.0` | 2.22.0 / 2.22.0 | 2.22.0 | 2.23.0 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| apps/server | dependencies | @livekit/protocol | `^1.51.0` | 1.51.0 / 1.51.0 | 1.51.0 | 1.52.0 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| apps/server | dependencies | jose | `^6.2.12` | 6.2.12 / 6.2.12 | 6.2.12 | 6.2.12 | Current |
| apps/server | dependencies | livekit-server-sdk | `^2.19.0` | 2.19.0 / 2.19.0 | 2.19.0 | 2.19.0 | Current |
| apps/server | dependencies | sharp | `^0.35.4` | 0.35.4 / 0.35.4 | 0.35.4 | 0.35.4 | Current |
| apps/server | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| apps/web | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | workspace:packages/design-tokens | workspace:packages/design-tokens | Current |
| apps/web | dependencies | react | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: React 19.2.6 stays aligned across mobile and web. React Native 0.85.3 accepts ^19.2.3 and React DOM 19.2.6 accepts ^19.2.6; mobile and web runtime suites, builds, and exports pass, so Expo validation excludes only react and react-dom. |
| apps/web | dependencies | react-dom | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: React 19.2.6 stays aligned across mobile and web. React Native 0.85.3 accepts ^19.2.3 and React DOM 19.2.6 accepts ^19.2.6; mobile and web runtime suites, builds, and exports pass, so Expo validation excludes only react and react-dom. |
| apps/web | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| apps/web | devDependencies | @types/react | `~19.2.2` | 19.2.14 / 19.2.14 | 19.2.14 | 19.3.0 | Held by story 207/208: Web React and type versions stay aligned with the Expo cohort selected by stories 207/208. |
| apps/web | devDependencies | @types/react-dom | `~19.2.1` | 19.2.3 / 19.2.3 | 19.2.3 | 19.3.0 | Held by story 207/208: Web React and type versions stay aligned with the Expo cohort selected by stories 207/208. |
| packages/design-tokens | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| packages/design-tokens | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |
| packages/shared | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| packages/shared | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |

### Root resolution overrides

| Override | Requested | Reason |
|---|---|---|
| dnssd-advertise | `1.1.4` | Root resolution override retained unchanged. |
| expo-constants | `56.0.26` | Aligns expo-asset with the Expo SDK 56 CLI-selected direct native module version. |
| hermes-compiler | `0.15.0` | expo-build-properties requires this compiler for the supported SDK 56 legacy Hermes opt-out. |
| react-native-screens | `4.26.0` | Aligns Expo Router with the Expo SDK 56 CLI-selected direct native module version. |

E2E exclusion: Independent manifest, lock, and default service DSNs are owned by story 210; its browser surface is rerun after stories 207/208 land the shared React cohort.

The committed `uv.lock` and root `bun.lock` files are the exact transitive dependency records.
