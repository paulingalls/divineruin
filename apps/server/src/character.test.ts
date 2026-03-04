import { test, expect, describe, mock } from "bun:test";

// Mock the db module before importing character handler
mock.module("./db.ts", () => {
  const mockSql = Object.assign(
    async (_strings: TemplateStringsArray, ..._values: unknown[]) => {
      return [];
    },
    { close: async () => {} },
  );
  return { sql: mockSql };
});

const { handleGetCharacter } = await import("./character.ts");

function makeRequest(): Request {
  return new Request("http://localhost/api/character/player-1", { method: "GET" });
}

describe("handleGetCharacter", () => {
  test("returns 404 when player not found", async () => {
    const res = await handleGetCharacter(makeRequest(), "player-1");
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("not found");
  });
});
