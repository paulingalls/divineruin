import { test, expect, describe } from "bun:test";
import {
  AMBIENT_IDLE_CHATTER,
  COMPANION_IDLE_CHATTER,
  chatterPool,
  getCompanionIdleChatter,
} from "./companion_chatter.ts";
import type { Companion } from "@divineruin/shared";

const companions = (await Bun.file(
  new URL("../../../content/companions.json", import.meta.url),
).json()) as Companion[];

// Same map, same carve-out, and the same two authoring rules as the Python half
// (apps/agent/tests/test_companion_vignette_content.py — read its docstring). A text guard
// cannot attribute a word to a speaker, so: gendered pronouns in a chatter line refer to the
// companion and to no one else, and no speech verb appears in a non-verbal companion's lines.
// they/them/their is not forbidden for the gendered companions — it is the neutral default.
const PRONOUNS: Record<string, string[]> = {
  male: ["he", "him", "his", "himself"],
  female: ["she", "her", "hers", "herself"],
  nonbinary: ["they", "them", "their", "theirs", "themselves"],
};
const NEUTRAL = "nonbinary";

const SPEECH_VERBS =
  `says say said speaks speak spoke talks talk talking mutters mutter muttering whispers
   whisper whispering murmurs murmur murmuring hums hum humming sings sing singing asks ask
   asked answers answer answered replies reply replied shouts shout tells tell told`.split(/\s+/);

const present = (words: string[], text: string): string[] =>
  words.filter((w) => new RegExp(`\\b${w}\\b`, "i").test(text));

const NAMES = companions.map((c) => c.name);
const PLAYER_IDS = Array.from({ length: 24 }, (_, i) => `player_${i}`);

describe("the four chatter sets", () => {
  test("there is a set for every companion in the catalog, and no other", () => {
    expect(Object.keys(COMPANION_IDLE_CHATTER).sort()).toEqual(companions.map((c) => c.id).sort());
  });

  test("each companion has exactly ten lines", () => {
    for (const c of companions) expect(COMPANION_IDLE_CHATTER[c.id]).toHaveLength(10);
  });

  // The five companion-free lines are the "and stay" clause of the card: they shipped before
  // this story and their text is not the story's to rewrite. Pinned by content, not by count.
  test("the five ambient lines are unchanged", () => {
    expect([...AMBIENT_IDLE_CHATTER]).toEqual([
      "A faint breeze stirs dust motes in the lamplight. Nothing stirs.",
      "Somewhere down the hall, someone drops a tankard. Then silence.",
      "Candlelight flickers across old maps pinned to the wall.",
      "A distant bell marks the hour. The guild hall settles deeper into silence.",
      "The floorboards creak as the building breathes in the wind.",
    ]);
  });

  test("a companion's lines name that companion and no other", () => {
    for (const c of companions) {
      for (const line of COMPANION_IDLE_CHATTER[c.id]!) {
        expect(line).toContain(c.name);
        for (const other of NAMES.filter((n) => n !== c.name)) expect(line).not.toContain(other);
      }
    }
  });
});

describe("AC4 — pronouns agree with content/companions.json", () => {
  test("no pool carries a gendered pronoun from another bucket", () => {
    for (const c of companions) {
      const text = chatterPool(c.id).join(" ");
      for (const [bucket, words] of Object.entries(PRONOUNS)) {
        if (bucket === c.gender || bucket === NEUTRAL) continue;
        expect({ id: c.id, leaked: present(words, text) }).toEqual({ id: c.id, leaked: [] });
      }
    }
  });

  // The neutral bucket is excluded for the reason the Python half spells out: they/them is
  // also the player's pronoun here, so this assertion greens on a set that never refers to the
  // companion at all. A nonbinary set rests on the negative check above, which does red on a
  // stray "he"/"she".
  test("every gendered set carries its own pronouns, so the check above is not vacuous", () => {
    for (const c of companions.filter((x) => x.gender !== NEUTRAL)) {
      const own = present(PRONOUNS[c.gender]!, COMPANION_IDLE_CHATTER[c.id]!.join(" "));
      expect({ id: c.id, own }).not.toEqual({ id: c.id, own: [] });
    }
  });
});

describe("AC4 — a non-verbal companion's presence carries no speech", () => {
  const nonVerbal = companions.filter((c) => c.non_verbal);

  test("the catalog has a non-verbal companion for this guard to bite on", () => {
    expect(nonVerbal.length).toBeGreaterThan(0);
  });

  test("no line in a non-verbal companion's pool attributes speech or quotes one", () => {
    for (const c of nonVerbal) {
      const text = chatterPool(c.id).join(" ");
      expect({ id: c.id, spoken: present(SPEECH_VERBS, text) }).toEqual({ id: c.id, spoken: [] });
      expect(text).not.toContain('"');
    }
  });
});

describe("getCompanionIdleChatter", () => {
  test("every draw comes from that companion's own pool", () => {
    for (const c of companions) {
      const pool = chatterPool(c.id);
      for (const playerId of PLAYER_IDS) {
        expect(pool).toContain(getCompanionIdleChatter(playerId, c.id));
      }
    }
  });

  test("no draw for one companion names another", () => {
    for (const c of companions) {
      const others = NAMES.filter((n) => n !== c.name);
      for (const playerId of PLAYER_IDS) {
        const line = getCompanionIdleChatter(playerId, c.id);
        for (const other of others) expect(line).not.toContain(other);
      }
    }
  });

  test("the same player and hour draws the same line", () => {
    expect(getCompanionIdleChatter("player_1", "companion_kael")).toBe(
      getCompanionIdleChatter("player_1", "companion_kael"),
    );
  });

  test("different players draw across the pool, not one line", () => {
    const drawn = new Set(PLAYER_IDS.map((p) => getCompanionIdleChatter(p, "companion_lira")));
    expect(drawn.size).toBeGreaterThan(1);
  });

  // Fail loud (constraint 4): an id the catalog has and this file does not is a content/code
  // disagreement, pinned green by the first test above. Defaulting to some companion's lines
  // is the exact defect this story deletes.
  test("an unknown companion id throws rather than defaulting", () => {
    expect(() => getCompanionIdleChatter("player_1", "companion_nobody")).toThrow(
      "companion_nobody",
    );
  });
});
