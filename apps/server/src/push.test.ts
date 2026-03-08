import { test, expect, describe, mock, beforeEach } from "bun:test";

import { _setInternalSecretForTesting } from "./middleware.ts";
_setInternalSecretForTesting("test-secret");

let mockQueryResults: unknown[][] = [];
let queryCallIndex = 0;

function mockTaggedTemplate(_strings: TemplateStringsArray, ..._values: unknown[]) {
  const result = mockQueryResults[queryCallIndex] ?? [];
  queryCallIndex++;
  return Promise.resolve(result);
}

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(mockTaggedTemplate, {
    close: () => Promise.resolve(),
  });
  return { sql: mockSql };
});

const { handleStorePushToken, handleInternalPush } = await import("./push.ts");

function makeRequest(
  method: string,
  path: string,
  body?: Record<string, unknown>,
  headers?: Record<string, string>,
): Request {
  const opts: RequestInit = { method };
  if (body) {
    opts.body = JSON.stringify(body);
    opts.headers = { "Content-Type": "application/json", ...headers };
  } else if (headers) {
    opts.headers = headers;
  }
  return new Request(`http://localhost${path}`, opts);
}

beforeEach(() => {
  mockQueryResults = [];
  queryCallIndex = 0;
});

describe("handleStorePushToken", () => {
  test("stores a valid Expo push token", async () => {
    mockQueryResults = [[]]; // INSERT

    const req = makeRequest("POST", "/api/push-token", {
      token: "ExponentPushToken[abc123]",
      platform: "ios",
    });
    const res = await handleStorePushToken(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean };
    expect(body.ok).toBe(true);
  });

  test("rejects missing token", async () => {
    const req = makeRequest("POST", "/api/push-token", {});
    const res = await handleStorePushToken(req, "player_1");
    expect(res.status).toBe(400);
  });

  test("rejects invalid token format", async () => {
    const req = makeRequest("POST", "/api/push-token", {
      token: "invalid-token-format",
    });
    const res = await handleStorePushToken(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Invalid push token");
  });

  test("accepts ExpoPushToken format", async () => {
    mockQueryResults = [[]];

    const req = makeRequest("POST", "/api/push-token", {
      token: "ExpoPushToken[xyz789]",
    });
    const res = await handleStorePushToken(req, "player_1");
    expect(res.status).toBe(200);
  });
});

describe("handleInternalPush", () => {
  const secretHeaders = { "X-Internal-Secret": "test-secret" };

  test("sends push via internal endpoint", async () => {
    mockQueryResults = [
      [{ token: "ExponentPushToken[abc123]" }], // SELECT tokens
    ];

    const req = makeRequest(
      "POST",
      "/api/internal/push",
      {
        player_id: "player_1",
        title: "Activity Complete",
        body: "Your sword is ready.",
      },
      secretHeaders,
    );
    const res = await handleInternalPush(req);
    expect(res.status).toBe(200);
  });

  test("rejects missing required fields", async () => {
    const req = makeRequest(
      "POST",
      "/api/internal/push",
      {
        player_id: "player_1",
      },
      secretHeaders,
    );
    const res = await handleInternalPush(req);
    expect(res.status).toBe(400);
  });

  test("handles no tokens gracefully", async () => {
    mockQueryResults = [[]]; // No tokens

    const req = makeRequest(
      "POST",
      "/api/internal/push",
      {
        player_id: "player_1",
        title: "Test",
        body: "Test body",
      },
      secretHeaders,
    );
    const res = await handleInternalPush(req);
    expect(res.status).toBe(200);
  });

  test("rejects missing secret", async () => {
    const req = makeRequest("POST", "/api/internal/push", {
      player_id: "player_1",
      title: "Test",
      body: "Test body",
    });
    const res = await handleInternalPush(req);
    expect(res.status).toBe(401);
  });

  test("rejects missing Content-Type", async () => {
    const req = new Request("http://localhost/api/internal/push", {
      method: "POST",
      headers: { "X-Internal-Secret": "test-secret" },
      body: JSON.stringify({
        player_id: "player_1",
        title: "Test",
        body: "Test body",
      }),
    });
    const res = await handleInternalPush(req);
    expect(res.status).toBe(415);
  });
});

describe("handleStorePushToken Content-Type", () => {
  test("rejects missing Content-Type", async () => {
    const req = new Request("http://localhost/api/push-token", {
      method: "POST",
      body: JSON.stringify({ token: "ExponentPushToken[abc]" }),
    });
    const res = await handleStorePushToken(req, "player_1");
    expect(res.status).toBe(415);
  });
});
