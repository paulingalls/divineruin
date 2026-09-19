import { expect, test } from "bun:test";
import { GoogleGenAI } from "@google/genai";
import { decodeJwt } from "jose";
import { AccessToken } from "livekit-server-sdk";

test("installed LiveKit token carries the participant identity and room grant", async () => {
  const token = new AccessToken("api-key", "a sufficiently long test secret", {
    identity: "player-42",
    name: "player-42",
  });
  token.addGrant({ roomJoin: true, room: "room-7", canPublish: true });

  const claims = decodeJwt(await token.toJwt());

  expect(claims.sub).toBe("player-42");
  expect(claims.video).toMatchObject({ roomJoin: true, room: "room-7", canPublish: true });
});

test("installed Google GenAI client exposes the generation API", () => {
  const client = new GoogleGenAI({ apiKey: "test-key" });

  expect(client.models.generateContent).toBeFunction();
});
