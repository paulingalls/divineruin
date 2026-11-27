# Dependency upgrade

Registry snapshot: 2026-11-26 (acquisition completed 2026-11-27T02:16:27.654900+00:00)

Toolchain: CPython 3.14.7, uv 0.13.9, Bun 1.4.5

Execution evidence: `--check --scope all` exited 0 at `ed26195b99cb2bdd673960b0a389fc1644b6af97` on 2026-11-27T02:22:05Z.

## Python environments

### apps/agent

| Group | Dependency | Requested | Resolved / installed | Latest stable | Holdback |
|---|---|---|---|---|---|
| runtime | anthropic | `>=1.17.0,<2` | 1.17.0 / 1.17.0 | 2.14.0 | `livekit-plugins-anthropic==1.8.13` requires `anthropic<2,>=1.8`. The agent manifest also caps Anthropic below 2. |
| runtime | asyncpg | `>=0.32.0,<1` | 0.32.0 / 0.32.0 | 0.32.0 | — |
| runtime | httpx | `>=0.28.1` | 0.28.1 / 0.28.1 | 0.29.0 | `apps/agent/pyproject.toml` sets `exclude-newer = "7 days"`. 0.29.0 was published 2026-11-26T15:58:35.703131Z. |
| runtime | livekit-agents | `~=1.8.13` | 1.8.13 / 1.8.13 | 1.9.0 | `apps/agent/pyproject.toml` requests `livekit-agents~=1.8.13`, which excludes 1.9.0. |
| runtime | livekit-plugins-anthropic | `~=1.8.13` | 1.8.13 / 1.8.13 | 1.9.0 | `apps/agent/pyproject.toml` requests `livekit-plugins-anthropic~=1.8.13`, which excludes 1.9.0. |
| runtime | livekit-plugins-deepgram | `~=1.8.13` | 1.8.13 / 1.8.13 | 1.9.0 | `apps/agent/pyproject.toml` requests `livekit-plugins-deepgram~=1.8.13`, which excludes 1.9.0. |
| runtime | livekit-plugins-inworld | `~=1.8.13` | 1.8.13 / 1.8.13 | 1.9.0 | `apps/agent/pyproject.toml` requests `livekit-plugins-inworld~=1.8.13`, which excludes 1.9.0. |
| runtime | livekit-plugins-openai | `~=1.8.13` | 1.8.13 / 1.8.13 | 1.9.0 | `apps/agent/pyproject.toml` requests `livekit-plugins-openai~=1.8.13`, which excludes 1.9.0. |
| runtime | redis | `>=8.1.0` | 8.1.0 / 8.1.0 | 8.2.0 | `apps/agent/pyproject.toml` sets `exclude-newer = "7 days"`. 8.2.0 was published 2026-11-23T08:31:55.011623Z. |
| dev | docker | `>=7.2.0` | 7.2.0 / 7.2.0 | 7.2.0 | — |
| dev | httpx2 | `>=2,<3` | 2.16.2 / 2.16.2 | 2.16.2 | — |
| dev | pillow | `>=13.0.0` | 13.0.0 / 13.0.0 | 13.0.0 | — |
| dev | pyright | `>=1.1.414` | 1.1.414 / 1.1.414 | 1.1.414 | — |
| dev | pytest | `>=9.2.0` | 9.2.0 / 9.2.0 | 9.2.0 | — |
| dev | pytest-asyncio | `>=1.5.0,<2` | 1.5.0 / 1.5.0 | 1.5.0 | — |
| dev | pytest-bdd | `>=9.0.1` | 9.0.1 / 9.0.1 | 9.0.1 | — |
| dev | pytest-cov | `>=7.1.0` | 7.1.0 / 7.1.0 | 7.1.0 | — |
| dev | pytest-timeout | `>=2.4.0` | 2.4.0 / 2.4.0 | 2.4.0 | — |
| dev | pytest-xdist | `>=3.8.0` | 3.8.0 / 3.8.0 | 3.8.0 | — |
| dev | ruff | `>=0.17.6,<1` | 0.17.6 / 0.17.6 | 0.17.6 | — |
| dev | testcontainers | `>=4.15.0` | 4.15.0 / 4.15.0 | 4.15.0 | — |

### scripts

| Group | Dependency | Requested | Resolved / installed | Latest stable | Holdback |
|---|---|---|---|---|---|
| runtime | asyncpg | `>=0.32.0,<1` | 0.32.0 / 0.32.0 | 0.32.0 | — |

## Bun workspace

Release age policy: 604800 seconds.

Candidate is the version selected in the committed graph. Registry columns show — for Git and workspace sources.

| Project | Group | Dependency | Requested | Locked / installed | Candidate | Registry latest | Decision |
|---|---|---|---|---|---|---|---|
| . | devDependencies | @eslint/js | `^10.0.1` | 10.0.1 / 10.0.1 | 10.0.1 | 10.0.1 | Current |
| . | devDependencies | @pi-innovations/proof | `git+https://github.com/paulingalls/proof.git#v0.34.1` | github:paulingalls/proof#059e14b / github:paulingalls/proof#059e14b | — | — | Git source pinned by the manifest and lock |
| . | devDependencies | @types/bun | `1.4.4` | 1.4.4 / 1.4.4 | 1.4.4 | 1.4.5 | Held by package.json: The requested range `1.4.4` excludes 1.4.5. |
| . | devDependencies | eslint | `^10.15.0` | 10.15.0 / 10.15.0 | 10.15.0 | 10.15.0 | Current |
| . | devDependencies | eslint-config-prettier | `^10.1.8` | 10.1.8 / 10.1.8 | 10.1.8 | 10.1.8 | Current |
| . | devDependencies | eslint-plugin-react-hooks | `^7.1.1` | 7.1.1 / 7.1.1 | 7.1.1 | 7.1.1 | Current |
| . | devDependencies | eslint-plugin-react-refresh | `^0.5.8` | 0.5.8 / 0.5.8 | 0.5.8 | 0.5.8 | Current |
| . | devDependencies | prettier | `^3.10.1` | 3.10.1 / 3.10.1 | 3.10.1 | 3.10.1 | Current |
| . | devDependencies | typescript | `6.0.3` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | Held by typescript-eslint@8.73.0: Its TypeScript peer range is `>=4.8.4 <6.1.0`. `package.json` requests `6.0.3`. |
| . | devDependencies | typescript-eslint | `^8.73.0` | 8.73.0 / 8.73.0 | 8.73.0 | 8.74.0 | Held by bunfig.toml: The seven-day Bun policy applies to 8.74.0, published 2026-11-23T17:06:58.945Z. |
| . | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | Held by typescript-eslint@8.73.0: Its TypeScript peer range is `>=4.8.4 <6.1.0`. `package.json` requests `>=5.9 <6.1`. |
| apps/mobile | dependencies | @config-plugins/react-native-webrtc | `15.0.2` | 15.0.2 / 15.0.2 | 15.0.2 | 15.0.2 | Current |
| apps/mobile | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | — | — | Workspace source |
| apps/mobile | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | — | — | Workspace source |
| apps/mobile | dependencies | @expo-google-fonts/cormorant-garamond | `^0.4.1` | 0.4.1 / 0.4.1 | 0.4.1 | 0.4.1 | Current |
| apps/mobile | dependencies | @expo-google-fonts/crimson-pro | `^0.4.2` | 0.4.2 / 0.4.2 | 0.4.2 | 0.4.2 | Current |
| apps/mobile | dependencies | @expo-google-fonts/ibm-plex-mono | `^0.4.2` | 0.4.2 / 0.4.2 | 0.4.2 | 0.4.2 | Current |
| apps/mobile | dependencies | @expo/vector-icons | `^15.1.1` | 15.1.1 / 15.1.1 | 15.1.1 | 15.1.1 | Current |
| apps/mobile | dependencies | @livekit/components-core | `^0.12.16` | 0.12.16 / 0.12.16 | 0.12.16 | 0.12.17 | Held by bunfig.toml: The seven-day Bun policy applies to 0.12.17, published 2026-11-20T14:44:52.126Z. |
| apps/mobile | dependencies | @livekit/components-react | `^2.9.25` | 2.9.25 / 2.9.25 | 2.9.25 | 2.9.26 | Held by bunfig.toml: The seven-day Bun policy applies to 2.9.26, published 2026-11-20T14:43:54.432Z. |
| apps/mobile | dependencies | @livekit/react-native | `3.2.0` | 3.2.0 / 3.2.0 | 3.2.0 | 3.2.0 | Current |
| apps/mobile | dependencies | @livekit/react-native-expo-plugin | `1.2.0` | 1.2.0 / 1.2.0 | 1.2.0 | 1.2.0 | Current |
| apps/mobile | dependencies | @livekit/react-native-webrtc | `150.2.0` | 150.2.0 / 150.2.0 | 150.2.0 | 150.2.0 | Current |
| apps/mobile | dependencies | @react-native-async-storage/async-storage | `2.2.0` | 2.2.0 / 2.2.0 | 2.2.0 | 3.1.1 | Held by expo@58.1.0: Expo recommends `2.2.0` and the mobile manifest pins `2.2.0`. |
| apps/mobile | dependencies | @react-native-community/slider | `5.2.1` | 5.2.1 / 5.2.1 | 5.2.1 | 5.2.2 | Held by expo@58.1.0: Expo recommends `5.2.1` and the mobile manifest pins `5.2.1`. |
| apps/mobile | dependencies | expo | `58.1.0` | 58.1.0 / 58.1.0 | 58.1.0 | 58.1.0 | Current |
| apps/mobile | dependencies | expo-asset | `58.0.21` | 58.0.21 / 58.0.21 | 58.0.21 | 58.0.21 | Current |
| apps/mobile | dependencies | expo-audio | `58.0.12` | 58.0.12 / 58.0.12 | 58.0.12 | 58.0.12 | Current |
| apps/mobile | dependencies | expo-crypto | `58.0.9` | 58.0.9 / 58.0.9 | 58.0.9 | 58.0.9 | Current |
| apps/mobile | dependencies | expo-dev-client | `58.0.22` | 58.0.22 / 58.0.22 | 58.0.22 | 58.0.22 | Current |
| apps/mobile | dependencies | expo-device | `58.0.5` | 58.0.5 / 58.0.5 | 58.0.5 | 58.0.5 | Current |
| apps/mobile | dependencies | expo-disable-pods-indexing | `github:paulingalls/expo-disable-pods-indexing` | github:paulingalls/expo-disable-pods-indexing#fdd8959 / github:paulingalls/expo-disable-pods-indexing#fdd8959 | — | — | Git source pinned by the manifest and lock |
| apps/mobile | dependencies | expo-font | `58.0.12` | 58.0.12 / 58.0.12 | 58.0.12 | 58.0.12 | Current |
| apps/mobile | dependencies | expo-glass-effect | `58.0.6` | 58.0.6 / 58.0.6 | 58.0.6 | 58.0.6 | Current |
| apps/mobile | dependencies | expo-haptics | `58.0.8` | 58.0.8 / 58.0.8 | 58.0.8 | 58.0.8 | Current |
| apps/mobile | dependencies | expo-image | `58.0.19` | 58.0.19 / 58.0.19 | 58.0.19 | 58.0.19 | Current |
| apps/mobile | dependencies | expo-linear-gradient | `58.0.4` | 58.0.4 / 58.0.4 | 58.0.4 | 58.0.4 | Current |
| apps/mobile | dependencies | expo-linking | `58.0.17` | 58.0.17 / 58.0.17 | 58.0.17 | 58.0.17 | Current |
| apps/mobile | dependencies | expo-notifications | `58.1.10` | 58.1.10 / 58.1.10 | 58.1.10 | 58.1.10 | Current |
| apps/mobile | dependencies | expo-router | `58.0.33` | 58.0.33 / 58.0.33 | 58.0.33 | 58.0.33 | Current |
| apps/mobile | dependencies | expo-secure-store | `58.0.3` | 58.0.3 / 58.0.3 | 58.0.3 | 58.0.3 | Current |
| apps/mobile | dependencies | expo-splash-screen | `58.0.15` | 58.0.15 / 58.0.15 | 58.0.15 | 58.0.15 | Current |
| apps/mobile | dependencies | expo-status-bar | `58.0.5` | 58.0.5 / 58.0.5 | 58.0.5 | 58.0.5 | Current |
| apps/mobile | dependencies | expo-symbols | `58.0.5` | 58.0.5 / 58.0.5 | 58.0.5 | 58.0.5 | Current |
| apps/mobile | dependencies | expo-system-ui | `58.0.7` | 58.0.7 / 58.0.7 | 58.0.7 | 58.0.7 | Current |
| apps/mobile | dependencies | expo-web-browser | `58.1.0` | 58.1.0 / 58.1.0 | 58.1.0 | 58.1.0 | Current |
| apps/mobile | dependencies | livekit-client | `^2.24.1` | 2.24.1 / 2.24.1 | 2.24.1 | 2.25.0 | Held by bunfig.toml: The seven-day Bun policy applies to 2.25.0, published 2026-11-20T12:42:16.828Z. |
| apps/mobile | dependencies | react | `19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.1 | Held by expo@58.1.0: Expo recommends `19.3.0` and the mobile manifest pins `19.3.0`. |
| apps/mobile | dependencies | react-dom | `19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.1 | Held by expo@58.1.0: Expo recommends `19.3.0` and the mobile manifest pins `19.3.0`. |
| apps/mobile | dependencies | react-native | `0.88.1` | 0.88.1 / 0.88.1 | 0.88.1 | 0.88.1 | Current |
| apps/mobile | dependencies | react-native-gesture-handler | `3.3.0` | 3.3.0 / 3.3.0 | 3.3.0 | 3.5.0 | Held by expo@58.1.0: Expo recommends `~3.3.0` and the mobile manifest pins `3.3.0`. |
| apps/mobile | dependencies | react-native-reanimated | `4.7.1` | 4.7.1 / 4.7.1 | 4.7.1 | 4.8.0 | Held by expo@58.1.0: Expo recommends `4.7.1` and the mobile manifest pins `4.7.1`. |
| apps/mobile | dependencies | react-native-safe-area-context | `5.11.1` | 5.11.1 / 5.11.1 | 5.11.1 | 5.11.1 | Current |
| apps/mobile | dependencies | react-native-screens | `4.30.1` | 4.30.1 / 4.30.1 | 4.30.1 | 4.30.1 | Current |
| apps/mobile | dependencies | react-native-url-polyfill | `4.0.0` | 4.0.0 / 4.0.0 | 4.0.0 | 4.0.0 | Current |
| apps/mobile | dependencies | react-native-web | `~0.21.4` | 0.21.4 / 0.21.4 | 0.21.4 | 0.21.4 | Current |
| apps/mobile | dependencies | react-native-worklets | `0.13.0` | 0.13.0 / 0.13.0 | 0.13.0 | 0.14.0 | Held by expo@58.1.0: Expo recommends `0.13.0` and the mobile manifest pins `0.13.0`. |
| apps/mobile | dependencies | zustand | `^5.1.0` | 5.1.0 / 5.1.0 | 5.1.0 | 5.1.0 | Current |
| apps/mobile | devDependencies | @types/react | `~19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.3 | Held by bunfig.toml: The seven-day Bun policy applies to 19.3.3, published 2026-11-25T14:37:51.670Z. The manifest tracks the SDK 58 React 19.3 types with `~19.3.0`. |
| apps/mobile | devDependencies | @types/react-dom | `~19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.0 | Current |
| apps/mobile | devDependencies | @types/react-test-renderer | `19.3.1` | 19.3.1 / 19.3.1 | 19.3.1 | 19.3.1 | Current |
| apps/mobile | devDependencies | expo-mcp | `~0.2.4` | 0.2.4 / 0.2.4 | 0.2.4 | 0.2.4 | Current |
| apps/mobile | devDependencies | react-test-renderer | `19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.1 | Held by mobile React 19.3.0: The mobile manifest pins the renderer at `19.3.0` alongside React 19.3.0. The installed renderer declares React `^19.3.0`. |
| apps/mobile | devDependencies | typescript | `6.0.3` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | Held by typescript-eslint@8.73.0: Its TypeScript peer range is `>=4.8.4 <6.1.0`. `apps/mobile/package.json` requests `6.0.3`. |
| apps/server | dependencies | @divineruin/shared | `workspace:*` | workspace:packages/shared / workspace:packages/shared | — | — | Workspace source |
| apps/server | dependencies | @google/genai | `^2.32.0` | 2.32.0 / 2.32.0 | 2.32.0 | 3.6.1 | Held by apps/server/package.json: The requested range `^2.32.0` excludes 3.6.1. |
| apps/server | dependencies | @livekit/protocol | `^1.54.1` | 1.54.1 / 1.54.1 | 1.54.1 | 1.55.0 | Held by bunfig.toml: The seven-day Bun policy applies to 1.55.0, published 2026-11-25T09:46:41.918Z. |
| apps/server | dependencies | jose | `^6.2.18` | 6.2.18 / 6.2.18 | 6.2.18 | 6.2.18 | Current |
| apps/server | dependencies | livekit-server-sdk | `^2.20.1` | 2.20.1 / 2.20.1 | 2.20.1 | 2.20.1 | Current |
| apps/server | dependencies | sharp | `^0.35.5` | 0.35.5 / 0.35.5 | 0.35.5 | 0.35.5 | Current |
| apps/server | devDependencies | @types/bun | `1.4.4` | 1.4.4 / 1.4.4 | 1.4.4 | 1.4.5 | Held by apps/server/package.json: The requested range `1.4.4` excludes 1.4.5. |
| apps/web | dependencies | @divineruin/design-tokens | `workspace:*` | workspace:packages/design-tokens / workspace:packages/design-tokens | — | — | Workspace source |
| apps/web | dependencies | react | `19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.1 | Held by Expo React 19.3.0 cohort: `apps/web/package.json` pins `19.3.0`, matching the Expo SDK 58.1.0 React and React DOM versions. |
| apps/web | dependencies | react-dom | `19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.1 | Held by Expo React 19.3.0 cohort: `apps/web/package.json` pins `19.3.0`, matching the Expo SDK 58.1.0 React and React DOM versions. |
| apps/web | devDependencies | @types/bun | `1.4.4` | 1.4.4 / 1.4.4 | 1.4.4 | 1.4.5 | Held by apps/web/package.json: The requested range `1.4.4` excludes 1.4.5. |
| apps/web | devDependencies | @types/react | `~19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.3 | Held by bunfig.toml: The seven-day Bun policy applies to 19.3.3, published 2026-11-25T14:37:51.670Z. The manifest tracks the SDK 58 React 19.3 types with `~19.3.0`. |
| apps/web | devDependencies | @types/react-dom | `~19.3.0` | 19.3.0 / 19.3.0 | 19.3.0 | 19.3.0 | Current |
| packages/design-tokens | devDependencies | @types/bun | `1.4.4` | 1.4.4 / 1.4.4 | 1.4.4 | 1.4.5 | Held by packages/design-tokens/package.json: The requested range `1.4.4` excludes 1.4.5. |
| packages/design-tokens | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | Held by typescript-eslint@8.73.0: Its TypeScript peer range is `>=4.8.4 <6.1.0`. `packages/design-tokens/package.json` requests `>=5.9 <6.1`. |
| packages/shared | devDependencies | @types/bun | `1.4.4` | 1.4.4 / 1.4.4 | 1.4.4 | 1.4.5 | Held by packages/shared/package.json: The requested range `1.4.4` excludes 1.4.5. |
| packages/shared | peerDependencies | typescript | `>=5.9 <6.1` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | Held by typescript-eslint@8.73.0: Its TypeScript peer range is `>=4.8.4 <6.1.0`. `packages/shared/package.json` requests `>=5.9 <6.1`. |

## Independent browser toolchain

| Group | Dependency | Requested | Locked / installed | Candidate | Registry latest | Decision |
|---|---|---|---|---|---|---|
| devDependencies | @axe-core/playwright | `^4.14.0` | 4.14.0 / 4.14.0 | 4.14.0 | 4.14.1 | e2e/bunfig.toml. The seven-day Bun policy applies to 4.14.1, published 2026-11-24T15:59:38.852Z. |
| devDependencies | @eslint/js | `^10.0.1` | 10.0.1 / 10.0.1 | 10.0.1 | 10.0.1 | Current |
| devDependencies | @playwright/test | `^1.65.1` | 1.65.1 / 1.65.1 | 1.65.1 | 1.65.1 | Current |
| devDependencies | @types/bun | `1.4.4` | 1.4.4 / 1.4.4 | 1.4.4 | 1.4.5 | e2e/package.json. The requested range `1.4.4` excludes 1.4.5. |
| devDependencies | @types/pg | `^8.23.1` | 8.23.1 / 8.23.1 | 8.23.1 | 8.23.1 | Current |
| devDependencies | eslint | `^10.15.0` | 10.15.0 / 10.15.0 | 10.15.0 | 10.15.0 | Current |
| devDependencies | eslint-config-prettier | `^10.1.8` | 10.1.8 / 10.1.8 | 10.1.8 | 10.1.8 | Current |
| devDependencies | lighthouse | `^13.6.0` | 13.6.0 / 13.6.0 | 13.6.0 | 13.6.0 | Current |
| devDependencies | pg | `^8.23.1` | 8.23.1 / 8.23.1 | 8.23.1 | 8.23.1 | Current |
| devDependencies | playwright-lighthouse | `^4.0.0` | 4.0.0 / 4.0.0 | 4.0.0 | 4.0.0 | Current |
| devDependencies | typescript | `^6.0.3` | 6.0.3 / 6.0.3 | 6.0.3 | 7.0.2 | typescript-eslint@8.73.0. Its TypeScript peer range is `>=4.8.4 <6.1.0`. `e2e/package.json` requests `^6.0.3`. |
| devDependencies | typescript-eslint | `^8.73.0` | 8.73.0 / 8.73.0 | 8.73.0 | 8.74.0 | e2e/bunfig.toml. The seven-day Bun policy applies to 8.74.0, published 2026-11-23T17:06:58.945Z. |

## Mobile SDK 58 baseline

- Expo 58.1.0, React Native 0.88.1, Hermes V1 (SDK 58 default).
- Android 7+ (compile SDK 37, target SDK 36), iOS 16.4+, Xcode 26.4+.
- Config plugins: @livekit/react-native-expo-plugin, @config-plugins/react-native-webrtc, expo-router, expo-splash-screen, expo-disable-pods-indexing, expo-font, expo-status-bar, expo-web-browser, expo-audio, expo-secure-store, expo-asset, expo-image.
- Patch files: none.

| Git dependency | Requested | Locked commit |
|---|---|---|
| expo-disable-pods-indexing | `github:paulingalls/expo-disable-pods-indexing` | `fdd8959` |

Compatibility exceptions:
- none

### One-off Expo release-age exemption, 2026-11-26

The #792 handback records the two npm age inventories and expo-58.1.0-install-second-layer.log. One install exempted these coordinates. The frozen install passed with the seven-day policy. [Expo 58.1.0 upgrade](https://github.com/paulingalls/divineruin/pull/792)

| Package | Previous | Exempted version |
|---|---|---|
| expo | 58.0.26 | 58.1.0 |
| expo-crypto | 58.0.8 | 58.0.9 |
| expo-dev-client | 58.0.21 | 58.0.22 |
| expo-glass-effect | 58.0.5 | 58.0.6 |
| expo-image | 58.0.18 | 58.0.19 |
| expo-notifications | 58.1.9 | 58.1.10 |
| expo-router | 58.0.32 | 58.0.33 |
| expo-splash-screen | 58.0.14 | 58.0.15 |
| @expo/cli | 58.1.21 | 58.1.22 |
| @expo/config | 58.0.12 | 58.0.13 |
| expo-file-system | 58.0.14 | 58.0.15 |
| @expo/fingerprint | 0.21.10 | 0.22.0 |
| babel-preset-expo | 58.0.26 | 58.0.27 |
| expo-modules-core | 58.1.0 | 58.2.0 |
| @expo/metro-config | 58.0.23 | 58.0.24 |
| @expo/config-plugins | 58.0.13 | 58.0.14 |
| @expo/local-build-cache-provider | 58.0.12 | 58.0.13 |
| expo-dev-launcher | 58.0.21 | 58.1.0 |
| @expo/router-server | 58.0.23 | 58.0.24 |
| @expo/inline-modules | 0.2.10 | 0.2.11 |
| @expo/metro-file-map | 58.0.6 | 58.0.7 |
| @expo/prebuild-config | 58.0.20 | 58.0.21 |
| expo-modules-jsi | 58.0.23 | 58.0.24 |

## Root resolution overrides

| Override | Requested | Reason |
|---|---|---|
| dnssd-advertise | `1.1.6` | Reproducibility pin for native development Bonjour discovery. Expo CLI 58.1.22 requests `^1.1.6`. |

## Infrastructure holds

- `postgres:16-alpine` (PostgreSQL container): held outside this card. A database major migration requires separate application and data migration work.
- `valkey/valkey:8-alpine` (Valkey container): held outside this card. Container major upgrades are infrastructure work outside this library and browser-toolchain upgrade.

## Historical validation outcomes

The SDK 57 validation record was accepted at `795cec97832a7fe2d7567b36d0343e476e236b76` on 2026-09-19T14:14:59Z.

### Native builds

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

### Other recorded checks

| Lane | Recorded outcome | Evidence |
|---|---|---|
| bun install --frozen-lockfile | passed | Bun 1.4.4 accepted the root frozen lock without changes. |
| bun install --cwd e2e --frozen-lockfile | passed | Bun 1.4.4 accepted the independent e2e frozen lock without changes. |
| uv sync --project apps/agent --frozen | passed | uv 0.13.7 installed the agent lock under CPython 3.14.7. |
| uv sync --project scripts --frozen | passed | uv 0.13.7 installed the scripts lock under CPython 3.14.7. |
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
