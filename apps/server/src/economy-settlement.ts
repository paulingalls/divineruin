import { SETTLEMENT_PERSONALITY_VALUES, SETTLEMENT_SIZE_VALUES } from "@divineruin/shared";

export const ECONOMY_SIZES = [...SETTLEMENT_SIZE_VALUES, "capital"] as const;
export const ECONOMY_TRAITS = [...SETTLEMENT_PERSONALITY_VALUES, "trade_hub"] as const;
