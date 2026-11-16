import { test, expect } from "../fixtures/session.js";

test.describe("Session lifecycle", () => {
  test("session_end populates summary screen", async ({ sessionPage }) => {
    await sessionPage.injectSessionInit();

    await sessionPage.injectEvent({
      type: "session_end",
      summary: "You explored the ruins and discovered a hidden passage.",
      xp_earned: 200,
      items_found: ["Moonstone Amulet"],
      quest_progress: ["The Missing Merchant"],
      duration: 1800,
      next_hooks: ["The passage leads deeper underground."],
      story_moments: [],
    });

    // Phase watcher in session-test.tsx auto-navigates to /session-summary
    const summaryScreen = sessionPage.page.getByTestId("session-summary-screen");
    await expect(summaryScreen).toBeVisible();
    await expect(sessionPage.page.getByText("Session Complete")).toBeVisible();
    await expect(sessionPage.page.getByText(/explored the ruins/)).toBeVisible();
    await expect(sessionPage.page.getByText("RETURN HOME")).toBeVisible();
  });

  test("summary shows XP, items, and quest counts", async ({ sessionPage }) => {
    await sessionPage.injectSessionInit();

    await sessionPage.injectEvent({
      type: "session_end",
      summary: "A productive adventure.",
      xp_earned: 350,
      items_found: ["Iron Shield", "Health Potion"],
      quest_progress: ["The Missing Merchant", "Hollow Threat"],
      duration: 2700,
      next_hooks: [],
      story_moments: [],
    });

    const summaryScreen = sessionPage.page.getByTestId("session-summary-screen");
    await expect(summaryScreen).toBeVisible();

    // Stats row shows correct values
    await expect(sessionPage.page.getByText("350")).toBeVisible();
    await expect(sessionPage.page.getByText("XP")).toBeVisible();
    await expect(sessionPage.page.getByText("Items")).toBeVisible();
    await expect(sessionPage.page.getByText("Quests")).toBeVisible();
  });
});

test("production session shows dispatch error and retries with a fresh room", async ({
  characterPage,
}) => {
  const rooms: string[] = [];
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const error = "The DM could not join. Try again.";
  await characterPage.route("**/api/livekit/token", async (route) => {
    const body = route.request().postDataJSON() as { room_name: string };
    rooms.push(body.room_name);
    if (rooms.length === 2) await held;
    await route.fulfill({ status: 503, json: { error } });
  });
  try {
    await characterPage.goto("/session");
    await expect(characterPage.getByText("Connection failed", { exact: true })).toBeVisible();
    await expect(characterPage.getByText(error, { exact: true })).toBeVisible();
    const retry = characterPage.getByRole("button", { name: "Retry", exact: true });
    await expect(retry).toBeVisible();
    await retry.click();
    await expect.poll(() => rooms.length).toBe(2);
    expect(rooms[0]).toMatch(/^[a-zA-Z0-9_-]+$/);
    expect(rooms[1]).toMatch(/^[a-zA-Z0-9_-]+$/);
    expect(rooms[1]).not.toBe(rooms[0]);
    await expect(characterPage.getByText("Entering the world...", { exact: true })).toBeVisible();
    await expect(retry).toBeHidden();
    release();
    await expect(characterPage.getByText(error, { exact: true })).toBeVisible();
    await expect(retry).toBeVisible();
    expect(rooms).toHaveLength(2);
  } finally {
    release();
  }
});
