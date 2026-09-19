# Maestro acceptance flows

Native-mobile acceptance lane for `apps/mobile`. Maestro covers what Playwright
can't reach: native LiveKit, native audio, haptics, permissions, platform
glyph rendering. Playwright still owns web/HTTP/general UI.

## Run

```sh
MAESTRO_APP_LAUNCH_URL=<dev-server-url> bun run test:e2e:mobile   # gated; skips cleanly when no device
IOS_SIMULATOR_UDID=<udid> REQUIRE_EMULATOR=1 bun run test:e2e:mobile
REQUIRE_BACKEND=1 bun run test:e2e:mobile    # additionally run flows that need apps/server reachable
```

`bun run test:e2e:mobile` invokes `scripts/maestro-acceptance.ts`, which:

1. With `REQUIRE_EMULATOR=1`, requires `IOS_SIMULATOR_UDID`, proves that exact
   simulator is booted and available, and passes it to Maestro with `--device`.
   Other booted simulators and Android devices cannot satisfy the strict gate.
2. Without the strict flag, checks broadly for a booted iOS simulator or an
   attached Android device and skips cleanly when neither exists.
3. Runs offline-safe flows by default and adds backend-required flows when
   `REQUIRE_BACKEND=1` is set.

Every flow clears app state and then opens `APP_LAUNCH_URL`, so a development
build needs a reachable Metro server: export `MAESTRO_APP_LAUNCH_URL` with that
server's `exp+divineruin://expo-development-client/?url=...` address. Without it
the flows fall back to the bare `divineruin://` scheme, which only reaches the
app's own bundle — the dev launcher will never render app content and the flow
fails rather than passing vacuously.

`verify:native-build` owns the strict lane. It generates native projects in a
temporary workspace, builds and installs on the requested simulator, starts its
own Metro process, and supplies `APP_LAUNCH_URL` so each flow opens that exact
development server after clearing app state. It preserves the explicit backend
URL from the root `.env`; SDK 57 native acceptance proved simulator loopback
against the story server. The runner never edits the root `.env`.

This gate proves native module loading, app launch, and the auth form. LiveKit
transport, microphone, and audio HUD behavior remain story 209 scope.

This mirrors the `REQUIRE_DOCKER` pattern in
`apps/agent/tests/acceptance/conftest.py` for the Python acceptance lane, so the
same "skip-by-default, hard-fail-under-env-flag" muscle memory applies across
both surfaces.

## Flows

- `launch.yaml` — offline-safe smoke: app launches without crashing. Runs by
  default.
- `auth-form.yaml` — backend-required: exercises the auth screen form
  mechanics (input → SEND CODE → phase transition to the code-input view). The
  email→code transition only happens on a 2xx from `/auth/request-code`, so
  this flow requires `apps/server` running and reachable from the device.
  Gated behind `REQUIRE_BACKEND=1`; skipped by default to keep the lane
  offline-safe.

## Assumptions worth tracking

- **Auth is the entry screen for unauthenticated users.** `auth-form.yaml`
  starts with "Listen to the dark" visible. If onboarding/splash lands in front
  of the auth screen, prefix the flow with the appropriate `tapOn`/wait steps.
- **testIDs on auth inputs.** `auth-form.yaml` uses `id: "email-input"` and
  `id: "code-input"` set on `<TextInput>` in `apps/mobile/src/app/auth.tsx`.
  If those testIDs disappear, the flow fails at the first `tapOn`.
- **Development-client tutorial.** Clearing app state may show Expo's first-run
  tutorial and leave its developer menu open. Both flows dismiss those vendor
  overlays before asserting app content.
- **Maestro CLI** must be installed locally (`brew install maestro`).
- **Local-only.** This lane does not run in `.github/workflows/ci.yml` — CI
  has no emulator. Hooking it up to EAS Workflows or a self-hosted runner is
  follow-up scope.
