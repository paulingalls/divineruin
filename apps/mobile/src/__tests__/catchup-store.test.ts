import { test, expect, beforeEach } from "bun:test";
import { catchupStore, type CatchUpCard } from "@/stores/catchup-store";

const SAMPLE_CARDS: CatchUpCard[] = [
  {
    id: "1",
    type: "world_news",
    title: "Market Prices Shift",
    summary: "Ironwood prices rose sharply.",
    timestamp: "2h ago",
    hasAudio: true,
  },
  {
    id: "2",
    type: "resolved",
    title: "Patrol Complete",
    summary: "Eastern patrol found nothing.",
    timestamp: "5h ago",
    hasAudio: false,
  },
];

beforeEach(() => {
  catchupStore.getState().clearCards();
});

test("initial state is empty", () => {
  expect(catchupStore.getState().cards).toEqual([]);
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
      type: "quest_update",
      title: "New Quest",
      summary: "A quest appeared.",
      timestamp: "1h ago",
      hasAudio: false,
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
