import { test, expect, describe, beforeEach, mock } from "bun:test";
import {
  dbMockFactory,
  setQueryStubs,
  resetMockDb,
  getCapturedQueries,
  makeRequest,
} from "./activities-test-mock.ts";

void mock.module("./db.ts", dbMockFactory);

const { handleCreateActivity } = await import("./activity_create.ts");

const { setupDangerLevelFixture } = await import("./test-fixtures/danger-levels.ts");
const { setupErrandTemplatesFixture } = await import("./test-fixtures/errand-templates.ts");

// Stub fragments are matched by SQL substring, order-independent; only row-returning
// queries need one. Errand dispatch derives the ASSIGNED companion from the player's class
// via the companions catalog (`data->'complements'`): warrior -> Lira, beastcaller -> Sable.
const playerWarrior = {
  match: "FROM players",
  result: [{ location_id: "millhaven", class: "warrior" }],
};
const playerBeastcaller = {
  match: "FROM players",
  result: [{ location_id: "millhaven", class: "beastcaller" }],
};
const companionLira = { match: "FROM companions", result: [{ id: "companion_lira" }] };
const companionSable = { match: "FROM companions", result: [{ id: "companion_sable" }] };
const slotsEmpty = { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 0 }] };

beforeEach(() => {
  resetMockDb();
  setupDangerLevelFixture();
  setupErrandTemplatesFixture();
});

describe("handleCreateActivity — companion errands", () => {
  test("creates companion errand", async () => {
    setQueryStubs([playerWarrior, companionLira, slotsEmpty]);

    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "scout", destination: "millhaven" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activity_id: string; status: string };
    expect(body.status).toBe("in_progress");
    // Errands stamp slot='companion' (the ActivitySlot value, not 'companion_errand');
    // countActiveBySlot's companion bucket matches both forms.
    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    expect((insert!.values[2] as { slot: string }).slot).toBe("companion");
  });

  test("rejects errand without errand_type", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { destination: "millhaven" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("errand_type");
  });

  test("rejects errand with invalid destination", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "scout", destination: "narnia" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Invalid destination");
  });

  test("rejects a social errand for a Sable-assigned player", async () => {
    setQueryStubs([playerBeastcaller, companionSable, slotsEmpty]);
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "social", destination: "millhaven_inn" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("companion_sable");
  });

  test("a caller naming Kael cannot smuggle a Sable player past the social block", async () => {
    // The old default (companion_id || "companion_kael") checked the block against Kael and
    // let this through; resolution then ran as Sable with an empty errand frame.
    setQueryStubs([playerBeastcaller, companionSable, slotsEmpty]);
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: {
        errand_type: "social",
        destination: "millhaven_inn",
        companion_id: "companion_kael",
      },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("assigned companion is companion_sable");
  });

  test("rejects an errand for a player with no class", async () => {
    setQueryStubs([
      { match: "FROM players", result: [{ location_id: "millhaven", class: null }] },
      slotsEmpty,
    ]);
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "scout", destination: "millhaven" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("no class");
  });

  test("rejects when companion slot is held by a 'resolving' row (story-004)", async () => {
    // The worker has CAS-claimed the row (status='resolving'). Without the
    // status filter widening, the slot would falsely show 0 and let a second
    // errand dispatch through, breaking the 1-companion cap.
    setQueryStubs([
      playerWarrior,
      companionLira,
      { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 1 }] },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "scout", destination: "millhaven" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error.toLowerCase()).toMatch(/companion/);
  });
});
