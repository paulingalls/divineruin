import { test, expect, describe, beforeEach, mock } from "bun:test";
import { dbMockFactory, setQueryStubs, resetMockDb } from "./activities-test-mock.ts";

void mock.module("./db.ts", dbMockFactory);

const { resolveAssignedCompanion } = await import("./assigned_companion.ts");

beforeEach(resetMockDb);

// The error strings are byte-identical to the ones activity_create.ts returned before the
// extraction. That identity is what makes "activity_create_errand.test.ts still passes against
// the extracted version" a check rather than a claim — those tests assert on the text.
describe("resolveAssignedCompanion", () => {
  test("resolves the archetype's complement", async () => {
    setQueryStubs([
      { match: "FROM players", result: [{ class: "warrior" }] },
      { match: "FROM companions", result: [{ id: "companion_lira" }] },
    ]);

    const result = await resolveAssignedCompanion("player_1");
    expect(result).toEqual({ ok: true, companionId: "companion_lira" });
  });

  test("a player with no class is a 400, not a default companion", async () => {
    setQueryStubs([{ match: "FROM players", result: [{ class: null }] }]);

    const result = await resolveAssignedCompanion("player_1");
    expect(result).toEqual({
      ok: false,
      status: 400,
      error: "Player has no class; cannot dispatch an errand",
    });
  });

  test("an unknown player row is a 400", async () => {
    setQueryStubs([]);

    const result = await resolveAssignedCompanion("player_ghost");
    expect(result).toMatchObject({ ok: false, status: 400 });
  });

  test("an archetype matching zero companions fails loud", async () => {
    setQueryStubs([
      { match: "FROM players", result: [{ class: "necromancer" }] },
      { match: "FROM companions", result: [] },
    ]);

    const result = await resolveAssignedCompanion("player_1");
    expect(result).toEqual({
      ok: false,
      status: 500,
      error: "Archetype necromancer matches 0 companions",
    });
  });

  test("an archetype matching several companions fails loud, never picks the first", async () => {
    setQueryStubs([
      { match: "FROM players", result: [{ class: "warrior" }] },
      {
        match: "FROM companions",
        result: [{ id: "companion_lira" }, { id: "companion_tam" }],
      },
    ]);

    const result = await resolveAssignedCompanion("player_1");
    expect(result).toEqual({
      ok: false,
      status: 500,
      error: "Archetype warrior matches 2 companions",
    });
  });
});
