import { beforeEach, expect, test } from "bun:test";
import fixture from "../../../agent/tests/native_transport/session_init_fixture.json";

import { handleGameEventMessage } from "@/audio/game-event-handler";
import {
  assertTransportResult,
  fetchTransportFixture,
  observeRemoteAudio,
  parseTransportFixture,
  validateFixtureEndpoint,
} from "@/audio/native-transport-observation";
import { characterStore } from "@/stores/character-store";
import { sessionStore } from "@/stores/session-store";

beforeEach(() => {
  characterStore.getState().clear();
  sessionStore.getState().reset();
});

async function expectAsyncError(action: () => Promise<unknown>, pattern: RegExp): Promise<void> {
  try {
    await action();
    throw new Error("expected action to reject");
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(pattern);
  }
}

test("loopback fixture is run-bound and rejects production or remote endpoints", () => {
  expect(validateFixtureEndpoint("http://127.0.0.1:3001/fixture", true)).toBe(
    "http://127.0.0.1:3001/fixture",
  );
  expect(() => validateFixtureEndpoint("http://localhost:3001/fixture", true)).not.toThrow();
  expect(() => validateFixtureEndpoint("https://example.com/fixture", true)).toThrow(/loopback/);
  expect(() => validateFixtureEndpoint("http://127.0.0.1:3001/fixture", false)).toThrow(
    /development/,
  );

  const parsed = parseTransportFixture(
    {
      run_id: "run-current",
      ws_url: "ws://127.0.0.1:49152",
      token: "secret-token",
      mobile_identity: "mobile-run-current",
      publisher_identity: "python-run-current",
    },
    "run-current",
  );
  expect(parsed.mobileIdentity).toBe("mobile-run-current");
  expect(() => parseTransportFixture({ ...parsed, run_id: "stale" }, "run-current")).toThrow(
    /run ID/,
  );
  expect(() =>
    parseTransportFixture(
      {
        run_id: "run-current",
        ws_url: "wss://live.example.com",
        token: "secret",
        mobile_identity: "mobile",
        publisher_identity: "python",
      },
      "run-current",
    ),
  ).toThrow(/loopback/);
});

test("release mode rejects before fixture fetch", async () => {
  let fetched = false;
  await expectAsyncError(
    () =>
      fetchTransportFixture("http://127.0.0.1:3001/fixture", "run-current", false, () => {
        fetched = true;
        return Promise.reject(new Error("fetch should not run"));
      }),
    /development/,
  );
  expect(fetched).toBeFalse();
});

test("real inbound audio stats are selected for the named publisher", async () => {
  const observed = await observeRemoteAudio(
    [
      {
        participantIdentity: "wrong-publisher",
        source: "microphone",
        trackSid: "wrong",
        track: { getRTCStatsReport: () => Promise.resolve(new Map()) },
      },
      {
        participantIdentity: "python-run-current",
        source: "microphone",
        trackSid: "TR_audio",
        track: {
          getRTCStatsReport: () =>
            Promise.resolve(
              new Map([
                [
                  "in-a",
                  { type: "inbound-rtp", kind: "audio", packetsReceived: 4, bytesReceived: 640 },
                ],
                [
                  "in-v",
                  { type: "inbound-rtp", kind: "video", packetsReceived: 99, bytesReceived: 99 },
                ],
                [
                  "out",
                  { type: "outbound-rtp", kind: "audio", packetsReceived: 99, bytesReceived: 99 },
                ],
              ]),
            ),
        },
      },
    ],
    "python-run-current",
  );
  expect(observed).toEqual({ trackSid: "TR_audio", packetsReceived: 4, bytesReceived: 640 });
});

test("audio observation rejects absent tracks and empty or zero real stats", async () => {
  await expectAsyncError(() => observeRemoteAudio([], "python"), /audio subscription/);
  const subscription = (report: Map<string, object>) => [
    {
      participantIdentity: "python",
      source: "microphone",
      trackSid: "TR_audio",
      track: { getRTCStatsReport: () => Promise.resolve(report) },
    },
  ];
  await expectAsyncError(
    () => observeRemoteAudio(subscription(new Map()), "python"),
    /inbound audio/,
  );
  await expectAsyncError(
    () =>
      observeRemoteAudio(
        subscription(
          new Map([
            ["zero", { type: "inbound-rtp", kind: "audio", packetsReceived: 0, bytesReceived: 0 }],
          ]),
        ),
        "python",
      ),
    /nonzero/,
  );
  await expectAsyncError(
    () =>
      observeRemoteAudio(
        subscription(new Map([["absent", { type: "inbound-rtp", kind: "audio" }]])),
        "python",
      ),
    /nonzero/,
  );
  await expectAsyncError(
    () =>
      observeRemoteAudio(
        subscription(
          new Map([
            [
              "nan",
              {
                type: "inbound-rtp",
                kind: "audio",
                packetsReceived: Number.NaN,
                bytesReceived: 640,
              },
            ],
          ]),
        ),
        "python",
      ),
    /not a finite number/,
  );
});

test("shared SESSION_INIT fixture crosses the production initializer", () => {
  handleGameEventMessage({
    payload: new TextEncoder().encode(JSON.stringify({ type: "session_init", ...fixture })),
    from: { isAgent: true },
  } as never);
  expect(characterStore.getState().character?.name).toBe("Upgrade Test Hero");
  expect(sessionStore.getState().locationContext?.locationName).toBe("Upgrade Test Room");
});

test("transport result requires every current-run observation and emits no token", () => {
  const good = {
    run_id: "run-current",
    room_name: "room-current",
    mobile_identity: "mobile-run-current",
    publisher_identity: "python-run-current",
    peer_ready: true,
    subscribed_publisher_identity: "python-run-current",
    audio_track_sid: "TR_audio",
    packets_received: 4,
    bytes_received: 640,
    microphone_frames: 3,
    event_received: true,
    event_sender_identity: "python-run-current",
    hud_character: "Upgrade Test Hero",
    hud_location: "Upgrade Test Room",
  };
  expect(assertTransportResult(good, "run-current").packets_received).toBe(4);
  for (const [field, value, message] of [
    ["peer_ready", false, /peer/],
    ["packets_received", 0, /audio/],
    ["microphone_frames", 0, /microphone/],
    ["event_received", false, /SESSION_INIT/],
    ["hud_character", "", /HUD/],
    ["run_id", "stale", /run ID/],
  ] as const) {
    expect(() => assertTransportResult({ ...good, [field]: value }, "run-current")).toThrow(
      message,
    );
  }
  for (const field of ["packets_received", "bytes_received", "microphone_frames"] as const) {
    const { [field]: _dropped, ...missing } = good;
    expect(() => assertTransportResult(missing, "run-current")).toThrow(/audio|microphone/);
    for (const malformed of [Number.NaN, Infinity, "4", null, 1.5]) {
      expect(() => assertTransportResult({ ...good, [field]: malformed }, "run-current")).toThrow(
        /audio|microphone/,
      );
    }
  }
  expect(() => assertTransportResult({ ...good, token: "leak" }, "run-current")).toThrow(
    /credential/,
  );
  expect(() =>
    assertTransportResult({ ...good, nested: { api_secret: "leak" } }, "run-current"),
  ).toThrow(/credential/);
});
