import { type Page } from "@playwright/test";
import { test as authTest, queryDb } from "./auth.js";

export interface TestCharacter {
  playerId: string;
  name: string;
  race: string;
  className: string;
  level: number;
  locationId: string;
  locationName: string;
}

export const TEST_CHARACTER = {
  name: "Edrin Ashvale",
  race: "Human",
  class: "Warden",
  level: 3,
  xp: 450,
  location_id: "accord_hearthstone_tavern",
  hp: { current: 28, max: 32 },
  portrait_url: null,
};

async function seedCharacter(playerId: string): Promise<TestCharacter> {
  await queryDb(
    `UPDATE players SET data = $1::jsonb WHERE player_id = $2`,
    [JSON.stringify(TEST_CHARACTER), playerId],
  );
  return {
    playerId,
    name: TEST_CHARACTER.name,
    race: TEST_CHARACTER.race,
    className: TEST_CHARACTER.class,
    level: TEST_CHARACTER.level,
    locationId: TEST_CHARACTER.location_id,
    locationName: "The Hearthstone Tavern",
  };
}

export async function seedActivity(
  playerId: string,
  opts: {
    id: string;
    type: string;
    status: string;
    narrationText?: string;
    narrationSummary?: string;
    decisionOptions?: { id: string; label: string }[];
    parameters?: Record<string, unknown>;
    startTime?: Date;
    resolveAt?: Date;
    progressStages?: string[];
  },
): Promise<void> {
  const now = new Date();
  const data: Record<string, unknown> = {
    status: opts.status,
    activity_type: opts.type,
    start_time: (opts.startTime ?? new Date(now.getTime() - 3_600_000)).toISOString(),
    resolve_at: (opts.resolveAt ?? new Date(now.getTime() - 60_000)).toISOString(),
    narration_text: opts.narrationText ?? null,
    narration_summary: opts.narrationSummary ?? opts.narrationText ?? null,
    narration_audio_url: null,
    decision_options: opts.decisionOptions ?? null,
    parameters: opts.parameters ?? {},
  };
  if (opts.progressStages) {
    data.progress_stages = opts.progressStages;
  }
  await queryDb(
    `INSERT INTO async_activities (id, player_id, data)
     VALUES ($1, $2, $3::jsonb)
     ON CONFLICT (id) DO UPDATE SET data = $3::jsonb`,
    [opts.id, playerId, JSON.stringify(data)],
  );
}

async function cleanupCharacterData(playerId: string): Promise<void> {
  try {
    await queryDb(
      `DELETE FROM async_activities WHERE player_id = $1; UPDATE players SET data = '{}'::jsonb WHERE player_id = $1`,
      [playerId],
    );
  } catch {
    // best-effort
  }
}

export const test = authTest.extend<
  {
    characterPage: Page;
    testCharacter: TestCharacter;
  },
  { seededCharacter: TestCharacter }
>({
  seededCharacter: [
    async ({ testUser }, use) => {
      const character = await seedCharacter(testUser.playerId);
      await use(character);
      await cleanupCharacterData(testUser.playerId);
    },
    { scope: "worker" },
  ],

  testCharacter: async ({ seededCharacter }, use) => {
    await use(seededCharacter);
  },

  characterPage: async ({ authenticatedPage, seededCharacter: _ }, use) => {
    // authenticatedPage already has auth injected, and seededCharacter
    // ensures character data exists. Reload to pick up character.
    await authenticatedPage.goto("/");
    await authenticatedPage.waitForLoadState("domcontentloaded");
    await use(authenticatedPage);
  },
});

export { expect } from "@playwright/test";
export { queryDb };
