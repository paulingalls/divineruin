# iOS TestFlight and internal device builds

The [Expo SDK 58 update](#expo-sdk-58-update-2026-11-26) applies to the
current build. The rest of this runbook records the 2026-11-16 profile review.

These profiles build a release app for a physical iPhone:
`production` uses store distribution and the EAS `production` environment;
`internal` uses ad hoc distribution and `preview`. Both require HTTPS and increment
the remote iOS build number. The bundle id stays `com.divineruin.app`, marketing
version `1.0.0`. No development client or simulator is selected.

Configuration resolution and native generation passed without credentials. No
CocoaPods installation, native compilation, signing, upload, store record creation
or tester invitation was performed. The first signed release must pass the device
checks below; WebRTC's published SDK matrix has a known SDK 57 gap.

## Tools and evidence

The locally installed versions used for review were Bun **1.4.4**, Expo **57.0.24**,
`@expo/cli` **57.0.26**, `@expo/config` **57.0.9**, `@expo/config-plugins`
**57.0.9**, `@expo/config-types` **57.0.2**, `eas-cli` **20.1.0**,
`@expo/eas-json` **20.1.0**, and its Joi schema **17.11.0**. Commands below pin
EAS to that reviewed version. The current documentation describes newer CLI syntax
(`env:set`); 20.1.0 uses `env:create --force`.

Story evidence is in XP DATA, `stories/story-testflight-config/evidence/`:
`versions.log`, `final-config.log`, per-case `final-*.json`, command/help JSON,
`prebuild.log`, generated `Podfile`, `AppDelegate.swift`, `Info.plist`,
`Podfile.properties.json`, and `autolinking.json`. Disposable programs were removed;
no regular test invokes these operator commands. The real EAS Joi schema and
profile loader validated both profiles. Real Expo public-config subprocesses
resolved distinct HTTPS URLs, then fresh production Bun processes passed those
configs to `getApiBase` with the URL environment variable removed: exact agreement.
Missing, HTTP and malformed HTTPS inputs failed both release profiles with
`EXPO_PUBLIC_API_URL` diagnostics; unprofiled local missing/HTTP inputs passed.
Dotenv was disabled in Bun and Expo throughout those probes.

References: [EAS configuration](https://docs.expo.dev/eas/json/),
[remote app versions](https://docs.expo.dev/build-reference/app-versions/),
[environment management](https://docs.expo.dev/eas/environment-variables/manage/),
[monorepo commands](https://docs.expo.dev/build-reference/build-with-monorepos/),
[iOS submission](https://docs.expo.dev/submit/ios/), and
[internal distribution](https://docs.expo.dev/build/internal-distribution/).

## Before starting

The human supplies:

- Paid Apple Developer membership and access to the signing team; an iPhone for
  ad hoc testing, and an App Store Connect role allowed to create/upload builds.
- EAS login authorized for `pi-innovations-llc` and existing project
  `132df1ee-041d-4289-a374-f56152c971e0`. Preserve that association.
- A deployed, device-reachable HTTPS API URL, including its path if applicable.
  Public API URLs are embedded in the binary; never put a secret in this value.
- An App Store Connect iOS app record for `com.divineruin.app`. Create it manually
  if absent, choosing the display name and unique SKU; record its numeric Apple
  app id. This is a human credentialed step, not a CLI command performed here.

## Prepare the checkout

Run in the repository root. **Reviewed/executed:** frozen install exited 0;
Acceptance exited 0 (3 tests, mobile typecheck); affected image consumer exited 0
(3 tests). These exact commands require no Apple/EAS credentials:

```sh
bun install --frozen-lockfile
bun test ./apps/mobile/src/__tests__/base-url.test.ts && bun run typecheck:mobile
bun test ./apps/mobile/src/__tests__/use-game-events.overlays-creation.test.ts
cd apps/mobile
bunx eas-cli@20.1.0 --version
```

The directory change and version command were executed; the latter reported
`eas-cli/20.1.0`. All remaining Expo/EAS commands run from `apps/mobile`.
Do not initialize a new EAS project or regenerate the build configuration.

## Production / TestFlight

1. **Human credentials required — not executed:** EAS account/project access.
   Sign in with the account authorized for the existing owner:

   ```sh
   bunx eas-cli@20.1.0 login
   ```

2. Export the real deployed URL. **Reviewed/executed** with the exact sample below
   (exit 0); replace the sample with your server before continuing:

   ```sh
   export EXPO_PUBLIC_API_URL=https://production.example.com
   ```

   **Human credentials required — not executed:** EAS project environment write
   and read permissions. Set the project-scoped public URL, then inspect it:

   ```sh
   APP_VARIANT=production bunx eas-cli@20.1.0 env:create --environment production --scope project --name EXPO_PUBLIC_API_URL --value "$EXPO_PUBLIC_API_URL" --type string --visibility plaintext --force
   APP_VARIANT=production bunx eas-cli@20.1.0 env:list --environment production --scope project --format long
   ```

   Compare the listed value with the shell export before building. **The EAS-stored
   value is what ships.** CLI 20.1.0 first resolves config with shell plus profile
   variables to discover the project id, then resolves again with remote variables
   overriding the shell; the worker also uses the remote value. The shell export
   lets the first evaluation succeed. A mismatch silently ships the remote URL.
   `APP_VARIANT` on these environment commands allows that initial config check;
   build commands receive it from their profile automatically.

3. Resolve public configuration locally with the chosen shell URL.
   **Reviewed/executed:** exit 0, `extra.apiUrl` equals the sample URL, bundle id
   and all ten plugins preserved:

   ```sh
   EXPO_NO_DOTENV=1 APP_VARIANT=production bun --no-env-file expo config --type public --json
   ```

   **Reviewed/executed negative checks:** each exited 1 naming
   `EXPO_PUBLIC_API_URL`, before any build command. These inline assignments do not
   change the exported URL:

   ```sh
   EXPO_NO_DOTENV=1 APP_VARIANT=production EXPO_PUBLIC_API_URL= bun --no-env-file expo config --type public --json
   EXPO_NO_DOTENV=1 APP_VARIANT=production EXPO_PUBLIC_API_URL=http://api.example.com bun --no-env-file expo config --type public --json
   ```

4. **Human credentials required — not executed:** EAS remote-version access.
   Initialize/check the iOS counter. If this app already has uploaded builds,
   consult App Store Connect history and set the current counter accordingly so
   the next increment produces an unused number:

   ```sh
   bunx eas-cli@20.1.0 build:version:set --platform ios --profile production
   ```

   `cli.appVersionSource` is explicitly `remote`; no local `ios.buildNumber` is
   maintained. Installed EAS initializes an absent number from Expo's default
   `"1"` on first use. Both profiles have `autoIncrement: true`.

5. **Human credentials required — not executed:** EAS build access and Apple
   signing-team credentials. Complete signing prompts, wait for the artifact, and
   record the resulting EAS build id:

   ```sh
   bunx eas-cli@20.1.0 build --platform ios --profile production
   ```

6. **Human credentials required — not executed:** EAS artifact access and Apple
   submission credentials (interactive prompts may request an App Store Connect
   API key or Apple account). Replace the placeholder with that exact build id:

   ```sh
   bunx eas-cli@20.1.0 submit --platform ios --id <that-build-id>
   ```

   Select the existing App Store Connect app. Do not select an unrelated latest
   artifact. No numeric app id is hardcoded in the repository.

7. **Human App Store Connect steps — not executed:** wait for processing, answer
   export-compliance questions for the complete app, configure TestFlight testing,
   provide test information/review as required, and invite testers. Uploading alone
   does not invite testers or publish an App Store release. Run the device checks
   below on the installed release before expanding the group.

## Internal device build (separate path)

After checkout preparation and EAS login, use a chosen reachable HTTPS server.
**Reviewed/executed** sample export and public-config command: exit 0, exact
`extra.apiUrl` agreement with runtime for `https://internal.example.com`:

```sh
export EXPO_PUBLIC_API_URL=https://internal.example.com
```

**Human credentials required — not executed:** EAS project environment write/read.
Set and compare `preview` to the shell value using the same precedence rules:

```sh
APP_VARIANT=internal bunx eas-cli@20.1.0 env:create --environment preview --scope project --name EXPO_PUBLIC_API_URL --value "$EXPO_PUBLIC_API_URL" --type string --visibility plaintext --force
APP_VARIANT=internal bunx eas-cli@20.1.0 env:list --environment preview --scope project --format long
```

**Reviewed/executed**, credential-free config resolution:

```sh
EXPO_NO_DOTENV=1 APP_VARIANT=internal bun --no-env-file expo config --type public --json
```

**Human credentials required — not executed:** EAS device registration/build access
and Apple team signing access. Register the device before building, follow the
registration URL on that iPhone, then build:

```sh
bunx eas-cli@20.1.0 device:create
bunx eas-cli@20.1.0 build --platform ios --profile internal
```

Install from the resulting internal build link on a registered device. There is
no TestFlight submission for this profile. Both variants share the bundle id, so
installing one replaces the other on the device.

## Native plugin release review

All ten configured plugins were checked against official references on 2026-11-16.
No dependency or plugin option was changed. Bare plugin entries use their installed
defaults. Generation proves configuration application, not native compatibility.
EAS image selection remains the default SDK-matched selection; see
[build infrastructure](https://docs.expo.dev/build-reference/infrastructure/).

| Plugin / installed version | Configuration and observed evidence | Human check on a signed release / reference |
| --- | --- | --- |
| `@livekit/react-native-expo-plugin` 1.0.2 | No options; LiveKit 2.12.0 / WebRTC 144.1.2 preserved. Apple autolinking resolves `LiveKitExpoAppDelegate`; its installed subscriber calls `LivekitReactNative.setup()`. Root layout calls the JS `registerGlobals` wrapper. | Microphone, room connection and session audio. Expo Go cannot certify this native SDK. [LiveKit Expo](https://docs.livekit.io/transport/sdk-platforms/expo/) |
| `@config-plugins/react-native-webrtc` 15.0.2 | No options; `ios.bitcode: false` retained. Generated microphone text is the app's existing DM-access description; camera text is the plugin default. | Native WebRTC audio/session on device. Published matrix stops at SDK 56/plugin 15/WebRTC 124.0.7; SDK 57 with installed LiveKit WebRTC 144.1.2 is an evidence gap and known first-build risk, not certified by prebuild. [Upstream matrix/options](https://raw.githubusercontent.com/expo/config-plugins/main/packages/react-native-webrtc/README.md), [LiveKit pair](https://docs.livekit.io/transport/sdk-platforms/expo/) |
| `expo-router` 57.0.22 | No options; `expo-router/entry`, scheme `divineruin`, typed routes and router extras retained; generated URL schemes and route activity present. | Cold launch and `divineruin` links. [Router installation](https://docs.expo.dev/router/installation/) |
| `expo-splash-screen` 57.0.9 | Image `./assets/images/splash.png`, background `#0A0A0B`, resize `cover`, `enableFullScreenImage_legacy: true`; Android image/background same, width 288. Generated launch storyboard reference present. | Actual splash appearance in release. Development/Expo Go splash differs. [SDK 57 SplashScreen](https://docs.expo.dev/versions/v57.0.0/sdk/splash-screen/) |
| `expo-disable-pods-indexing` 1.0.0, lock revision `fdd8959` | No options; dangerous mod writes `COMPILER_INDEX_STORE_ENABLE = NO` for every Pods target/build configuration in generated Podfile. | Confirm Pods installation and release compilation; custom plugin has no Expo compatibility certification. [Plugin upstream](https://github.com/paulingalls/expo-disable-pods-indexing), [CNG](https://docs.expo.dev/workflow/continuous-native-generation/) |
| `expo-build-properties` 57.0.21 | Only `ios.enableSceneSupport: true`; Expo 57.0.24 exceeds documented 57.0.23 floor. Generated scene manifest uses `EXExpoAppSceneDelegate`; AppDelegate exposes its factory/provider. | Native cold launch under scene lifecycle. [SDK 57 BuildProperties](https://docs.expo.dev/versions/v57.0.0/sdk/build-properties/) |
| `expo-audio` 57.0.5 | No options; default background playback true, background recording false, Android recording true. Existing app microphone text retained, generated `UIBackgroundModes` includes `audio`. | Playback, capture, interruptions, headphones/Bluetooth and background audio. [SDK 57 Audio](https://docs.expo.dev/versions/v57.0.0/sdk/audio/) |
| `expo-secure-store` 57.0.4 | No options; Android backup default true, Face ID description default generated. App storage calls do not request biometric authentication. | Sign-in storage and relaunch using Keychain. Answer encryption/export questions for the complete app; this change adds no blanket encryption declaration. [SDK 57 SecureStore](https://docs.expo.dev/versions/v57.0.0/sdk/securestore.md) |
| `expo-asset` 57.0.18 | No options; extra native asset list defaults to empty, existing Metro-imported assets retained; Apple module resolves. | Bundled sounds/images work without Metro. [SDK 57 Asset](https://docs.expo.dev/versions/v57.0.0/sdk/asset/) |
| `expo-image` 57.0.5 | No options; default `disableLibdav1d: false` retained; Apple module resolves. | Native image rendering/decoding. [SDK 57 Image](https://docs.expo.dev/versions/v57.0.0/sdk/image/) |

## Credential-free generation evidence

From `apps/mobile`, **reviewed/executed**, each exited 0 with the sample production
URL. These are optional inspection commands, not build or upload steps:

```sh
EXPO_NO_DOTENV=1 APP_VARIANT=production EXPO_PUBLIC_API_URL=https://production.example.com bun --no-env-file expo config --type prebuild --json
EXPO_NO_DOTENV=1 APP_VARIANT=production EXPO_PUBLIC_API_URL=https://production.example.com bun --no-env-file expo config --type introspect --json
EXPO_NO_DOTENV=1 APP_VARIANT=production EXPO_PUBLIC_API_URL=https://production.example.com bun --no-env-file expo prebuild --clean --platform ios --no-install
bun --no-env-file expo-modules-autolinking resolve --platform apple --json
```

Introspection showed permissions, background audio and scene support. Prebuild
also ran the indexing dangerous mod, which introspection cannot execute. The
reviewer retained the generated files externally, removed generated `ios/`, and
confirmed a clean Git status. Keep native directories absent for EAS to regenerate
them from configuration; do not commit inspection output. CocoaPods and a signed
release remain untested here.


## Expo SDK 58 update (2026-11-26)

The app locks Expo 58.0.26, React Native 0.88.1 and React 19.3.0. Expo's
SDK-selected native dependencies include Gesture Handler 3.3.0 and AsyncStorage
2.2.0. The LiveKit packages move together to React Native SDK 3.2.0, WebRTC
150.2.0 and Expo plugin 1.2.0. The minimum Xcode version is 26.4.
[Expo SDK 58 platform support](https://docs.expo.dev/versions/v58.0.0/#support-for-android-and-ios-versions)
and the [LiveKit release notes](https://github.com/livekit/client-sdk-react-native/releases)
describe these requirements.

Clean Expo prebuild generates the iOS scene lifecycle from SDK 58 defaults.
The simulator commands are `bun run --cwd apps/mobile verify:native-build` and
`bun run --cwd apps/mobile verify:native-transport`. The signed iPhone checks
above still apply before TestFlight certification.
