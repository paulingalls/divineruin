import { test, expect, jest } from "bun:test";
import { CREATION_CARD_TAP } from "@/audio/event-types";

// --- Debounce and payload logic tests (no React context needed) ---

const DEBOUNCE_MS = 500;

function makePayload(cardId: string, category: string): string {
  return JSON.stringify({
    type: CREATION_CARD_TAP,
    card_id: cardId,
    category,
  });
}

test("payload has correct shape", () => {
  const raw = makePayload("elari", "race");
  const parsed: unknown = JSON.parse(raw);
  expect(parsed).toEqual({
    type: "creation_card_tap",
    card_id: "elari",
    category: "race",
  });
});

test("payload encodes as valid Uint8Array", () => {
  const raw = makePayload("warrior", "class");
  const encoded = new TextEncoder().encode(raw);
  expect(encoded).toBeInstanceOf(Uint8Array);
  const decoded = new TextDecoder().decode(encoded);
  expect(JSON.parse(decoded)).toEqual({
    type: "creation_card_tap",
    card_id: "warrior",
    category: "class",
  });
});

test("debounce: rapid calls result in one send after delay", async () => {
  const send = jest.fn<(data: Uint8Array) => void>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  function sendHint(cardId: string, category: string) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      const payload = makePayload(cardId, category);
      send(new TextEncoder().encode(payload));
    }, DEBOUNCE_MS);
  }

  // Rapid taps
  sendHint("human", "race");
  sendHint("elari", "race");
  sendHint("korath", "race");

  // Not yet sent
  expect(send).not.toHaveBeenCalled();

  // Wait for debounce
  await new Promise((r) => setTimeout(r, DEBOUNCE_MS + 50));

  // Only the last call should have fired
  expect(send).toHaveBeenCalledTimes(1);
  const raw = new TextDecoder().decode(send.mock.calls[0][0]);
  expect(JSON.parse(raw)).toHaveProperty("card_id", "korath");
});
