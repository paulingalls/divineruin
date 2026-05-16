# Dependency Version Audit

Sprint-001 / Milestone 1 companion audit. Pinned versions vs upstream stable.

- Audit date: 2026-05-15. Snapshot — packages added to manifests after this date (e.g., `testcontainers`, `docker` landed 2026-05-16) are out of scope and not listed below.
- Inputs read: `apps/agent/pyproject.toml` (+ `uv.lock`), `apps/server/package.json`, `apps/mobile/package.json`, root `package.json`, root `bun.lock`.
- "Current" = version resolved by the lockfile when available; otherwise the manifest pin.
- "Latest stable" = `info.version` from `pypi.org/pypi/<pkg>/json` or `dist-tags.latest` from `registry.npmjs.org/<pkg>/latest`.
- Recommendation legend:
  - **now** — security fix, known critical bug, or already-broken pin; pull this sprint.
  - **next sprint** — minor/patch with no breaking changes; routine refresh.
  - **hold** — major version bump or coordinated migration (Expo SDK, RN core); needs dedicated work.

## Recommended Next Sprint (top-10)

These surface first because they either unblock other upgrades, fix a latent issue, or carry the largest version drift among low-risk items.

| Package | Current | Latest Stable | Recommendation | Risk |
| --- | --- | --- | --- | --- |
| `@types/sharp` (server) | ^0.32.0 | deprecated | **now** | `sharp` ships its own types since 0.32; `@types/sharp` is a stub. Remove the dep — keeping it is misleading and can mask type drift. |
| `anthropic` (agent) | 0.86.0 | 0.102.0 | **next sprint** | 16 minor versions behind. SDK has added Claude 4.x model IDs, refined message-shape types, and tweaked tool-use streaming. Bump alongside `livekit-plugins-anthropic` so the resolver picks one anthropic. |
| `livekit-agents` + `livekit-plugins-*` (agent) | 1.5.1 | 1.5.9 | **next sprint** | Patch line of the 1.5 family. Bug fixes only; bump all six packages together (`agents`, `plugins-anthropic`, `plugins-deepgram`, `plugins-inworld`, `plugins-silero`, `plugins-turn-detector`) to keep the suite version-aligned. |
| `pytest` (agent) | 9.0.2 | 9.0.3 | **next sprint** | Patch. Trivial. |
| `ruff` (agent) | 0.15.7 | 0.15.13 | **next sprint** | Six patch releases of lint/format fixes. May surface a few new lints — run `lint:python:fix` after bump. |
| `pyright` (agent) | 1.1.408 | 1.1.409 | **next sprint** | Patch. Trivial. |
| `pillow` (agent) | 12.1.1 | 12.2.0 | **next sprint** | Minor, used only for asset utilities. No API breakage expected. |
| `livekit-client` (mobile) | ^2.18.0 | 2.19.0 | **next sprint** | Minor. Pair with `@livekit/react-native` 2.10.x bump below to keep client+native aligned. |
| `@livekit/react-native` (mobile) | ^2.9.6 | 2.10.3 | **next sprint** | Minor. Verify against `@livekit/react-native-webrtc` 144 (already current). |
| `@livekit/protocol` (server) | ^1.44.1 | 1.45.8 | **next sprint** | Minor — protocol additions, no breaking removals; safe with current `livekit-server-sdk` ^2.15. |

## Python (apps/agent/pyproject.toml)

Resolved versions taken from `apps/agent/uv.lock`.

| Package | Current | Latest Stable | Recommendation | Risk |
| --- | --- | --- | --- | --- |
| `livekit-agents[silero,turn-detector]` | 1.5.1 | 1.5.9 | next sprint | Patch line within `~=1.5` pin — `uv sync` after registry refresh will pick it up. Bug fixes; no API churn documented in 1.5.x. |
| `livekit-plugins-noise-cancellation` | 0.2.5 | 0.2.5 | — | Current. |
| `livekit-plugins-anthropic` | 1.5.1 | 1.5.9 | next sprint | Patch. Bump in lockstep with `livekit-agents`; this plugin transitively pulls `anthropic` SDK so coordinate with row below. |
| `livekit-plugins-deepgram` | 1.5.1 | 1.5.9 | next sprint | Patch. STT plugin — keep aligned with `livekit-agents`. |
| `livekit-plugins-inworld` | 1.5.1 | 1.5.9 | next sprint | Patch. TTS plugin — keep aligned with `livekit-agents`. |
| `livekit-plugins-silero` (extra) | 1.5.1 | 1.5.9 | next sprint | Patch. VAD. Auto-bumps with `livekit-agents[silero,...]`. |
| `livekit-plugins-turn-detector` (extra) | 1.5.1 | 1.5.9 | next sprint | Patch. Auto-bumps with extras. |
| `anthropic` | 0.86.0 | 0.102.0 | next sprint | 16 minor versions of additive change (new model IDs, refined types, extended-thinking helpers). Run `bun run test:python` after — most code paths go through LiveKit's wrapper, not the SDK directly. |
| `asyncpg` | 0.31.0 | 0.31.0 | — | Current. |
| `redis` (redis.asyncio) | 7.4.0 | 7.4.0 | — | Current. Note: 7.4 is the floor; check before any 8.x adoption — redis-py 8 dropped Python 3.9 and shifted some pubsub semantics. |
| `httpx` | 0.28.1 | 0.28.1 | — | Current. |
| `pillow` (dev) | 12.1.1 | 12.2.0 | next sprint | Minor; dev-only (asset utils). Safe bump. |
| `pyright` (dev) | 1.1.408 | 1.1.409 | next sprint | Patch. Trivial. |
| `pytest` (dev) | 9.0.2 | 9.0.3 | next sprint | Patch. Trivial. |
| `pytest-asyncio` (dev) | 1.3.0 | 1.3.0 | — | Current. (`>=0.24` pin is loose; consider tightening to `>=1.3` to match resolution.) |
| `ruff` (dev) | 0.15.7 | 0.15.13 | next sprint | Six patch releases. Re-run `ruff format` after bump to absorb new auto-fixes. |

Python runtime pin (`>=3.11`) is fine; CPython 3.13 is GA and all listed deps support it.

## Bun / TS (apps/server/package.json + root package.json)

| Package | Current | Latest Stable | Recommendation | Risk |
| --- | --- | --- | --- | --- |
| `@google/genai` | ^1.44.0 | 2.3.0 | hold | Major version bump (1.x → 2.x). Gemini SDK reshaped the `models.generateContent` surface and tool-calling types between 1.44 and 2.x. Plan a dedicated migration when touching the Gemini integration; until then `^1.44.0` is fine. |
| `@livekit/protocol` | ^1.44.1 | 1.45.8 | next sprint | Minor. Safe under existing caret; just refresh the lock. |
| `@types/sharp` | ^0.32.0 | (deprecated) | **now** | `sharp` 0.33+ bundles its own TS types. Keeping `@types/sharp` 0.32 is a no-op at best and a type-conflict footgun at worst. Delete the entry. |
| `jose` | ^6.2.0 | 6.2.3 | next sprint | Patch within caret. Safe. |
| `livekit-server-sdk` | ^2.15.0 | 2.15.3 | next sprint | Patch within caret. Safe. |
| `sharp` | ^0.34.5 | 0.34.5 | — | Current. (libvips bumps land in 0.35 — defer until next major.) |
| `@types/bun` (server devDep) | ^1.2.0 | 1.3.14 | next sprint | Server still asks for `^1.2.0`; root asks for `^1.3.11`. Bump server entry to `^1.3` so both workspaces resolve the same Bun typings. |
| `@types/bun` (root devDep) | ^1.3.11 | 1.3.14 | next sprint | Patch within caret. Safe. |
| `@eslint/js` (root) | ^10.0.1 | ~10.x | next sprint | Track ESLint core; bump together with `eslint`. |
| `eslint` (root) | ^10.1.0 | 10.4.0 | next sprint | Minor within caret. Run `bun run lint` after — new rules can flag existing code. |
| `eslint-config-prettier` (root) | ^10.1.8 | 10.x | next sprint | Tracks ESLint. Safe with bump above. |
| `eslint-plugin-react-hooks` (root) | ^7.0.1 | 7.x | next sprint | Patch under caret. Safe. |
| `eslint-plugin-react-refresh` (root) | ^0.5.2 | 0.5.x | next sprint | Patch under caret. Safe. |
| `prettier` (root) | ^3.8.1 | 3.8.3 | next sprint | Patch within caret. May reformat a few files. |
| `typescript-eslint` (root) | ^8.57.2 | 8.59.3 | next sprint | Minor within caret. Pair with `eslint` bump. |
| `typescript` (peer; mobile devDep) | `^5` / ~5.9.2 | 6.0.3 | hold | TS 6.0 is a major. Dedicated migration: review `verbatimModuleSyntax`, deprecated flag removals, and `--isolatedDeclarations` opt-in before adopting. |
| `pnpm` (packageManager field) | 10.28.0 | n/a | review | `packageManager` declares pnpm 10.28, but the repo actually uses Bun (`bun.lock` is the lockfile). Either remove the `packageManager` field or switch it to `bun@<version>` so tools like Corepack don't shadow Bun. Not blocking, but misleading. |

Bun version compatibility: all server deps work with current Bun stable (1.2.x line). No Bun-specific pins force a downgrade.

## Expo / React Native (apps/mobile/package.json)

Mobile workspace tracks **Expo SDK 55**. Most `~55.0.x` pins are Expo-managed — bumping inside the 55.0.x line is routine; jumping to SDK 56 requires the full Expo migration. SDK 56 was not yet on `npm latest` for `expo` as of the audit date (`expo@latest` = 55.0.24).

| Package | Current | Latest Stable | Recommendation | Risk |
| --- | --- | --- | --- | --- |
| `expo` | ~55.0.8 | 55.0.24 | next sprint | Patch line within SDK 55. Run `npx expo install --check` after to align sibling expo-* packages. |
| `expo-router` | ~55.0.7 | 55.0.14 | next sprint | Patch within SDK 55. |
| `expo-asset` | ~55.0.10 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-audio` | ~55.0.9 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. Audio-critical — smoke-test playback before merging. |
| `expo-constants` | ~55.0.9 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-dev-client` | ~55.0.18 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-device` | ~55.0.10 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-font` | ~55.0.4 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-glass-effect` | ~55.0.8 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-haptics` | ~55.0.9 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-image` | ~55.0.6 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-linear-gradient` | ~55.0.9 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-linking` | ~55.0.8 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-notifications` | ^55.0.13 | (SDK 55 latest) | next sprint | Caret already accepts newer SDK 55 patches. |
| `expo-secure-store` | ~55.0.9 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-splash-screen` | ~55.0.12 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-status-bar` | ~55.0.4 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-symbols` | ~55.0.5 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-system-ui` | ~55.0.10 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-web-browser` | ~55.0.10 | (SDK 55 latest) | next sprint | Bump with `expo install --check`. |
| `expo-disable-pods-indexing` (github fork) | github:paulingalls/... | n/a | review | Fork. Track upstream for divergence; no registry version to compare against. |
| `@expo-google-fonts/cormorant-garamond` | ^0.4.1 | 0.4.x | next sprint | Caret already accepts patches. |
| `@expo-google-fonts/crimson-pro` | ^0.4.2 | 0.4.x | next sprint | Caret already accepts patches. |
| `@expo-google-fonts/ibm-plex-mono` | ^0.4.1 | 0.4.x | next sprint | Caret already accepts patches. |
| `@expo/vector-icons` | ^15.0.2 | 15.1.1 | next sprint | Minor within caret. |
| `react` | 19.2.0 (exact) | 19.2.6 | next sprint | Patch. Pin is exact (no caret) — bump explicitly. |
| `react-dom` | 19.2.0 (exact) | 19.2.6 | next sprint | Patch. Match `react`. |
| `react-native` | 0.83.2 (exact) | 0.85.3 | hold | Two minor versions ahead of current (RN 0.84, 0.85). RN minors are Expo-coordinated — staying on 0.83 until SDK 56 migration is correct. Do **not** bump independently. |
| `react-native-gesture-handler` | ~2.30.0 | 2.31.2 | hold | Minor. Expo-aligned package — let `expo install --check` decide. |
| `react-native-reanimated` | 4.2.1 (exact) | 4.3.1 | hold | Minor, exact pin. Reanimated is RN/Expo-aligned and paired with `react-native-worklets`; defer to Expo's compatibility matrix. |
| `react-native-safe-area-context` | ~5.6.2 | 5.7.0 | hold | Expo-aligned; bump via `expo install --check`. |
| `react-native-screens` | ~4.23.0 | 4.25.0 | hold | Expo-aligned; bump via `expo install --check`. |
| `react-native-worklets` | 0.7.2 (exact) | 0.8.3 | hold | Paired with `react-native-reanimated`; bump as a pair when SDK allows. |
| `react-native-web` | ~0.21.0 | 0.21.2 | next sprint | Patch within Expo SDK 55 compatibility. |
| `react-native-url-polyfill` | ^3.0.0 | 3.x | — | Current under caret. |
| `@react-native-async-storage/async-storage` | 2.2.0 (exact) | 3.0.2 | hold | Major bump (2 → 3). Native module — requires Expo SDK alignment and a rebuild of dev clients. Schedule with SDK 56 upgrade. |
| `@react-native-community/slider` | ^5.1.2 | 5.2.0 | next sprint | Minor within caret. |
| `@react-navigation/native` | ^7.1.33 | 7.2.4 | next sprint | Minor within caret. Bump bottom-tabs + elements together. |
| `@react-navigation/bottom-tabs` | ^7.15.5 | 7.16.1 | next sprint | Patch within caret. |
| `@react-navigation/elements` | ^2.9.12 | 2.x | next sprint | Patch within caret. |
| `@livekit/components-core` | ^0.12.13 | 0.12.13 | — | Current. |
| `@livekit/components-react` | ^2.9.20 | 2.9.21 | next sprint | Patch within caret. |
| `@livekit/react-native` | ^2.9.6 | 2.10.3 | next sprint | Minor within caret. Pair with `livekit-client` bump. |
| `@livekit/react-native-expo-plugin` | ^1.0.2 | 1.0.2 | — | Current. |
| `@livekit/react-native-webrtc` | ^144.0.0 | 144.0.0 | — | Current. (Major releases track upstream WebRTC milestones — next bump will require a coordinated config-plugins bump.) |
| `livekit-client` | ^2.18.0 | 2.19.0 | next sprint | Minor within caret. |
| `@config-plugins/react-native-webrtc` | ^13.0.0 | 14.0.0 | hold | Major bump. Native-module config plugin; bump only alongside a corresponding `@livekit/react-native-webrtc` major. |
| `zustand` | ^5.0.12 | 5.0.13 | next sprint | Patch within caret. |
| `@types/react` (devDep) | ~19.2.2 | 19.2.14 | next sprint | Patch within Expo SDK 55 typings. |
| `typescript` (devDep) | ~5.9.2 | 6.0.3 | hold | See server section — TS 6 is a coordinated migration. |

### Mobile-specific notes

- **SDK 56 migration is the next big lift.** Most "hold" items above (RN 0.85, async-storage 3, reanimated 4.3, gesture-handler 2.31, screens 4.25, safe-area-context 5.7) will move as a single batch when SDK 56 lands. Plan a dedicated story.
- **Native-module rebuild required for any "hold" item.** Bumping reanimated, async-storage, WebRTC, or screens forces an `expo prebuild --clean` and dev-client rebuild — do not bundle with patch refreshes.
- **Exact pins on `react`, `react-dom`, `react-native`, `react-native-reanimated`, `react-native-worklets`, `@react-native-async-storage/async-storage`** mean `bun install` will not silently upgrade them — version moves require an explicit manifest edit, which is correct for SDK-aligned packages.

## Methodology Notes

- PyPI lookups: `info.version` from `https://pypi.org/pypi/<pkg>/json`. Cross-checked entries where the initial summary appeared inconsistent with the rest of the LiveKit 1.5 family (deepgram/silero plugins re-fetched and confirmed at 1.5.9).
- npm lookups: `version` field from `https://registry.npmjs.org/<pkg>/latest` (the `latest` dist-tag). For Expo-managed packages this reflects the SDK 55 patch line, not pre-release SDK 56 builds.
- Lockfile resolution: agent uses `apps/agent/uv.lock`; TS/JS uses root `bun.lock`. Mobile and server inherit from the root bun.lock (no per-app lockfile).
- No CVE database scan was performed — recommendations are based on version drift only. A separate `npm audit` / `pip-audit` pass is advisable before any "now" bump lands.
