# Maestro acceptance flows

The scheduled Proof `super` set runs all nine iOS journeys. To run just that
task from the repository root:

```sh
bunx proof run --fresh --tasks native-maestro
```

Proof provisions checkout-owned Postgres, Valkey and LiveKit. The task builds
and installs one dev client on the clone's `divineruin-native-<clone id>`
simulator. All journeys use the same Metro and API processes. The task stops
them and removes its temporary sign-in enrollment on exit. Each journey's
result appears in the super log, and JUnit reports and simulator artifacts are
retained under `flake-artifacts/native-maestro-*`.

The Mac needs Xcode with an available general iOS runtime, Docker, Maestro on
`PATH` or at `~/.maestro/bin/maestro`, and FFmpeg with AudioToolbox output.
Launchd needs a logged-in GUI session. For the Choir journey, grant microphone
access to the Simulator and keep the built-in speaker audible to the host
microphone. An unavailable prerequisite, an omitted journey, or a failing flow
fails the task.

## Journeys

| Flow | Behavior |
| --- | --- |
| `launch.yaml` | Development client loads the app and shows the auth entry. |
| `auth-form.yaml` | The mock-email backend accepts the enrolled address and the form advances to code entry. |
| `native-transport.yaml` | Native LiveKit delivers microphone frames, received audio and the session-init HUD. |
| `choir-encounter.yaml` | Acoustic speech reaches LiveKit and dispatches commands with encounter checkpoints and receipts. |
| `patron-abilities.yaml` | The patron HUD renders server state across ability use, rests and disposition changes. |
| `iron-resolve-hud.yaml` | Combat updates add and clear Iron Resolve in the HUD. |
| `http-inventory-refresh.yaml` | Authenticated inventory shows clean and tainted material and pauses polling in the background. |
| `http-inventory-resume.yaml` | The same app and fixture refresh on return and reject a stale held response. |
| `live-material-inventory.yaml` | The inventory panel displays material state captured from a live agent event. |

## Manual smoke checks

```sh
bun run test:e2e:mobile
REQUIRE_EMULATOR=1 REQUIRE_BACKEND=1 bun run test:e2e:mobile
bun run --cwd apps/mobile verify:native-build
```

The manual gate defaults to `launch.yaml` on the already-booted owned iOS
simulator and ready Android device, if present. `REQUIRE_EMULATOR=1` requires
the owned iOS simulator, and `REQUIRE_BACKEND=1` also exercises auth and patron
abilities on iOS. The manual gate can start an API and Metro from the caller's
`DATABASE_URL`. If you supply `MAESTRO_APP_LAUNCH_URL` or use Android, provide
a running backend and enroll the address with
`bun run allow acceptance@divineruin.test`. Use a development-client launch
URL such as `exp+divineruin://expo-development-client/?url=...`.

`verify:native-build` builds and installs the dev client, starts Metro, and
runs the manual strict gate using `EXPO_PUBLIC_API_URL` from the caller or the
root `.env`.
