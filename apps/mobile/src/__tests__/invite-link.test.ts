import { afterEach, describe, expect, test } from "bun:test";

import { buildInviteUrl, fetchInviteUrl } from "@/utils/invite-link";

describe("buildInviteUrl", () => {
  test("builds a divineruin://join deep link with the code", () => {
    expect(buildInviteUrl("abc")).toBe("divineruin://join?code=abc");
  });

  test("encodes codes that need it", () => {
    expect(buildInviteUrl("a b/c")).toBe(`divineruin://join?code=${encodeURIComponent("a b/c")}`);
  });
});

describe("fetchInviteUrl", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function mockFetch(response: Response, capture?: { url?: string; init?: RequestInit }) {
    globalThis.fetch = ((url: string, init?: RequestInit) => {
      if (capture) {
        capture.url = url;
        capture.init = init;
      }
      return Promise.resolve(response);
    }) as unknown as typeof fetch;
  }

  test("posts room_name and resolves to the deep link", async () => {
    const capture: { url?: string; init?: RequestInit } = {};
    mockFetch(
      new Response(JSON.stringify({ code: "XYZ", expires_in: 1800 }), { status: 200 }),
      capture,
    );

    const result = await fetchInviteUrl("room-1", "https://api.example.com", {
      Authorization: "Bearer tok",
    });

    expect(result).toBe("divineruin://join?code=XYZ");
    expect(capture.url).toBe("https://api.example.com/api/livekit/invite");
    expect(capture.init?.method).toBe("POST");
    expect(JSON.parse(capture.init?.body as string)).toEqual({ room_name: "room-1" });
    expect((capture.init?.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  test("throws the server error when the response is not ok", async () => {
    mockFetch(new Response(JSON.stringify({ error: "room not found" }), { status: 404 }));

    let caught: unknown;
    try {
      await fetchInviteUrl("room-1", "https://api.example.com", {});
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("room not found");
  });
});
