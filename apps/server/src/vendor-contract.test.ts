import { expect, test } from "bun:test";
import { GoogleGenAI } from "@google/genai";

const CONTRACT_CHILD = "DIVINERUIN_LIVEKIT_CONTRACT_CHILD";

if (process.env[CONTRACT_CHILD] === "1") {
  test("production player token carries only the expected standard participant grant", async () => {
    const [{ decodeJwt }, { mintParticipantToken }] = await Promise.all([
      import("jose"),
      import("./livekit.ts"),
    ]);
    const clients = {
      apiKey: "api-key",
      apiSecret: "a sufficiently long test secret",
    } as Parameters<typeof mintParticipantToken>[0];
    const claims = decodeJwt(await mintParticipantToken(clients, "room-7", "player-42"));

    expect(claims.sub).toBe("player-42");
    expect(claims.kind).toBe("standard");
    expect(claims.video).toEqual({
      roomJoin: true,
      room: "room-7",
      canPublish: true,
      canSubscribe: true,
      canPublishData: true,
      canPublishSources: ["microphone"],
      agent: false,
    });
  });
} else {
  test("production player token passes the isolated real LiveKit SDK contract", async () => {
    const child = Bun.spawn(["bun", "test", import.meta.path], {
      cwd: import.meta.dir,
      env: { ...process.env, [CONTRACT_CHILD]: "1" },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]);
    expect(exitCode, `${stdout}\n${stderr}`).toBe(0);
  });
}

test("installed Google GenAI client exposes the generation API", () => {
  const client = new GoogleGenAI({ apiKey: "test-key" });

  expect(client.models.generateContent).toBeFunction();
});
