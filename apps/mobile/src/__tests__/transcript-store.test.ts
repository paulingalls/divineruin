import { test, expect, beforeEach } from "bun:test";
import { transcriptStore, type TranscriptEntry } from "@/stores/transcript-store";

function makeEntry(
  overrides: Partial<Omit<TranscriptEntry, "id">> = {},
): Omit<TranscriptEntry, "id"> {
  return {
    speaker: "dm",
    character: null,
    emotion: null,
    text: "The cave is dark.",
    timestamp: Date.now() / 1000,
    ...overrides,
  };
}

beforeEach(() => {
  transcriptStore.getState().clear();
});

test("initial state is empty", () => {
  expect(transcriptStore.getState().entries).toEqual([]);
});

test("addEntry appends an entry with a generated id", () => {
  transcriptStore.getState().addEntry(makeEntry({ text: "Hello" }));
  const entries = transcriptStore.getState().entries;
  expect(entries).toHaveLength(1);
  expect(entries[0].text).toBe("Hello");
  expect(entries[0].id).toBeDefined();
  expect(entries[0].speaker).toBe("dm");
});

test("addEntry preserves speaker types", () => {
  transcriptStore.getState().addEntry(makeEntry({ speaker: "player", text: "I attack" }));
  transcriptStore
    .getState()
    .addEntry(makeEntry({ speaker: "npc", character: "TORIN", text: "Not so fast" }));
  transcriptStore.getState().addEntry(makeEntry({ speaker: "tool", text: "roll_dice: 14" }));
  const entries = transcriptStore.getState().entries;
  expect(entries).toHaveLength(3);
  expect(entries[0].speaker).toBe("player");
  expect(entries[1].speaker).toBe("npc");
  expect(entries[1].character).toBe("TORIN");
  expect(entries[2].speaker).toBe("tool");
});

test("clear removes all entries", () => {
  transcriptStore.getState().addEntry(makeEntry());
  transcriptStore.getState().addEntry(makeEntry());
  transcriptStore.getState().clear();
  expect(transcriptStore.getState().entries).toEqual([]);
});

test("entries are capped at 200", () => {
  for (let i = 0; i < 210; i++) {
    transcriptStore.getState().addEntry(makeEntry({ text: `Entry ${i}` }));
  }
  const entries = transcriptStore.getState().entries;
  expect(entries).toHaveLength(200);
  // Oldest entries should have been dropped
  expect(entries[0].text).toBe("Entry 10");
  expect(entries[199].text).toBe("Entry 209");
});

test("entries have unique ids", () => {
  transcriptStore.getState().addEntry(makeEntry({ text: "first" }));
  transcriptStore.getState().addEntry(makeEntry({ text: "second" }));
  const entries = transcriptStore.getState().entries;
  expect(entries[0].id).not.toBe(entries[1].id);
});
