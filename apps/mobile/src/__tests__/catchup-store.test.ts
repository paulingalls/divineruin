import { test, expect, beforeEach } from "bun:test";
import { catchupStore, type CatchUpCard } from "@/stores/catchup-store";

const SAMPLE_CARDS: CatchUpCard[] = [
  {
    id: "1",
    type: "world_news",
    title: "Market Prices Shift",
    summary: "Ironwood prices rose sharply.",
    timestamp: "2024-01-01T00:00:00Z",
    relativeTime: "2h ago",
    hasAudio: true,
    audioUrl: "/api/audio/news.mp3",
    decisionOptions: null,
    activityType: null,
    progress: null,
    locationId: null,
  },
  {
    id: "2",
    type: "resolved",
    title: "Patrol Complete",
    summary: "Eastern patrol found nothing.",
    timestamp: "2024-01-01T00:00:00Z",
    relativeTime: "5h ago",
    hasAudio: false,
    audioUrl: null,
    decisionOptions: null,
    activityType: "companion_errand",
    progress: null,
    locationId: null,
  },
];

beforeEach(() => {
  catchupStore.getState().clearCards();
});

test("initial state is empty", () => {
  expect(catchupStore.getState().cards).toEqual([]);
  expect(catchupStore.getState().loading).toBe(false);
  expect(catchupStore.getState().error).toBeNull();
  expect(catchupStore.getState().lastFetchedAt).toBeNull();
});

test("setCards populates cards", () => {
  catchupStore.getState().setCards(SAMPLE_CARDS);
  expect(catchupStore.getState().cards).toEqual(SAMPLE_CARDS);
});

test("setCards replaces existing cards", () => {
  catchupStore.getState().setCards(SAMPLE_CARDS);
  const newCards: CatchUpCard[] = [
    {
      id: "3",
      type: "pending_decision",
      title: "New Decision",
      summary: "A quest appeared.",
      timestamp: "2024-01-01T00:00:00Z",
      relativeTime: "1h ago",
      hasAudio: false,
      audioUrl: null,
      decisionOptions: [{ id: "accept", label: "Accept" }],
      activityType: "companion_errand",
      progress: null,
      locationId: null,
    },
  ];
  catchupStore.getState().setCards(newCards);
  expect(catchupStore.getState().cards).toEqual(newCards);
});

test("clearCards empties the list", () => {
  catchupStore.getState().setCards(SAMPLE_CARDS);
  catchupStore.getState().clearCards();
  expect(catchupStore.getState().cards).toEqual([]);
});

test("removeCard removes specific card", () => {
  catchupStore.getState().setCards(SAMPLE_CARDS);
  catchupStore.getState().removeCard("1");
  expect(catchupStore.getState().cards).toHaveLength(1);
  expect(catchupStore.getState().cards[0].id).toBe("2");
});

test("removeCard does nothing for non-existent id", () => {
  catchupStore.getState().setCards(SAMPLE_CARDS);
  catchupStore.getState().removeCard("nonexistent");
  expect(catchupStore.getState().cards).toHaveLength(2);
});

test("setLoading updates loading state", () => {
  catchupStore.getState().setLoading(true);
  expect(catchupStore.getState().loading).toBe(true);
  catchupStore.getState().setLoading(false);
  expect(catchupStore.getState().loading).toBe(false);
});

test("setError updates error and clears loading", () => {
  catchupStore.getState().setLoading(true);
  catchupStore.getState().setError("Network error");
  expect(catchupStore.getState().error).toBe("Network error");
  expect(catchupStore.getState().loading).toBe(false);
});

test("setFetched updates cards, clears loading/error, sets timestamp", () => {
  catchupStore.getState().setLoading(true);
  catchupStore.getState().setFetched(SAMPLE_CARDS);
  expect(catchupStore.getState().cards).toEqual(SAMPLE_CARDS);
  expect(catchupStore.getState().loading).toBe(false);
  expect(catchupStore.getState().error).toBeNull();
  expect(catchupStore.getState().lastFetchedAt).toBeGreaterThan(0);
});

test("CatchUpCard supports in_progress type with progress data", () => {
  const inProgressCard: CatchUpCard = {
    id: "4",
    type: "in_progress",
    title: "Iron Sword",
    summary: "Crafting in progress",
    timestamp: "2024-01-01T00:00:00Z",
    relativeTime: "30m ago",
    hasAudio: false,
    audioUrl: null,
    decisionOptions: null,
    activityType: "crafting",
    progress: {
      startTime: "2024-01-01T00:00:00Z",
      resolveAtEstimate: "2024-01-01T04:00:00Z",
      progressText: "The forge burns hot...",
      percentEstimate: 45,
    },
    locationId: null,
  };
  catchupStore.getState().setCards([inProgressCard]);
  const card = catchupStore.getState().cards[0];
  expect(card.type).toBe("in_progress");
  expect(card.progress?.percentEstimate).toBe(45);
  expect(card.progress?.progressText).toBe("The forge burns hot...");
});

test("CatchUpCard supports companion_idle type", () => {
  const idleCard: CatchUpCard = {
    id: "5",
    type: "companion_idle",
    title: "Companion",
    summary: "Kael is sharpening his blade.",
    timestamp: "2024-01-01T00:00:00Z",
    relativeTime: "now",
    hasAudio: false,
    audioUrl: null,
    decisionOptions: null,
    activityType: null,
    progress: null,
    locationId: null,
  };
  catchupStore.getState().setCards([idleCard]);
  expect(catchupStore.getState().cards[0].type).toBe("companion_idle");
});
