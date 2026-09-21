import { beforeEach, expect, test } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { transcriptStore } from "@/stores/transcript-store";

beforeEach(() => transcriptStore.getState().clear());

test("player transcript preserves the authenticated player id", () => {
  handleGameEvent({
    type: "transcript_entry",
    speaker: "player",
    player_id: "player-two",
    text: "I inspect the door.",
    timestamp: 123,
  });

  expect(transcriptStore.getState().entries[0]).toMatchObject({
    speaker: "player",
    playerId: "player-two",
    text: "I inspect the door.",
  });
});
