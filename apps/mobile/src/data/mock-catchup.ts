import type { CatchUpCard } from "@/stores/catchup-store";

export const MOCK_CATCHUP_CARDS: CatchUpCard[] = [
  {
    id: "1",
    type: "world_news",
    title: "Market Prices Shift",
    summary: "Ironwood prices rose sharply after a supply route was disrupted near Greyvale.",
    timestamp: "2h ago",
    hasAudio: true,
  },
  {
    id: "2",
    type: "resolved",
    title: "Patrol Report Filed",
    summary: "The guild completed the eastern patrol. No anomalies detected this cycle.",
    timestamp: "5h ago",
    hasAudio: false,
  },
  {
    id: "3",
    type: "pending_decision",
    title: "A Stranger's Offer",
    summary: "A hooded figure left a sealed letter at the guild hall addressed to you.",
    timestamp: "8h ago",
    hasAudio: true,
  },
];
