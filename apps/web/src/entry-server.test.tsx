import { test, expect } from "bun:test";
import { renderAppHTML } from "./entry-server.tsx";

test("renderAppHTML prerenders the hero content", async () => {
  const html = await renderAppHTML();
  expect(html).toContain("Divine Ruin");
});

test("renderAppHTML includes the waitlist call to action", async () => {
  const html = await renderAppHTML();
  expect(html).toContain("waitlist");
});
