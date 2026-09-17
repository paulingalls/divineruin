import { beforeEach, describe, expect, mock, test } from "bun:test";
import {
  dbMockFactory,
  getCapturedQueries,
  makeRequest,
  resetMockDb,
  setQueryStubs,
} from "./activities-test-mock.ts";
import { parseArchetypeRow, setArchetypes } from "./archetypes.ts";
import { parseSpellRow, setSpells } from "./spells.ts";

void mock.module("./db.ts", dbMockFactory);

const { handleCreateActivity } = await import("./activity_create.ts");
const { setupTrainingConfigFixture } = await import("./test-fixtures/training-config.ts");

const spellsPath = new URL("../../../content/spells.json", import.meta.url);
const archetypesPath = new URL("../../../content/archetypes.json", import.meta.url);
const spellRows = (await Bun.file(spellsPath).json()) as Record<string, unknown>[];
const archetypeRows = (await Bun.file(archetypesPath).json()) as Record<string, unknown>[];

const slotsEmpty = { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 0 }] };
const playerMage = { match: "FROM players", result: [{ class: "mage" }] };
const knownEmpty = { match: "FROM character_spells", result: [] };

function setupCatalogs(): void {
  setSpells(
    new Map(
      spellRows.map((row) => {
        const id = row.id as string;
        return [id, parseSpellRow(id, row)];
      }),
    ),
  );
  setArchetypes(
    new Map(
      archetypeRows.map((row) => {
        const id = row.id as string;
        return [id, parseArchetypeRow(id, row)];
      }),
    ),
  );
}

function trainingInserts() {
  return getCapturedQueries().filter((query) =>
    query.sql.includes("INSERT INTO training_activities"),
  );
}

beforeEach(() => {
  resetMockDb();
  setupTrainingConfigFixture();
  setupCatalogs();
});

describe("handleCreateActivity training", () => {
  test("creates ordinary training without a spell field", async () => {
    setQueryStubs([slotsEmpty]);

    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "combat_basics" },
      }),
      "player_1",
    );

    expect(res.status).toBe(200);
    const body = (await res.json()) as { activity_id: string; state: string };
    expect(body.activity_id).toStartWith("train_");
    expect(body.state).toBe("running_first_half");
    const data = trainingInserts()[0]!.values[4] as Record<string, unknown>;
    expect(data.spell_id).toBeUndefined();
  });

  test("rejects unknown training program", async () => {
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "underwater_basket_weaving" },
      }),
      "player_1",
    );
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("Unknown training program");
  });

  test("rejects training without program_id", async () => {
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", { type: "training", parameters: {} }),
      "player_1",
    );
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("program_id");
  });

  // Both refusals below assert their MESSAGE, not just the 400: an absent spell_id and a
  // non-string one both reach getSpell() and 400 as "Unknown spell", so a status-only
  // assertion passes with the guard deleted (constraint 1).
  test("rejects spell training without spell_id before insert", async () => {
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("spell_id is required");
    expect(trainingInserts()).toHaveLength(0);
  });

  test("rejects a malformed spell_id before insert", async () => {
    setQueryStubs([playerMage, knownEmpty, slotsEmpty]);
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: 42 },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("non-empty string");
    expect(trainingInserts()).toHaveLength(0);
  });

  test("rejects an unknown spell before insert", async () => {
    setQueryStubs([playerMage, knownEmpty, slotsEmpty]);
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: "unknown_spell" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(trainingInserts()).toHaveLength(0);
  });

  test("rejects a spell from the wrong tier before insert", async () => {
    setQueryStubs([playerMage, knownEmpty, slotsEmpty]);
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: "arcane_fireball" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(trainingInserts()).toHaveLength(0);
  });

  test("rejects an off-source spell before insert", async () => {
    setQueryStubs([{ match: "FROM players", result: [{ class: "cleric" }] }]);
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: "arcane_hold_person" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(trainingInserts()).toHaveLength(0);
  });

  test("rejects spell training when the player class is missing", async () => {
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: "arcane_hold_person" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(trainingInserts()).toHaveLength(0);
  });

  test("rejects spell training for an unknown player class", async () => {
    setQueryStubs([{ match: "FROM players", result: [{ class: "unknown" }] }]);
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: "arcane_hold_person" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(trainingInserts()).toHaveLength(0);
  });

  test("rejects an already-known spell before insert", async () => {
    setQueryStubs([
      playerMage,
      { match: "FROM character_spells", result: [{ spell_id: "arcane_hold_person" }] },
    ]);
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: "arcane_hold_person" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(trainingInserts()).toHaveLength(0);
  });

  test("persists the studied spell for a valid mage request", async () => {
    setQueryStubs([playerMage, knownEmpty, slotsEmpty]);
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "arcane_study", spell_id: "arcane_hold_person" },
      }),
      "player_1",
    );

    expect(res.status).toBe(200);
    const data = trainingInserts()[0]!.values[4] as Record<string, unknown>;
    expect(data.spell_id).toBe("arcane_hold_person");
  });

  test("rejects a spell_id for non-spell training before insert", async () => {
    const res = await handleCreateActivity(
      makeRequest("POST", "/api/activities", {
        type: "training",
        parameters: { program_id: "combat_basics", spell_id: "arcane_hold_person" },
      }),
      "player_1",
    );

    expect(res.status).toBe(400);
    expect(trainingInserts()).toHaveLength(0);
  });
});
