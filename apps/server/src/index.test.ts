import { test, expect } from "bun:test";

test("POST /api/livekit/token rejects missing fields", async () => {
  const res = await fetch("http://localhost:3000/api/livekit/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  expect(res.status).toBe(400);
  const body = await res.json();
  expect(body.error).toContain("required");
});

test("POST /api/livekit/token rejects partial fields", async () => {
  const res = await fetch("http://localhost:3000/api/livekit/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ player_id: "test" }),
  });
  expect(res.status).toBe(400);
});

test("GET /api/hello still works", async () => {
  const res = await fetch("http://localhost:3000/api/hello");
  expect(res.status).toBe(200);
  const body = await res.json();
  expect(body.message).toBe("Hello, world!");
});
