import { expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

await mock.module("expo-linear-gradient", () => ({ LinearGradient: () => null }));

const { TranscriptRow } = await import("@/components/transcript-view");
const entry = (playerId: string | null) => ({
  id: "1",
  speaker: "player" as const,
  playerId,
  character: null,
  emotion: null,
  text: "I inspect the door.",
  timestamp: 1,
});

test("a party member's line is labelled with the speaker, not You", () => {
  const html = renderToStaticMarkup(
    <TranscriptRow item={entry("player-two")} localPlayerId="player-one" />,
  );

  expect(html).toContain("player-two");
  expect(html).not.toContain(">You<");
});

test("the local player's own line stays You", () => {
  const html = renderToStaticMarkup(
    <TranscriptRow item={entry("player-one")} localPlayerId="player-one" />,
  );

  expect(html).toContain(">You<");
});

test("an unloaded character cannot relabel the local player as a stranger", () => {
  // characterStore is empty until session_init lands; before that every player line is the
  // local speaker's, and a raw id there is a regression on the single-player default path.
  const html = renderToStaticMarkup(<TranscriptRow item={entry("player-one")} />);

  expect(html).toContain(">You<");
  expect(html).not.toContain("player-one");
});
