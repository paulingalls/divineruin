# Maestro acceptance flows

Native-mobile acceptance lane for `apps/mobile`. Maestro covers what Playwright
can't reach: native LiveKit, native audio, haptics, permissions, platform
glyph rendering. Playwright still owns web/HTTP/general UI.

## Run

```sh
bun run test:e2e:mobile                      # gated; skips cleanly when no device; runs offline-safe flows only
REQUIRE_EMULATOR=1 bun run test:e2e:mobile   # hard-fail when no device
REQUIRE_BACKEND=1  bun run test:e2e:mobile   # additionally run flows that need apps/server reachable
```

`bun run test:e2e:mobile` invokes `scripts/maestro-acceptance.ts`, which:

1. Checks for a booted iOS simulator via `xcrun simctl list devices`.
2. Checks for an attached Android device via `adb devices`.
3. Neither present + `REQUIRE_EMULATOR` unset → exit 0 with skip message.
4. Neither present + `REQUIRE_EMULATOR=1` → exit 1 with actionable error.
5. Either present → runs the offline-safe flows by default; adds
   backend-required flows when `REQUIRE_BACKEND=1` is set.

This mirrors the `REQUIRE_DOCKER` pattern in
`apps/agent/tests/acceptance/conftest.py:77-83` for the Python acceptance lane,
so the same "skip-by-default, hard-fail-under-env-flag" muscle memory applies
across both surfaces.

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
- **Maestro 2.5.x** is the assumed local version (`brew install maestro`).
- **Local-only.** This lane does not run in `.github/workflows/ci.yml` — CI
  has no emulator. Hooking it up to EAS Workflows or a self-hosted runner is
  follow-up scope.
