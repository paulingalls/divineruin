export const MERCHANT_KIND_VALUES = ["general", "specialist", "exotic", "black_market"] as const;
export const INVENTORY_POOL_SINK_VALUES = [
  "maintenance",
  "subsistence",
  "combat",
  "progression",
  "crafting",
  "service",
  "lifestyle",
  "endgame",
] as const;

export const STOCK_SETTLEMENT_VALUES = ["hamlet", "village", "town", "city"] as const;
type StockSettlement = (typeof STOCK_SETTLEMENT_VALUES)[number];
type StockRange = [number, number];

export interface InventoryPoolTier2 {
  item_id: string;
  quantity_by_settlement: Record<StockSettlement, StockRange>;
}

export interface InventoryPoolTier3 {
  item_id: string;
  settlements: (StockSettlement | "capital")[];
  presence_chance: number;
  restock_check: "daily" | "weekly";
  rotation_group?: string;
  /** Units when present. An omitted range means one unit. */
  quantity?: StockRange;
}

export interface InventoryPool {
  id: string;
  name: string;
  type: string;
  merchant_kind: (typeof MERCHANT_KIND_VALUES)[number];
  sink_category: (typeof INVENTORY_POOL_SINK_VALUES)[number];
  buys: "all" | string[];
  buys_rarities: string[];
  tier_1_items: string[];
  tier_2_items: InventoryPoolTier2[];
  tier_3_items: InventoryPoolTier3[];
}
