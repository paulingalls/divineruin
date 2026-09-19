export interface TransportFixture {
  runId: string;
  wsUrl: string;
  token: string;
  mobileIdentity: string;
  publisherIdentity: string;
}

interface TrackStats {
  getRTCStatsReport(): Promise<{ forEach(callback: (value: unknown) => void): void } | undefined>;
}

export interface AudioSubscription {
  participantIdentity: string;
  source: string;
  trackSid: string;
  track: TrackStats;
}

export interface AudioObservation {
  trackSid: string;
  packetsReceived: number;
  bytesReceived: number;
}

export function validateFixtureEndpoint(raw: string, development: boolean): string {
  if (!development) throw new Error("native transport route is available only in development");
  const url = new URL(raw);
  if (url.protocol !== "http:" || (url.hostname !== "127.0.0.1" && url.hostname !== "localhost")) {
    throw new Error("native transport fixture endpoint must use HTTP loopback");
  }
  if (!url.port) throw new Error("native transport fixture endpoint must name an ephemeral port");
  return url.toString().replace(/\/$/, "");
}

function requiredString(record: Record<string, unknown>, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || !value.trim()) throw new Error(`fixture ${field} is required`);
  return value;
}

export function parseTransportFixture(raw: unknown, expectedRunId: string): TransportFixture {
  if (!raw || typeof raw !== "object") throw new Error("fixture response must be an object");
  const record = raw as Record<string, unknown>;
  const runId = requiredString(record, "run_id");
  if (runId !== expectedRunId)
    throw new Error(`fixture run ID ${runId} does not match ${expectedRunId}`);
  const wsUrl = requiredString(record, "ws_url");
  const ws = new URL(wsUrl);
  if (
    (ws.protocol !== "ws:" && ws.protocol !== "wss:") ||
    (ws.hostname !== "127.0.0.1" && ws.hostname !== "localhost")
  ) {
    throw new Error("LiveKit fixture URL must use loopback WebSocket");
  }
  return {
    runId,
    wsUrl,
    token: requiredString(record, "token"),
    mobileIdentity: requiredString(record, "mobile_identity"),
    publisherIdentity: requiredString(record, "publisher_identity"),
  };
}

export async function fetchTransportFixture(
  endpoint: string,
  runId: string,
  development: boolean,
  request: (input: string) => Promise<Pick<Response, "ok" | "status" | "json">> = fetch,
): Promise<{ endpoint: string; fixture: TransportFixture }> {
  const safeEndpoint = validateFixtureEndpoint(endpoint, development);
  const response = await request(`${safeEndpoint}?run_id=${encodeURIComponent(runId)}`);
  if (!response.ok) throw new Error(`fixture endpoint returned HTTP ${response.status}`);
  return { endpoint: safeEndpoint, fixture: parseTransportFixture(await response.json(), runId) };
}

export function isPositiveCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

export function isZeroCount(value: unknown): value is number {
  return typeof value === "number" && value === 0;
}

/** An absent stat is 0; a present non-finite one is malformed vendor data, not 0. */
function readCounter(row: Record<string, unknown>, field: string): number {
  const value = row[field];
  if (value === undefined || value === null) return 0;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`RTC inbound audio ${field} is not a finite number`);
  }
  return value;
}

export async function observeRemoteAudio(
  subscriptions: AudioSubscription[],
  expectedPublisherIdentity: string,
): Promise<AudioObservation> {
  const subscription = subscriptions.find(
    (candidate) =>
      candidate.participantIdentity === expectedPublisherIdentity &&
      candidate.source.toLowerCase() === "microphone",
  );
  if (!subscription) {
    throw new Error(`missing audio subscription from publisher ${expectedPublisherIdentity}`);
  }
  const report = await subscription.track.getRTCStatsReport();
  if (!report) throw new Error("audio subscription returned no RTC stats report");
  let packetsReceived = 0;
  let bytesReceived = 0;
  let rows = 0;
  report.forEach((raw) => {
    if (!raw || typeof raw !== "object") return;
    const row = raw as Record<string, unknown>;
    const mediaKind = row.kind ?? row.mediaType;
    if (row.type !== "inbound-rtp" || mediaKind !== "audio") return;
    rows += 1;
    packetsReceived += readCounter(row, "packetsReceived");
    bytesReceived += readCounter(row, "bytesReceived");
  });
  if (rows === 0) throw new Error("RTC stats report has no inbound audio records");
  if (!isPositiveCount(packetsReceived) || !isPositiveCount(bytesReceived)) {
    throw new Error("RTC inbound audio must have nonzero packets and bytes");
  }
  return { trackSid: subscription.trackSid, packetsReceived, bytesReceived };
}

export interface TransportResult {
  run_id: string;
  room_name: string;
  mobile_identity: string;
  publisher_identity: string;
  peer_ready: boolean;
  subscribed_publisher_identity: string;
  audio_track_sid: string;
  packets_received: number;
  bytes_received: number;
  microphone_frames: number;
  event_received: boolean;
  event_sender_identity: string;
  hud_character: string;
  hud_location: string;
  [key: string]: unknown;
}

export function assertNoCredentials(value: unknown): void {
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    if (/token|secret|credential/i.test(key))
      throw new Error("transport evidence contains a credential field");
    assertNoCredentials(child);
  }
}

export function assertTransportResult(raw: unknown, expectedRunId: string): TransportResult {
  if (!raw || typeof raw !== "object") throw new Error("transport result must be an object");
  const result = raw as TransportResult;
  assertNoCredentials(result);
  if (result.run_id !== expectedRunId) throw new Error("transport result has stale run ID");
  if (!result.peer_ready || !result.mobile_identity || !result.publisher_identity) {
    throw new Error("transport result is missing peer readiness or identities");
  }
  if (
    result.subscribed_publisher_identity !== result.publisher_identity ||
    !result.audio_track_sid ||
    !isPositiveCount(result.packets_received) ||
    !isPositiveCount(result.bytes_received)
  ) {
    throw new Error("transport result is missing received audio evidence");
  }
  if (!isPositiveCount(result.microphone_frames)) {
    throw new Error("transport result has no microphone frames");
  }
  if (!result.event_received || result.event_sender_identity !== result.publisher_identity) {
    throw new Error("transport result is missing current-run SESSION_INIT evidence");
  }
  if (result.hud_character !== "Upgrade Test Hero" || result.hud_location !== "Upgrade Test Room") {
    throw new Error("transport result is missing expected HUD values");
  }
  return result;
}
