import { expect, test } from "bun:test";

import {
  OWNED_SIMULATOR_UDID,
  developmentClientUrl,
  transportRouteUrl,
  validateScenarioResult,
  runNativeTransport,
} from "../../scripts/verify-native-transport";

const good = {
  run_id: "run-one",
  room_name: "room-one",
  mobile_identity: "mobile-run-one",
  publisher_identity: "python-run-one",
  peer_ready: true,
  subscribed_publisher_identity: "python-run-one",
  audio_track_sid: "TR_audio",
  packets_received: 4,
  bytes_received: 640,
  microphone_frames: 3,
  event_received: true,
  event_sender_identity: "python-run-one",
  hud_character: "Upgrade Test Hero",
  hud_location: "Upgrade Test Room",
};

test("runner binds Metro and route URLs to one run without credentials", () => {
  expect(OWNED_SIMULATOR_UDID).toBe("DC457949-200B-479A-95FD-611E33210F12");
  expect(developmentClientUrl(18082)).toBe(
    "exp+divineruin://expo-development-client/?url=http%3A%2F%2F127.0.0.1%3A18082",
  );
  const route = transportRouteUrl("http://127.0.0.1:3210/fixture", "run-one");
  expect(route).toContain("run_id=run-one");
  expect(route).toContain("fixture=http%3A%2F%2F127.0.0.1%3A3210%2Ffixture");
  expect(route).not.toMatch(/token|secret/);
});

test("runner refuses transport evidence when the current native app build fails", async () => {
  let prepared = false;
  let error: unknown;
  try {
    await runNativeTransport(
      "/unused",
      { IOS_SIMULATOR_UDID: OWNED_SIMULATOR_UDID },
      "none",
      () => {
        prepared = true;
        return Promise.reject(new Error("injected native build failure"));
      },
    );
  } catch (caught) {
    error = caught;
  }
  expect(error).toBeInstanceOf(Error);
  expect((error as Error).message).toBe("injected native build failure");
  expect(prepared).toBeTrue();
});

test("success requires every observation from the current run", () => {
  expect(validateScenarioResult(good, "run-one", "none").bytes_received).toBe(640);
  for (const [field, value, message] of [
    ["run_id", "stale", /run ID/],
    ["peer_ready", false, /peer/],
    ["microphone_frames", 0, /microphone/],
    ["packets_received", 0, /audio/],
    ["event_received", false, /SESSION_INIT/],
  ] as const) {
    expect(() => validateScenarioResult({ ...good, [field]: value }, "run-one", "none")).toThrow(
      message,
    );
  }
});

test("success rejects absent or malformed counters, not only zero ones", () => {
  for (const field of ["packets_received", "bytes_received", "microphone_frames"] as const) {
    const { [field]: _dropped, ...missing } = good;
    expect(() => validateScenarioResult(missing, "run-one", "none")).toThrow(/audio|microphone/);
    for (const malformed of [Number.NaN, Infinity, "4", null, 1.5]) {
      expect(() =>
        validateScenarioResult({ ...good, [field]: malformed }, "run-one", "none"),
      ).toThrow(/audio|microphone/);
    }
  }
});

test("withhold-audio accepts only its guard after unaffected evidence", () => {
  const result = {
    ...good,
    subscribed_publisher_identity: "",
    audio_track_sid: "",
    packets_received: 0,
    bytes_received: 0,
    guard_failed: "received-audio",
    expected_guard: "received-audio",
  };
  expect(validateScenarioResult(result, "run-one", "withhold-audio").event_received).toBeTrue();
  expect(() =>
    validateScenarioResult({ ...result, event_received: false }, "run-one", "withhold-audio"),
  ).toThrow(/SESSION_INIT/);
  expect(() =>
    validateScenarioResult(
      { ...result, guard_failed: "session-init-hud" },
      "run-one",
      "withhold-audio",
    ),
  ).toThrow(/received-audio/);
  // The withheld-audio counters are still evidence: absent is not the same as 0.
  for (const field of ["packets_received", "bytes_received"] as const) {
    const { [field]: _dropped, ...missing } = result;
    expect(() => validateScenarioResult(missing, "run-one", "withhold-audio")).toThrow(
      /unexpectedly/,
    );
    expect(() =>
      validateScenarioResult({ ...result, [field]: Number.NaN }, "run-one", "withhold-audio"),
    ).toThrow(/unexpectedly/);
  }
  const { microphone_frames: _mic, ...noMicrophone } = result;
  expect(() => validateScenarioResult(noMicrophone, "run-one", "withhold-audio")).toThrow(
    /microphone/,
  );
});

test("withhold-event accepts only its guard after audio evidence", () => {
  const result = {
    ...good,
    event_received: false,
    event_sender_identity: "",
    hud_character: "",
    hud_location: "",
    guard_failed: "session-init-hud",
    expected_guard: "session-init-hud",
  };
  expect(validateScenarioResult(result, "run-one", "withhold-event").packets_received).toBe(4);
  expect(() =>
    validateScenarioResult({ ...result, packets_received: 0 }, "run-one", "withhold-event"),
  ).toThrow(/audio/);
  expect(() =>
    validateScenarioResult({ ...result, hud_character: "stale" }, "run-one", "withhold-event"),
  ).toThrow(/unexpectedly/);
  for (const field of ["packets_received", "bytes_received", "microphone_frames"] as const) {
    const { [field]: _dropped, ...missing } = result;
    expect(() => validateScenarioResult(missing, "run-one", "withhold-event")).toThrow(
      /audio|microphone/,
    );
    expect(() =>
      validateScenarioResult({ ...result, [field]: Number.NaN }, "run-one", "withhold-event"),
    ).toThrow(/audio|microphone/);
  }
});
