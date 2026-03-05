import { test, expect, describe, mock } from "bun:test";

// Default mock returns empty (player not found)
let mockRows: unknown[] = [];

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(
    (_strings: TemplateStringsArray, ..._values: unknown[]) => {
      return Promise.resolve(mockRows);
    },
    { close: () => Promise.resolve() },
  );
  return { sql: mockSql };
});

const { handleGetCharacter } = await import("./character.ts");

function makeRequest(playerId = "player_1"): Request {
  return new Request(`http://localhost/api/character/${playerId}`, { method: "GET" });
}

describe("handleGetCharacter", () => {
  test("returns 404 when player not found", async () => {
    mockRows = [];
    const res = await handleGetCharacter(makeRequest("no_such_player"), "no_such_player");
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("not found");
  });

  test("returns character data from JSONB data column", async () => {
    mockRows = [
      {
        player_id: "player_1",
        data: {
          name: "Kael",
          level: 1,
          xp: 0,
          location_id: "accord_guild_hall",
          hp: { current: 25, max: 25 },
        },
        location_name: "Accord Guild Hall",
      },
    ];

    const res = await handleGetCharacter(makeRequest(), "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.player_id).toBe("player_1");
    expect(body.name).toBe("Kael");
    expect(body.level).toBe(1);
    expect(body.location_id).toBe("accord_guild_hall");
    expect(body.location_name).toBe("Accord Guild Hall");
    expect(body.hp_current).toBe(25);
    expect(body.hp_max).toBe(25);
  });

  test("handles missing optional fields gracefully", async () => {
    mockRows = [
      {
        player_id: "player_2",
        data: {},
        location_name: null,
      },
    ];

    const res = await handleGetCharacter(makeRequest("player_2"), "player_2");
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.name).toBe("Unknown");
    expect(body.level).toBe(1);
    expect(body.hp_current).toBe(0);
    expect(body.hp_max).toBe(0);
    expect(body.location_id).toBe("unknown");
    expect(body.location_name).toBe("unknown");
  });
});
