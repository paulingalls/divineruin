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
| apps/mobile | dependencies | @config-plugins/react-native-webrtc | `14.0.0` | 14.0.0 / 14.0.0 | 14.0.0 | 15.0.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | workspace:packages/design-tokens | workspace:packages/design-tokens | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | workspace:packages/shared | workspace:packages/shared | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo-google-fonts/cormorant-garamond | `^0.4.1` | 0.4.1 / 0.4.1 | 0.4.1 | 0.4.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo-google-fonts/crimson-pro | `^0.4.2` | 0.4.2 / 0.4.2 | 0.4.2 | 0.4.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo-google-fonts/ibm-plex-mono | `^0.4.1` | 0.4.1 / 0.4.1 | 0.4.1 | 0.4.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @expo/vector-icons | `^15.0.2` | 15.1.1 / 15.1.1 | 15.1.1 | 15.1.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/components-core | `^0.12.13` | 0.12.13 / 0.12.13 | 0.12.13 | 0.12.15 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/components-react | `^2.9.20` | 2.9.20 / 2.9.20 | 2.9.20 | 2.9.24 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/react-native | `^2.9.6` | 2.9.6 / 2.9.6 | 2.9.6 | 3.0.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/react-native-expo-plugin | `^1.0.2` | 1.0.2 / 1.0.2 | 1.0.2 | 1.0.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @livekit/react-native-webrtc | `^144.0.0` | 144.0.0 / 144.0.0 | 144.0.0 | 144.2.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @react-native-async-storage/async-storage | `2.2.0` | 2.2.0 / 2.2.0 | 2.2.0 | 3.1.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @react-native-community/slider | `^5.1.2` | 5.1.2 / 5.1.2 | 5.1.2 | 5.2.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @react-navigation/bottom-tabs | `^7.15.5` | 7.15.7 / 7.15.7 | 7.15.7 | 7.19.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @react-navigation/elements | `^2.9.12` | 2.9.12 / 2.9.12 | 2.9.12 | 2.9.43 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | @react-navigation/native | `^7.1.33` | 7.2.0 / 7.2.0 | 7.2.0 | 7.4.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo | `55.0.23` | 55.0.23 / 55.0.23 | 55.0.23 | 57.0.24 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-asset | `55.0.17` | 55.0.17 / 55.0.17 | 55.0.17 | 57.0.18 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-audio | `55.0.14` | 55.0.14 / 55.0.14 | 55.0.14 | 57.0.5 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-constants | `55.0.16` | 55.0.16 / 55.0.16 | 55.0.16 | 57.0.19 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-crypto | `55.0.16` | 55.0.16 / 55.0.16 | 55.0.16 | 57.0.3 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-dev-client | `55.0.32` | 55.0.32 / 55.0.32 | 55.0.32 | 57.0.19 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-device | `55.0.16` | 55.0.16 / 55.0.16 | 55.0.16 | 57.0.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-disable-pods-indexing | `github:paulingalls/expo-disable-pods-indexing` | github:paulingalls/expo-disable-pods-indexing#fdd8959 / github:paulingalls/expo-disable-pods-indexing#fdd8959 | github:paulingalls/expo-disable-pods-indexing#fdd8959 | github:paulingalls/expo-disable-pods-indexing#fdd8959 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-font | `55.0.7` | 55.0.7 / 55.0.7 | 55.0.7 | 57.0.4 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-glass-effect | `55.0.11` | 55.0.11 / 55.0.11 | 55.0.11 | 57.0.3 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-haptics | `55.0.14` | 55.0.14 / 55.0.14 | 55.0.14 | 57.0.3 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-image | `55.0.10` | 55.0.10 / 55.0.10 | 55.0.10 | 57.0.5 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-linear-gradient | `55.0.13` | 55.0.13 / 55.0.13 | 55.0.13 | 57.0.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-linking | `55.0.15` | 55.0.15 / 55.0.15 | 55.0.15 | 57.0.10 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-notifications | `55.0.22` | 55.0.22 / 55.0.22 | 55.0.22 | 57.0.20 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-router | `55.0.14` | 55.0.14 / 55.0.14 | 55.0.14 | 57.0.22 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-secure-store | `55.0.13` | 55.0.13 / 55.0.13 | 55.0.13 | 57.0.4 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-splash-screen | `55.0.20` | 55.0.20 / 55.0.20 | 55.0.20 | 57.0.9 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-status-bar | `55.0.6` | 55.0.6 / 55.0.6 | 55.0.6 | 57.0.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-symbols | `55.0.8` | 55.0.8 / 55.0.8 | 55.0.8 | 57.0.3 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-system-ui | `55.0.17` | 55.0.17 / 55.0.17 | 55.0.17 | 57.0.4 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | expo-web-browser | `55.0.15` | 55.0.15 / 55.0.15 | 55.0.15 | 57.0.3 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | livekit-client | `^2.18.0` | 2.18.0 / 2.18.0 | 2.18.0 | 2.22.3 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-dom | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native | `0.83.6` | 0.83.6 / 0.83.6 | 0.83.6 | 0.87.1 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-gesture-handler | `~2.30.0` | 2.30.0 / 2.30.0 | 2.30.0 | 3.3.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-reanimated | `4.2.1` | 4.2.1 / 4.2.1 | 4.2.1 | 4.7.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-safe-area-context | `~5.6.2` | 5.6.2 / 5.6.2 | 5.6.2 | 5.10.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-screens | `~4.23.0` | 4.23.0 / 4.23.0 | 4.23.0 | 4.28.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-url-polyfill | `^3.0.0` | 3.0.0 / 3.0.0 | 3.0.0 | 4.0.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-web | `~0.21.0` | 0.21.2 / 0.21.2 | 0.21.2 | 0.21.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | react-native-worklets | `0.7.4` | 0.7.4 / 0.7.4 | 0.7.4 | 0.12.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | dependencies | zustand | `^5.0.12` | 5.0.12 / 5.0.12 | 5.0.12 | 5.0.15 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | devDependencies | @types/react | `~19.2.2` | 19.2.14 / 19.2.14 | 19.2.14 | 19.3.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | devDependencies | @types/react-dom | `~19.2.1` | 19.2.3 / 19.2.3 | 19.2.3 | 19.3.0 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/mobile | devDependencies | typescript | `~5.9.2` | 5.9.3 / 5.9.3 | 5.9.3 | 7.0.2 | Held by story 207/208: Expo-managed mobile dependency cohort is selected by stories 207/208. |
| apps/server | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | workspace:packages/shared | workspace:packages/shared | Current |
| apps/server | dependencies | @google/genai | `^2.22.0` | 2.22.0 / 2.22.0 | 2.22.0 | 2.23.0 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| apps/server | dependencies | @livekit/protocol | `^1.51.0` | 1.51.0 / 1.51.0 | 1.51.0 | 1.52.0 | Registry latest is inside the unchanged seven-day minimum release age; the candidate is the newest eligible stable release. |
| apps/server | dependencies | jose | `^6.2.12` | 6.2.12 / 6.2.12 | 6.2.12 | 6.2.12 | Current |
| apps/server | dependencies | livekit-server-sdk | `^2.19.0` | 2.19.0 / 2.19.0 | 2.19.0 | 2.19.0 | Current |
| apps/server | dependencies | sharp | `^0.35.4` | 0.35.4 / 0.35.4 | 0.35.4 | 0.35.4 | Current |
| apps/server | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| apps/web | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | workspace:packages/design-tokens | workspace:packages/design-tokens | Current |
| apps/web | dependencies | react | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: Web React and type versions stay aligned with the Expo cohort selected by stories 207/208. |
| apps/web | dependencies | react-dom | `19.2.6` | 19.2.6 / 19.2.6 | 19.2.6 | 19.3.0 | Held by story 207/208: Web React and type versions stay aligned with the Expo cohort selected by stories 207/208. |
| apps/web | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| apps/web | devDependencies | @types/react | `~19.2.2` | 19.2.14 / 19.2.14 | 19.2.14 | 19.3.0 | Held by story 207/208: Web React and type versions stay aligned with the Expo cohort selected by stories 207/208. |
| apps/web | devDependencies | @types/react-dom | `~19.2.1` | 19.2.3 / 19.2.3 | 19.2.3 | 19.3.0 | Held by story 207/208: Web React and type versions stay aligned with the Expo cohort selected by stories 207/208. |
| packages/design-tokens | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| packages/design-tokens | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |
| packages/shared | devDependencies | @types/bun | `1.4.2` | 1.4.2 / 1.4.2 | 1.4.2 | 1.4.2 | Current |
| packages/shared | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | TypeScript 7.0.2 exceeds typescript-eslint 8.70.0 peer range >=4.8.4 <6.1.0; 6.0.3 is the newest compatible stable release. |

E2E exclusion: Independent manifest, lock, and default service DSNs are owned by story 210; its browser surface is rerun after stories 207/208 land the shared React cohort.

The committed `uv.lock` and root `bun.lock` files are the exact transitive dependency records.
